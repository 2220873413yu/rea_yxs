"""Explicit platform-scoped role discovery and one-shot, user-confirmed pass-card binding."""
from dataclasses import dataclass,field
import base64
import hashlib
import json
import os
from pathlib import Path
from .auth import BGW
from .transport import Session,ServiceError
from .secure_store import crypt
from .gifts import GiftClient
from . import protocol as p
from .binding_session import check_binding_session
from .context import account_context,request_headers

GID=1187
PLATFORMS={'android':'安卓','ios':'iOS'}
PROVIDERS={'qq':'QQ','wx':'微信'}


def decode_label(value):
    """Decode URL-safe native role labels, retaining ordinary Unicode names unchanged."""
    if not isinstance(value,str):raise ServiceError('角色名称格式异常')
    try:
        decoded=base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True).decode('utf-8')
        if decoded and decoded.isprintable():return decoded
    except (ValueError,UnicodeError):pass
    return value


@dataclass(frozen=True)
class LoginChoice:
    """Keep the user's game platform separate from OAuth provider and heart-club client device."""
    device:str
    provider:str

    def __post_init__(self):
        """Reject missing selections before any QR or game-role request is dispatched."""
        if self.device not in PLATFORMS or self.provider not in PROVIDERS:
            raise ServiceError('请先选择安卓或iOS，以及QQ或微信。')

    @property
    def label(self):
        """Return the explicitly chosen game login combination for confirmations."""
        return PLATFORMS[self.device]+' '+PROVIDERS[self.provider]


class RoleConsentRequired(ServiceError):
    """Signal the native private-information consent gate without bypassing is_auth."""


@dataclass(frozen=True)
class Partition:
    """Expose only a server-returned partition identifier and decoded picker label."""
    id:int
    name:str


@dataclass(frozen=True)
class Role:
    """Keep owner-scoped server role identifiers private and out of repr/UI projections."""
    owner:str=field(repr=False)
    choice:LoginChoice
    partition:int
    name:str
    partition_name:str
    raw:dict=field(repr=False,compare=False)

    @property
    def label(self):
        """Describe the selected platform and actual role's server label without guessing from nickname."""
        return self.choice.label+' / '+self.partition_name+' / '+self.name

    def wire(self):
        """Serialize only the verified amp2.Role fields, preserving server-provided encoded labels."""
        out=b''
        for tag,key in enumerate(('game_open_id','game_app_id','area_id','plat_id','partition_id',
                                  'partition_name','role_id','role_name','device'),1):
            value=self.raw[key]
            out+=p.varint(tag<<3)+p.varint(value) if tag in (3,4,5) else p.message_string(tag,value)
        return out

    def identity(self):
        """Compare complete account/platform/role snapshots before a binding write, not just equal names."""
        return hashlib.sha256(self.owner.encode()+self.wire()).hexdigest()

    def binding_key(self):
        """Keep durable duplicate protection stable when a nickname or display label changes."""
        identity=[self.owner,self.choice.device,self.raw['game_open_id'],self.raw['game_app_id'],
                  self.raw['role_id'],self.raw['partition_id'],self.raw['plat_id']]
        return hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class BindingRepair:
    """Freeze the exact current recipient shown in the separate repair confirmation."""
    role:Role
    restricted:bool
    wire:bytes=field(repr=False)


