"""Two manually confirmed G-score exchanges, isolated from free gifts and all automatic actions."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import hashlib,json,os
from pathlib import Path
from .gifts import GiftClient
from .secure_store import crypt
from .transport import ServiceError
from . import protocol as p

ALLOWED={'粮木矿礼盒':2,'元神宝盒':1}


@dataclass(frozen=True)
class ExchangeGift:
    """Keep the exact reward and cost snapshot that the user must confirm before spending."""
    gift_id:str
    title:str
    quantity:int
    cost:int
    status:int
    used:int
    total:int
    cycle:int
    kind:int
    receive_type:int
    module:int

    @property
    def available(self):
        """Accept only the two observed configurations and a remaining single daily/weekly allowance."""
        return (self.title in ALLOWED and self.cycle==ALLOWED[self.title] and self.kind==11
                and self.receive_type==0 and self.module==1 and self.status==0 and self.used==0
                and self.total==1 and self.cost>0 and self.quantity>0 and self.gift_id.isdecimal())

    @property
    def confirmation(self):
        """Bind consent to every reward, cost, identity and quota value, excluding only display rank."""
        return (self.gift_id,self.title,self.quantity,self.cost,self.cycle,self.total,self.used,
                self.kind,self.receive_type,self.module)

    def describe(self):
        """Distinguish consumed quota from unknown server states rather than inferring eligibility by price."""
        if self.status==1 or (self.total>0 and self.used>=self.total):return '本周期已兑换'
        return '可兑换' if self.available else f'暂不可兑换（状态 {self.status}）'


@dataclass(frozen=True)
class ExchangeState:
    """Expose account-bound public exchange data; raw role bytes remain only on the client instance."""
    role_key:str
    role_label:str
    restricted:bool
    balance:int
    gifts:tuple

    def eligible(self,gift):
        """Require valid current binding, exact recognized gift configuration and sufficient live G-score."""
        return bool(self.role_key) and not self.restricted and gift.available and self.balance>=gift.cost


class ExchangeClient(GiftClient):
    """Read live prices and dispatch one user-confirmed score-scene mutation with the fresh role."""
    def __init__(self,session=None,attempt_folder=None):
        """Keep exchange guards separate from sign-in, free bounty and weekly gift receipts."""
        super().__init__(session)
        self.attempt_folder=Path(attempt_folder) if attempt_folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/exchange_attempts'
        self.receipt_path=None

    def query(self,account):
        """Read the bound role and G-score page once, retaining only the two requested Hero Kill rewards."""
        key,label,restricted=self.binding(account)
        data=self.request('xyapi.PageService/GScorePageNew',b'',account['headers'])
        info=p.get(data,1)
        if not isinstance(info,bytes):raise ServiceError('未取得G分余额，停止兑换')
        balance=p.get(p.parse(info),1,0);gifts=[]
        for tag,wire,raw in p.parse(p.get(data,4,b'')):
            if tag!=3 or wire!=2:continue
            game=p.parse(raw)
            if p.get(game,3)!=1187:continue
            for number,kind,value in game:
                if number!=7 or kind!=2:continue
                gift=p.parse(value);items=[p.parse(v) for t,w,v in gift if t==5 and w==2]
                if len(items)!=1:continue
                item=items[0];title=p.text(p.get(item,2,b''))
                if title not in ALLOWED:continue
                gifts.append(ExchangeGift(p.text(p.get(gift,1,b'')),title,p.get(item,4,0),
                    max(p.get(gift,10,0),p.get(gift,13,0)),p.get(gift,6,0),p.get(gift,8,0),p.get(gift,9,0),
                    p.get(gift,7,0),p.get(gift,2,0),p.get(gift,3,0),p.get(gift,14,0)))
        # Duplicate definitions are ambiguous: never let a UI row choose arbitrarily between them.
        if len({g.title for g in gifts})!=len(gifts):raise ServiceError('兑换礼包配置重复，停止兑换')
        self.last_state=ExchangeState(key,label,restricted,balance,tuple(gifts))
        return self.last_state

    def retain_response(self,path,response):
        """Encrypt the received mutation body before parsing so later diagnosis never requires another spend."""
        if path=='xyapp.GiftSrv/ReceiveGift' and self.receipt_path:
            self.receipt_path.write_bytes(b'XYEXCH1\0'+crypt(response.body))

    def receive(self,account,expected_role_key,expected_gift):
        """Fresh-check consent, durably reserve one period attempt, spend once, and verify quota plus balance."""
        self.reset_result();before=self.query(account)
        if before.role_key!=expected_role_key:raise ServiceError('兑换角色已变化，请重新查询并确认')
        gift=next((g for g in before.gifts if g.title==expected_gift.title),None)
        if not gift or gift.confirmation!=expected_gift.confirmation:
            raise ServiceError('兑换价格、奖励或次数配置已变化，请重新查询并确认')
        if not before.eligible(gift):raise ServiceError('当前不可兑换：余额不足、绑定受限或'+gift.describe())
        role=self._bound_role
        if not role or hashlib.sha256(role).hexdigest()!=before.role_key:
            raise ServiceError('兑换角色数据未确认，停止操作')
        now=datetime.now(timezone(timedelta(hours=8)));year,week,_=now.isocalendar()
        period=now.strftime('%Y-%m-%d') if gift.cycle==1 else f'{year}-W{week:02d}'
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        name_hash=hashlib.sha256(gift.title.encode('utf-8')).hexdigest()[:16]
        marker=self.attempt_folder/(account['profile_id']+'-'+name_hash+'-'+period+'.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched_do_not_repeat','gift_id':gift.gift_id,'cost':gift.cost,
                           'balance':before.balance,'used':gift.used},file)
                file.flush();os.fsync(file.fileno())
        except FileExistsError:raise ServiceError('本礼包本周期已有兑换尝试记录，请只读查询，不重复提交') from None
        # Native capture: gid=1187, scene=score, giftId and exact amp2.Role. No num/baseUin/t-gift-type.
        body=p.varint(8)+p.varint(1187)+p.message_string(2,'score')+p.message_string(3,gift.gift_id)
        body+=p.varint(34)+p.varint(len(role))+role
        headers={k:v for k,v in account['headers'].items() if k.lower()!='t-gift-type'}
        self.receipt_path=marker.with_suffix('.response.dpapi')
        self.dispatched=True
        result=self.request('xyapp.GiftSrv/ReceiveGift',body,headers)
        wrapped=p.get(result,1)
        if isinstance(wrapped,bytes):result=p.parse(wrapped)
        result_ret=p.get(result,8,0)
        if not isinstance(result_ret,int) or result_ret!=0:
            raise ServiceError('兑换响应未确认成功；请只读查询，不重复提交')
        after=self.query(account)
        current=next((g for g in after.gifts if g.gift_id==gift.gift_id),None)
        delta=before.balance-after.balance
        verified=(after.role_key==before.role_key and current is not None and current.used==gift.used+1
                  and current.status==1 and delta==gift.cost)
        self.result_status='success' if verified else 'uncertain'
        self.actual_rewards=((gift.title,gift.quantity),) if verified else ()
        marker.write_text(json.dumps({'state':'confirmed' if verified else 'uncertain',
            'before_balance':before.balance,'after_balance':after.balance,'deducted':delta,
            'before_used':gift.used,'after_used':current.used if current else None}),encoding='utf-8')
        if not verified:return '兑换已提交一次，扣分或次数尚未核对一致；请只读查询，不重复提交。'
        return (f'{gift.title} ×{gift.quantity} 兑换已确认：扣除 {delta} G分；余额 {before.balance} → {after.balance}；'
                f'次数 {gift.used}/{gift.total} → {current.used}/{current.total}。')
