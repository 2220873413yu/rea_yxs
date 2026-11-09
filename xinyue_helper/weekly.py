"""Weekly gifts are gated by live server eligibility, never by a local Monday timer."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
from .gifts import GiftClient
from .context import request_headers
from .secure_store import crypt
from .rewards import item_rewards
from .transport import ServiceError
from . import protocol as p


@dataclass(frozen=True)
class WeeklyState:
    """One safe snapshot of a unique ordinary Hero Kill weekly gift and its server eligibility."""
    role_key:str
    role_label:str
    restricted:bool
    gift_id:str
    title:str
    status:int
    summary_status:int
    used:int
    total:int
    cost:int
    next_receive:int
    button:str
    normal_config:bool
    rewards:tuple
    rule:str

    @property
    def available(self):
        """Require every observed server gate; unfamiliar activation/upgrade states never authorize a claim."""
        return (bool(self.role_key) and not self.restricted and bool(self.gift_id) and self.normal_config
                and self.status==0 and self.summary_status==0 and self.button=='领取'
                and self.total>0 and 0<=self.used<self.total and self.cost==0 and self.next_receive==0)

    def describe(self):
        """Explain why a claim is blocked without inventing meanings for unknown activation enums."""
        if not self.role_key:return '未取得有效英雄杀角色，不能领取'
        if self.restricted:return '服务器提示绑定受限，不能领取；不会修改绑定'
        if not self.gift_id or not self.normal_config:return '未确认普通周礼包配置，不能领取'
        if self.cost:return f'需要消耗 {self.cost} 分，停止领取'
        if self.total>0 and self.used>=self.total:return '本周期次数已用完'
        if self.available:return '服务器确认可领取'
        if self.next_receive:return f'服务器返回领取时间限制：{self.next_receive}；暂不领取'
        if self.button and self.button!='领取':return f'服务器提示：{self.button}；不会自动激活或升级'
        return f'资格未确认（礼包状态 {self.status}，汇总状态 {self.summary_status}），暂不领取'


class WeeklyClient(GiftClient):
    """Read eligibility and dispatch a single explicitly confirmed zero-cost weekly claim."""
    def __init__(self,session=None,attempt_folder=None):
        super().__init__(session)
        self.attempt_folder=Path(attempt_folder) if attempt_folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/weekly_attempts'
        self.receipt_path=None

    def retain_response(self,path,response):
        """Retain only an encrypted weekly mutation receipt so diagnostics never require another claim."""
        if path=='xyapp.GiftSrv/ReceiveGift' and self.receipt_path:
            self.receipt_path.write_bytes(b'XYWEEK1\0'+crypt(response.body))

    def query(self,account):
        """Read the bound role and weekGift scene once; missing or ambiguous gift data fail closed."""
        key,label,restricted=self.binding(account)
        data=self.request('xyapp.GiftSrv/GetGamesGifts',p.message_string(1,'weekGift')+p.varint(16)+p.varint(1187),request_headers(account))
        desc=p.parse(p.get(data,1,b''));matches=[]
        for tag,wire,raw in p.parse(p.get(data,2,b'')):
            if tag!=1 or wire!=2:continue
            game=p.parse(raw)
            if p.get(game,3,0)!=1187:continue
            for number,kind,value in game:
                if number==7 and kind==2:matches.append(p.parse(value))
        g=matches[0] if len(matches)==1 else []
        gd=p.parse(p.get(g,4,b''));rewards=[]
        for tag,wire,value in g:
            if tag==5 and wire==2:
                item=p.parse(value);rewards.append((p.text(p.get(item,2,b'')),p.get(item,4,0)))
        title=p.text(p.get(gd,1,b''));summary=p.text(p.get(desc,1,b''))
        normal=(len(matches)==1 and summary=='超级周礼包' and title=='每周礼包'
                and p.get(g,2,0)==0 and p.get(g,3,0)==0 and p.get(g,7,0)==2 and p.get(g,14,0)==1)
        self.last_state=WeeklyState(key,label,restricted,p.text(p.get(g,1,b'')),title,
            p.get(g,6,0),p.get(desc,6,0),p.get(g,8,0),p.get(g,9,0),
            max(p.get(g,10,0),p.get(g,13,0),p.get(desc,7,0)),p.get(desc,9,0),
            p.text(p.get(gd,7,b'')),normal,tuple(rewards),p.text(p.get(desc,10,b'')))
        return self.last_state

    def receive(self,account,expected_role_key,expected_gift_id):
        """Recheck all eligibility and identity gates, persist the weekly guard, claim once and verify counts."""
        self.reset_result();before=self.query(account)
        if before.role_key!=expected_role_key:raise ServiceError('领取角色已变化，请重新查询并确认')
        if before.gift_id!=expected_gift_id:raise ServiceError('周礼包配置已变化，请重新查询并确认')
        if (before.role_key and not before.restricted and before.normal_config and before.total>0
                and before.used>=before.total):
            self.result_status='skipped'
            return '本周期周礼包已领取，跳过；未提交领取请求。'
        if not before.available:raise ServiceError(before.describe())
        role=self._bound_role
        if not role:raise ServiceError('未取得当前绑定角色，停止领取')
        # Calendar week is only a duplicate guard. It never grants server eligibility on its own.
        now=datetime.now(timezone(timedelta(hours=8)));year,week,_=now.isocalendar()
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        marker=self.attempt_folder/(account['profile_id']+f'-{year}-W{week:02d}.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched_do_not_repeat','gid':1187,'gift_id':before.gift_id,
                           'scene':'weekGift','endpoint':'ReceiveGift'},file)
                file.flush();os.fsync(file.fileno())
        except FileExistsError:raise ServiceError('本账号本周已有周礼包尝试记录，不重复提交；请只读查询核对') from None
        self.receipt_path=marker.with_suffix('.response.dpapi')
        self.dispatched=True
        # Target only this game's live gift and exact bound role; never fall back to the bulk endpoint.
        body=(p.varint(8)+p.varint(1187)+p.message_string(2,'weekGift')
              +p.message_string(3,before.gift_id)+p.varint(34)+p.varint(len(role))+role)
        headers={k:v for k,v in request_headers(account).items() if k.lower()!='t-gift-type'}
        result=self.request('xyapp.GiftSrv/ReceiveGift',body,headers)
        wrapped=p.get(result,1)
        if isinstance(wrapped,bytes):
            try:inner=p.parse(wrapped)
            except p.ProtocolError:inner=[]
            if any(tag in (5,6,7,8,12) for tag,wire,value in inner):result=inner
        result_ret=p.get(result,8,0)
        if not isinstance(result_ret,int):raise ServiceError('周礼包结果结构待核对；不重复提交')
        if result_ret!=0:raise ServiceError('周礼包返回错误：'+str(result_ret)+'；不重复提交')
        rewards=item_rewards(result)
        after=self.query(account)
        verified=(after.role_key==before.role_key and after.gift_id==before.gift_id
                  and after.used>before.used and after.status==1)
        self.result_status='success' if verified else 'uncertain';self.actual_rewards=tuple(rewards)
        reward_text='、'.join(f'{name} ×{count}' for name,count in rewards if name)
        if not reward_text and verified:
            fixed=tuple((name,count) for name,count in before.rewards if name and isinstance(count,int) and count>0)
            if fixed:
                self.reward_description='、'.join(f'{name} ×{count}' for name,count in fixed)+'（礼包配置；回执仅确认成功）'
                reward_text=self.reward_description
        marker.write_text(json.dumps({'state':'confirmed_response' if verified else 'uncertain',
            'gid':1187,'scene':'weekGift','endpoint':'ReceiveGift','gift_id':before.gift_id,
            'before_used':before.used,'after_used':after.used,'after_status':after.status,
            'actual_rewards':rewards,'reward_description':self.reward_description},ensure_ascii=False),encoding='utf-8')
        return (f'英雄杀周礼包领取成功，次数 {after.used}/{after.total}。'+(reward_text+'。' if reward_text else '') if verified
                else '已提交一次英雄杀周礼包请求，结果待核对。')+'不会自动重试。'
