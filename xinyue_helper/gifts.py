"""Read binding/sign-in state and submit at most one explicitly confirmed sign-in per attempt."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import hashlib
import base64
import json
import os
from pathlib import Path
from .auth import BGW
from .transport import Session,ServiceError
from . import protocol as p


def role_text(value):
    """Decode base64-encoded role labels used by the native binding model, with a plain-text fallback."""
    text=p.text(value)
    try:return base64.b64decode(text,validate=True).decode('utf-8') if text else ''
    except (ValueError,UnicodeError):return text


@dataclass(frozen=True)
class GiftState:
    """Expose safe role labels and server state, never authentication headers or raw role IDs."""
    days:int
    status:int
    role_key:str
    role_label:str
    binding_restricted:bool
    @property
    def available(self):
        """Allow only the observed native available state with a real unrestricted binding."""
        return self.status==0 and bool(self.role_key) and not self.binding_restricted

    def describe(self):
        """Render server state without inferring success from cumulative sign-in days alone."""
        if self.binding_restricted:return '服务器提示绑定受限，请在心悦APP核对；助手不会解绑或重绑。'
        if not self.role_key:return '未取得英雄杀绑定角色，请先在心悦APP绑定。'
        return f'已签到 {self.days} 天；'+('可签到' if self.status==0 else '今日已签到' if self.status==5 else f'暂不可签到（状态 {self.status}）')


class GiftClient:
    """Each action uses the selected account snapshot and an isolated HTTP session, without a scheduler."""
    def __init__(self,session=None,attempt_folder=None):
        """Initialize transport plus structured receipt metadata without changing public return strings."""
        self.session=session or Session()
        self.dispatched=False;self.result_status='uncertain';self.actual_rewards=();self.reward_description=''
        self.attempt_folder=Path(attempt_folder) if attempt_folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/signin_attempts'

    def request(self,path,body,headers):
        """Perform one bounded request; parse JSON gateway failures separately from protobuf responses."""
        response=self.session.request(BGW+path,body,headers)
        self.retain_response(path,response)
        if response.status!=200:raise ServiceError('心悦HTTP错误：'+str(response.status))
        if 'json' in response.headers.get('Content-Type',''):
            try:ret=json.loads(response.body).get('ret')
            except (ValueError,AttributeError):ret='未知'
            raise ServiceError('心悦网关拒绝：'+str(ret))
        fields=p.parse(response.body);ret=p.get(fields,1,0)
        if ret!=0:
            if ret==10010:raise ServiceError('10010：服务器提示游戏绑定受限，请核对绑定；不会自动重试。')
            raise ServiceError('心悦服务器拒绝，返回码：'+str(ret))
        data=p.get(fields,3)
        if not isinstance(data,bytes):raise ServiceError('服务器未返回完整数据，停止操作')
        return p.parse(data)

    def retain_response(self,path,response):
        """Allow a scoped encrypted receipt sink without exposing raw responses to the UI or logs."""
        return None

    def reset_result(self):
        """Reset per-attempt metadata so reusing a client cannot inherit an earlier dispatch or reward."""
        self.dispatched=False;self.result_status='uncertain';self.actual_rewards=();self.reward_description=''

    def binding(self,account):
        """Read one binding and safe summary; retain its exact role bytes in RAM for scoped native requests."""
        headers=account['headers']
        self._bound_role=b''
        card=self.request('xyapp.GiftSrv/GetPassCardV2',b'',headers)
        self.bound_game_ids=[p.get(p.parse(value),1,0) for tag,wire,value in card if tag==3 and wire==2]
        key='';label='未绑定英雄杀';restricted=bool(p.get(card,6,0))
        for tag,wire,value in card:
            if tag!=3 or wire!=2:continue
            game=p.parse(value)
            if p.get(game,1,0)!=1187:continue
            role=p.get(game,5,b'')
            restricted=restricted or bool(p.get(game,10,0)) or bool(p.get(game,12,0))
            if role:
                self._bound_role=role
                fields=p.parse(role)
                name=role_text(p.get(fields,8,b'')) or account.get('nickname') or '已绑定角色'
                partition=role_text(p.get(fields,6,b''))
                label='英雄杀 / '+name+(' / '+partition if partition else '')
                key=hashlib.sha256(role).hexdigest()
            break
        return key,label,restricted

    def query(self,account):
        """Read the current binding and Hero Kill sign-in state; never refresh bindings or claim gifts."""
        key,label,restricted=self.binding(account)
        headers=account['headers']
        gifts=self.request('xyapp.GiftSrv/GetGamesGifts',p.message_string(1,'signin')+p.varint(16)+p.varint(1187),headers)
        desc=p.parse(p.get(gifts,1,b''))
        if not desc:raise ServiceError('服务器未返回签到状态，不能领取')
        self.last_state=GiftState(p.get(desc,5,0),p.get(desc,6,0),key,label,restricted)
        return self.last_state

    def signin(self,account,expected_role_key):
        """Recheck role/state, durably block duplicate attempts, claim once, then query once to verify."""
        self.reset_result();before=self.query(account)
        if not before.available:
            self.result_status='skipped';return before.describe()
        if before.role_key!=expected_role_key:raise ServiceError('绑定角色已变化，请重新查询并确认')
        day=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        marker=self.attempt_folder/(account['profile_id']+'-'+day+'.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched_do_not_repeat','scene':'signin','date':day},file)
                file.flush();os.fsync(file.fileno())
        except FileExistsError:
            raise ServiceError('本账号今天已有签到尝试记录；请核对状态，不会重复领取') from None
        # The exact header was observed on the successful native day-seven claim, not guessed from gift enums.
        headers={**account['headers'],'T-GIFT-TYPE':'signin'}
        self.dispatched=True
        data=self.request('xyapp.GiftSrv/ReceiveGamesGift',p.message_string(1,'signin'),headers)
        success=p.get(data,3,0);failed=p.get(data,4,0)
        after=self.query(account)
        if success>0 and failed==0 and after.status==5:
            self.result_status='success'
            result=f'签到成功；成功礼包 {success} 个，已签到 {after.days} 天。'
        else:
            result=f'已提交一次：成功 {success}，失败 {failed}；{after.describe()}。不会自动重试。'
        marker.write_text(json.dumps({'state':'confirmed_response','success':success,'failed':failed,'after_status':after.status}),encoding='utf-8')
        self.actual_rewards=tuple((p.text(p.get(p.parse(v),2,b'')),p.get(p.parse(v),4,0)) for t,w,v in data if t==8 and w==2)
        return result