class RoleClient:
    """Isolate one account's explicit role reads, private consent, and pass-card binding from all claims."""
    def __init__(self,session=None,attempt_folder=None):
        """Use a fresh transport and durable one-shot binding guards; construction sends no requests."""
        self.session=session or Session()
        self.attempt_folder=Path(attempt_folder) if attempt_folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/binding_attempts'

    def check_account(self,account,choice):
        """Validate ownership and return an immutable platform-scoped copy for this picker operation."""
        if not isinstance(choice,LoginChoice) or account.get('provider')!=choice.provider:
            raise ServiceError('账号与登录方式不一致，请重新选择。')
        return account_context(account,choice.device)

    def read(self,path,body,account):
        """Read a native JSON role endpoint and surface privacy gates and safe numeric errors only."""
        result=self.session.json(BGW+path,body,request_headers(account))
        code=result.get('ret')
        if code==400000:
            raise RoleConsentRequired('心悦俱乐部将获取你在《英雄杀》的大区信息、角色昵称，以发放游戏权益内容。')
        if code!=0:raise ServiceError('角色查询被拒绝，返回码：'+str(code))
        return result

    def consent_private(self,account,choice):
        """Submit the person's explicit game-info consent once, using native private visibility action 2."""
        account=self.check_account(account,choice)
        entry=p.message_string(1,'GameRole')+p.message_string(2,'{"gid":1187, "authAction":2}')
        body=p.varint(10)+p.varint(len(entry))+entry
        response=self.session.request(BGW+'xyapi.PageService/UpdateSettingSwitch',body,request_headers(account))
        self.checked_response(response,'资料授权')

    def partitions(self,account,choice):
        """Validate the current ticket using native CheckBind before reading the explicitly requested platform."""
        account=self.check_account(account,choice)
        check_binding_session(account,self.session)
        result=self.read('amp2.RoleSrv/GetPartitionList',{'gid':GID,'device':choice.device,
                         'is_auth':True,'area_channel_id':''},account)
        rows=result.get('list')
        if not isinstance(rows,list):raise ServiceError('服务器未返回区服列表。')
        out=[]
        for row in rows:
            if not isinstance(row,dict) or type(row.get('id')) is not int or row['id']<0:
                raise ServiceError('服务器区服资料不完整。')
            out.append(Partition(row['id'],decode_label(row.get('name',''))))
        return tuple(out)

    def roles(self,account,choice,partition):
        """Read bounded pages for the selected server partition and deduplicate without changing platform."""
        account=self.check_account(account,choice)
        page=1;pages=set();out={}
        while page not in pages and len(pages)<20:
            pages.add(page)
            result=self.read('amp2.RoleSrv/GetSpecifyRoleList',{'partition_id':partition.id,'gid':GID,
                'device':choice.device,'page_no':page,'is_auth':True,'area_channel_id':''},account)
            rows=result.get('roles')
            if not isinstance(rows,list):raise ServiceError('服务器未返回角色列表。')
            for row in rows:
                raw=dict(row) if isinstance(row,dict) else {}
                strings=('game_open_id','game_app_id','partition_name','role_id','role_name','device')
                if any(not isinstance(raw.get(k),str) or not raw[k] for k in strings):
                    raise ServiceError('服务器角色资料不完整，请重新查询。')
                if any(type(raw.get(k)) is not int or raw[k]<0 for k in ('area_id','plat_id','partition_id')):
                    raise ServiceError('服务器角色区服标识不完整。')
                if raw['device']!=choice.device or raw['plat_id']!=(0 if choice.device=='ios' else 1):
                    raise ServiceError('角色返回平台与所选平台不一致，已停止，不自动猜测。')
                if raw['partition_id']!=partition.id:raise ServiceError('角色返回区服与所选区服不一致。')
                role=Role(account['profile_id'],choice,partition.id,decode_label(raw['role_name']),decode_label(raw['partition_name']),raw)
                out[role.identity()]=role
            next_page=result.get('next_page_no',-1)
            if next_page==-1:return tuple(out.values())
            if type(next_page) is not int or next_page<1 or next_page in pages:
                raise ServiceError('服务器角色分页异常，已停止。')
            page=next_page
        raise ServiceError('角色分页超过限制，未提交绑定。')

    def checked_response(self,response,action):
        """Require an explicit native success envelope; never echo a raw server response or token."""
        if response.status!=200:raise ServiceError(action+'HTTP错误：'+str(response.status))
        if 'json' in response.headers.get('Content-Type',''):
            try:code=json.loads(response.body).get('ret')
            except (ValueError,AttributeError):code='未知'
        else:code=p.get(p.parse(response.body),1,0)
        if code!=0:raise ServiceError(action+'被拒绝，返回码：'+str(code))

    def current_binding(self,account):
        """Read the pass-card binding and restriction flags without fetching or claiming gift rewards."""
        client=GiftClient(self.session);_,_,restricted=client.binding(account)
        return client._bound_role,restricted

    def confirm_native_role(self,account,role):
        """Complete the observed native xinyue role-selection acknowledgement once, without rebinding the pass card."""
        account=self.check_account(account,role.choice)
        if role.owner!=account['profile_id']:raise ServiceError('角色确认不属于当前账号。')
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        marker=self.attempt_folder/('register-'+role.binding_key()+'.json')
        if marker.exists():
            try:state=json.loads(marker.read_text(encoding='utf-8')).get('state')
            except (OSError,ValueError,AttributeError):state='uncertain'
            if state=='confirmed_response':return
            raise ServiceError('原生角色确认已有未完成记录，不重复提交，请只读核对。')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched'},file);file.flush();os.fsync(file.fileno())
        except FileExistsError:raise ServiceError('原生角色确认正在处理，不重复提交。') from None
        body={'scene':'xinyue','gid':GID,'device':role.choice.device,
              'role':{key:role.raw[key] for key in ('game_open_id','game_app_id','area_id','plat_id',
                       'partition_id','partition_name','role_id','role_name','device')},'is_auth':True}
        result=self.session.json(BGW+'amp2.RoleSrv/BindRole',body,request_headers(account))
        marker.with_suffix('.dpapi').write_bytes(b'XYBIND1\0'+crypt(json.dumps(result,ensure_ascii=False).encode('utf-8')))
        if result.get('ret')!=0:raise ServiceError('原生角色确认被拒绝，返回码：'+str(result.get('ret')))
        marker.write_text(json.dumps({'state':'confirmed_response'}),encoding='utf-8')

    def prepare_repair(self,account):
        """Read the actual bound platform/recipient; never take a replacement from the role picker."""
        wire,restricted=self.current_binding(account)
        if not wire:raise ServiceError('服务器当前没有英雄杀绑定，请使用正常角色选择流程。')
        fields=p.parse(wire)
        names=('game_open_id','game_app_id','area_id','plat_id','partition_id','partition_name','role_id','role_name','device')
        raw={key:(p.get(fields,tag,0) if tag in (3,4,5) else p.text(p.get(fields,tag,b'')))
             for tag,key in enumerate(names,1)}
        device=raw['device']
        if device not in PLATFORMS or raw['plat_id']!=(0 if device=='ios' else 1):
            raise ServiceError('服务器当前绑定平台不完整或不一致，不能自动判断，请在原生APP核对。')
        if any(not raw[k] for k in ('game_open_id','game_app_id','role_id','role_name','partition_name')):
            raise ServiceError('服务器当前绑定资料不完整，不能进行解绑重绑。')
        choice=LoginChoice(device,account['provider'])
        role=Role(account['profile_id'],choice,raw['partition_id'],decode_label(raw['role_name']),decode_label(raw['partition_name']),raw)
        return BindingRepair(role,restricted,wire)

    def repair(self,account,snapshot):
        """After explicit confirmation, unbind once and bind back the exact same recipient, stopping on any failure."""
        role=snapshot.role;account=self.check_account(account,role.choice)
        if role.owner!=account['profile_id']:raise ServiceError('确认的绑定不属于当前账号，已停止。')
        check_binding_session(account,self.session)
        # Revalidate both the displayed binding snapshot and the account's own role list before either write.
        current,restricted=self.current_binding(account)
        if current!=snapshot.wire:raise ServiceError('当前绑定已变化，请重新检查并确认；未解绑。')
        if not restricted:return '服务器当前绑定已不受限，本次未解绑或重绑。'
        fresh=self.roles(account,role.choice,Partition(role.partition,role.partition_name))
        if not any(candidate.binding_key()==role.binding_key() for candidate in fresh):
            raise ServiceError('未能在本账号角色列表中确认当前绑定，未解绑。')
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        marker=self.attempt_folder/('repair-'+role.binding_key()+'.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'unbind_dispatched'},file);file.flush();os.fsync(file.fileno())
        except FileExistsError:
            raise ServiceError('此角色已有受限处理记录，请只读核对或在原生APP处理；不会重复解绑重绑。') from None
        body=p.varint(8)+p.varint(GID)+p.varint(18)+p.varint(len(snapshot.wire))+snapshot.wire
        stage='解除绑定'
        try:
            response=self.session.request(BGW+'xyapp.GiftSrv/PassCardUnbindGameRole',body,request_headers(account))
            marker.with_suffix('.unbind.dpapi').write_bytes(b'XYBIND1\0'+crypt(response.body))
            self.checked_response(response,'解除礼包绑定')
            current,_=self.current_binding(account)
            if current:raise ServiceError('解除后仍有绑定，已停止，不覆盖任何角色。')
            check_binding_session(account,self.session,require_allowed=True)
            # Only a confirmed empty binding permits the second and final write, using the original wire bytes.
            stage='重新绑定'
            marker.write_text(json.dumps({'state':'rebind_dispatched'}),encoding='utf-8')
            response=self.session.request(BGW+'xyapp.GiftSrv/PassCardBindGameRoleV2',body,request_headers(account))
            marker.with_suffix('.rebind.dpapi').write_bytes(b'XYBIND1\0'+crypt(response.body))
            self.checked_response(response,'重新绑定礼包角色')
            current,restricted=self.current_binding(account)
            if not self.matches(current,role):raise ServiceError('当前绑定未核对一致。')
            if restricted:raise ServiceError('角色已重新绑定，但服务器仍返回受限标记，请在原生APP核对资格。')
            marker.write_text(json.dumps({'state':'verified'}),encoding='utf-8')
            return '处理成功，服务器已确认绑定且不受限：'+role.label+'；未签到、领奖或兑换。'
        except Exception as error:
            detail=str(error) if isinstance(error,ServiceError) else '响应或本地记录未完成。'
            raise ServiceError(stage+'阶段停止：'+detail+' 可能暂时没有礼包绑定；仅查询核对，不自动重试。') from None

    @staticmethod
    def matches(wire,role):
        """Match stable recipient/platform fields; display-name changes do not require a new binding."""
        if not wire:return False
        current=p.parse(wire);wanted=p.parse(role.wire())
        return all(p.get(current,tag,0 if tag in (3,4,5) else b'')==value
                   for tag,_,value in wanted if tag in (1,2,3,4,5,7,9))

    def reserve_binding_attempt(self,role):
        """Retain verified history while permitting a new explicit attempt only after the caller confirms no current binding."""
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        key=role.binding_key();base=self.attempt_folder/(key+'.json');previous=[]
        if base.exists():previous.append((1,base))
        for path in self.attempt_folder.glob(key+'-*.json'):
            suffix=path.stem[len(key)+1:]
            if suffix.isdigit() and int(suffix)>1:previous.append((int(suffix),path))
        # A prior verified success is completed history, but any uncertain attempt still blocks all later clicks.
        for _,path in previous:
            try:state=json.loads(path.read_text(encoding='utf-8')).get('state')
            except (OSError,ValueError,AttributeError):state='uncertain'
            if state!='verified':
                raise ServiceError('该角色已有结果未确认的绑定尝试；请只读核对当前绑定，不重复提交。')
        revision=max((number for number,_ in previous),default=0)+1
        marker=base if revision==1 else self.attempt_folder/(key+'-'+str(revision)+'.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched','attempt':revision,'time':__import__('time').time()},file)
                file.flush();os.fsync(file.fileno())
        except FileExistsError:
            raise ServiceError('另一次绑定尝试已占用本次记录；请只读核对，不重复提交。') from None
        return marker

    def bind(self,account,role):
        """Revalidate the selected own role, submit at most once durably, then read back the binding only."""
        account=self.check_account(account,role.choice)
        if role.owner!=account['profile_id']:raise ServiceError('角色不属于本次账号查询，已停止。')
        check_binding_session(account,self.session)
        fresh=self.roles(account,role.choice,Partition(role.partition,role.partition_name))
        if not any(candidate.identity()==role.identity() for candidate in fresh):
            raise ServiceError('角色资料已变化，请重新选择并确认，未提交绑定。')
        current,restricted=self.current_binding(account)
        if current and self.matches(current,role):
            if restricted:
                self.confirm_native_role(account,role)
                current,restricted=self.current_binding(account)
                if not self.matches(current,role):raise ServiceError('补全原生角色确认后当前绑定已变化，请只读核对，不重复提交。')
                if restricted:raise ServiceError('已补全原生角色确认，但礼包绑定仍受限；未再次提交礼包绑定，请核对原生流程。')
                return '已补全原生角色确认，服务器当前绑定不受限：'+role.label+'；未重复礼包绑定或领取。'
            return '服务器已绑定该角色，本次未重复提交。'
        if restricted or current:raise ServiceError('当前已有其他绑定或服务器要求解绑，请在原生APP处理；助手不会自动解绑。')
        check_binding_session(account,self.session,require_allowed=True)
        self.confirm_native_role(account,role)
        marker=self.reserve_binding_attempt(role)
        wire=role.wire();body=p.varint(8)+p.varint(GID)+p.varint(18)+p.varint(len(wire))+wire
        response=self.session.request(BGW+'xyapp.GiftSrv/PassCardBindGameRoleV2',body,request_headers(account))
        (marker.with_suffix('.dpapi')).write_bytes(b'XYBIND1\0'+crypt(response.body))
        self.checked_response(response,'角色绑定')
        current,restricted=self.current_binding(account)
        if not self.matches(current,role):raise ServiceError('绑定请求已返回，但当前绑定尚未核对一致；请只读查询，不要重复提交。')
        if restricted:raise ServiceError('角色已绑定，但服务器仍返回绑定受限；请检查当前绑定，不重复提交。')
        marker.write_text(json.dumps({'state':'verified'}),encoding='utf-8')
        return '绑定成功，已从服务器核对：'+role.label+'；未签到、领奖或兑换。'
