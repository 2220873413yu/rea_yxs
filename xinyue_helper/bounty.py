"""Two explicit zero-cost bounty actions, isolated from seven-day sign-in and other activities."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
from .gifts import GiftClient
from .context import request_headers
from .transport import ServiceError
from .secure_store import crypt
from .rewards import item_rewards
from . import protocol as p

ALLOWED_TASKS={'每日礼包':0,'抽奖礼包':1}


@dataclass(frozen=True)
class Task:
    """Display only the two identified daily tasks; retained costs and counters gate every mutation."""
    gift_id:str
    title:str
    kind:int
    status:int
    used:int
    total:int
    cost:int
    cycle:int
    receive_type:int
    module:int
    rewards:tuple
    @property
    def available(self):
        """Require a recognized zero-cost daily task, known available enum, and explicit remaining count."""
        return (self.title in ALLOWED_TASKS and self.kind==ALLOWED_TASKS[self.title]
                and self.status==0 and self.cycle==1 and self.receive_type==0 and self.module==1
                and self.cost==0 and self.total>0 and 0<=self.used<self.total)

    def describe(self):
        """Explain the gate without treating every nonzero enum as already received."""
        if self.cost:return f'需要 {self.cost} 分，禁止自动消耗'
        if self.status==1 or (self.total>0 and self.used>=self.total):return '今日已领取'
        return '可领取' if self.available else f'暂不可操作（状态 {self.status}）'


@dataclass(frozen=True)
class BountyState:
    """Keep safe role identity and task definitions together as one account-bound read snapshot."""
    role_key:str
    role_label:str
    binding_restricted:bool
    tasks:tuple


class BountyClient(GiftClient):
    """Reuse only transport and binding reads; bounty claims have their own schema, enums and guard keys."""
    def __init__(self,session=None,attempt_folder=None):
        super().__init__(session)
        self.attempt_folder=Path(attempt_folder) if attempt_folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/bounty_attempts'
        self.receipt_path=None

    def retain_response(self,path,response):
        """Encrypt the mutation receipt before decoding so future parser fixes never require repeat draws."""
        if path=='xyapp.GiftSrv/ReceiveGift' and self.receipt_path:
            self.receipt_path.write_bytes(b'XYBOUNTY1\0'+crypt(response.body))

    def query(self,account):
        """Read role and scene=task once; ignore recharge, membership and unrelated activity gifts."""
        key,label,restricted=self.binding(account)
        data=self.request('xyapp.GiftSrv/GetGamesGifts',p.message_string(1,'task')+p.varint(16)+p.varint(1187),request_headers(account))
        games=p.parse(p.get(data,2,b''));tasks=[]
        for tag,wire,value in games:
            if tag!=1 or wire!=2:continue
            game=p.parse(value)
            if p.get(game,3,0)!=1187:continue
            for number,kind,raw in game:
                if number!=7 or kind!=2:continue
                gift=p.parse(raw);desc=p.parse(p.get(gift,4,b''));title=p.text(p.get(desc,1,b''))
                if title not in ALLOWED_TASKS:continue
                rewards=[]
                for field,form,item in gift:
                    if field==5 and form==2:
                        details=p.parse(item);rewards.append((p.text(p.get(details,2,b'')),p.get(details,4,0)))
                cost=max(p.get(gift,10,0),p.get(gift,13,0))
                tasks.append(Task(p.text(p.get(gift,1,b'')),title,p.get(gift,2,0),p.get(gift,6,0),
                    p.get(gift,8,0),p.get(gift,9,0),cost,p.get(gift,7,0),p.get(gift,3,0),p.get(gift,14,0),tuple(rewards)))
        self.last_state=BountyState(key,label,restricted,tuple(tasks))
        return self.last_state

    def receive(self,account,title,expected_role_key,expected_gift_id):
        """Preflight current free task and role, dispatch one ReceiveGift, and verify counters without replay."""
        self.reset_result()
        if title not in ALLOWED_TASKS:raise ServiceError('未开放此任务，停止操作')
        before=self.query(account)
        if before.binding_restricted or not before.role_key:raise ServiceError('未取得有效绑定，不能领取；不会修改绑定')
        if before.role_key!=expected_role_key:raise ServiceError('绑定角色已变化，请重新查询并确认')
        matches=[t for t in before.tasks if t.title==title]
        if len(matches)!=1:raise ServiceError('任务不存在或存在重复配置，请重新查询')
        task=matches[0]
        if task.gift_id!=expected_gift_id:raise ServiceError('礼包配置已变化，请重新查询后确认')
        if not task.available:raise ServiceError(title+'：'+task.describe())
        day=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        marker=self.attempt_folder/(account['profile_id']+'-'+hashlib.sha256(task.gift_id.encode()).hexdigest()[:16]+'-'+day+'.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched_do_not_repeat','gift_id':task.gift_id,'title':title,'date':day},file)
                file.flush();os.fsync(file.fileno())
        except FileExistsError:raise ServiceError('此任务今天已有操作记录，禁止重复提交；请只读查询核对') from None
        # Native daily claim uses ReceiveGift, no t-gift-type, and a 14-byte payload.
        # gid(3 bytes)+scene=task(6)+giftId=381(5) matches that payload length. Role is resolved from the existing binding.
        body=p.varint(8)+p.varint(1187)+p.message_string(2,'task')+p.message_string(3,task.gift_id)
        headers={k:v for k,v in request_headers(account).items() if k.lower()!='t-gift-type'}
        self.receipt_path=marker.with_suffix('.response.dpapi')
        self.dispatched=True
        result=self.request('xyapp.GiftSrv/ReceiveGift',body,headers)
        # Generic responses can wrap ReceiveGiftData in a per-game message.
        wrapped=p.get(result,1)
        if isinstance(wrapped,bytes):
            try:inner=p.parse(wrapped)
            except p.ProtocolError:inner=[]
            if any(tag in (5,6,7,8,12) for tag,wire,value in inner):result=inner
        result_ret=p.get(result,8,0)
        if not isinstance(result_ret,int):raise ServiceError('任务结果结构待核对；已停止，不重复提交')
        if result_ret!=0:raise ServiceError('任务返回错误：'+str(result_ret)+'；已停止，不重复提交')
        rewards=item_rewards(result)
        after=self.query(account)
        current=next((t for t in after.tasks if t.gift_id==task.gift_id),None)
        verified=current is not None and (current.used>task.used or current.status==1)
        self.result_status='success' if verified else 'uncertain';self.actual_rewards=tuple(rewards)
        reward_text='、'.join(f'{name} ×{count}' for name,count in rewards)
        if not reward_text and verified and task.kind==0:
            fixed=tuple((name,count) for name,count in task.rewards if name and isinstance(count,int) and count>0)
            if fixed:
                self.reward_description='、'.join(f'{name} ×{count}' for name,count in fixed)+'（礼包配置；回执仅确认成功）'
                reward_text=self.reward_description
        reward_text=reward_text or '服务器未返回可识别奖品，未使用候选奖品冒充结果'
        message=(title+'成功：' if verified else title+'已提交一次，状态待核对：')+reward_text+'。不会自动重试。'
        marker.write_text(json.dumps({'state':'confirmed_response' if verified else 'uncertain','gift_id':task.gift_id,
            'title':title,'configuration_rewards':task.rewards,'reward_description':self.reward_description,
            'before_used':task.used,'after_used':current.used if current else None,
            'after_status':current.status if current else None,'actual_rewards':rewards},ensure_ascii=False),encoding='utf-8')
        return message
