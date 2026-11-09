"""Account-level ordinary G-score signing; no ad completion, exchange or game-role mutation."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
from .gifts import GiftClient
from .secure_store import crypt
from .transport import ServiceError
from . import protocol as p
from .rewards import score_rewards


@dataclass(frozen=True)
class GScoreState:
    """Expose the confirmed page balance, consecutive days and daily signing enum."""
    balance:int
    days:int
    status:int
    gift_id:str
    valid:bool

    @property
    def available(self):
        """Only the observed unsigned state with a complete server configuration permits submission."""
        return self.valid and self.status==0 and self.gift_id.isdecimal() and len(self.gift_id)<=30

    def describe(self):
        """Keep unknown or incomplete page states distinct from already signed."""
        label='今日已签到' if self.valid and self.status==1 else '今日未签到' if self.available else '状态未确认，暂不签到'
        return f'G分 {self.balance}；连续签到 {self.days} 天；{label}'


class GScoreClient(GiftClient):
    """Serialize one ordinary sign attempt per saved account and Beijing day, without retries."""
    def __init__(self,session=None,attempt_folder=None):
        """Create an isolated transport and dedicated persistent daily guard folder."""
        super().__init__(session)
        self.attempt_folder=Path(attempt_folder) if attempt_folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/gscore_attempts'
        self.receipt_path=None

    def query(self,account):
        """Read only the G-score page, with no Hero Kill binding request or sign side effect."""
        data=self.request('xyapi.PageService/GScorePageNew',b'',account['headers'])
        info=p.get(data,1);sign=p.get(data,2)
        valid=isinstance(info,bytes) and isinstance(sign,bytes)
        i=p.parse(info) if isinstance(info,bytes) else []
        g=p.parse(sign) if isinstance(sign,bytes) else []
        days=p.get(g,4,0);balance=p.get(i,1,0)
        valid=valid and isinstance(days,int) and 0<=days<=30 and isinstance(balance,int) and balance>=0
        self.last_state=GScoreState(balance,days,p.get(g,5,0),p.text(p.get(g,9,b'')),valid)
        return self.last_state

    def retain_response(self,path,response):
        """Preserve only the mutation receipt under current-user DPAPI before parsing its result."""
        if path=='xyapi.PageService/GScoreSignWithAd' and self.receipt_path:
            self.receipt_path.write_bytes(b'XYGSCORE1\0'+crypt(response.body))

    def signin(self,account):
        """Fresh-check, skip signed accounts, durably guard one no-ad request, then verify server state."""
        self.reset_result();before=self.query(account)
        if before.valid and before.status==1:
            self.result_status='skipped';return before.describe()+'；已跳过，未提交签到。'
        if not before.available:raise ServiceError(before.describe())
        day=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        self.attempt_folder.mkdir(parents=True,exist_ok=True)
        marker=self.attempt_folder/(account['profile_id']+'-'+day+'.json')
        try:
            with marker.open('x',encoding='utf-8') as file:
                json.dump({'state':'dispatched_do_not_repeat','balance':before.balance,'days':before.days},file)
                file.flush();os.fsync(file.fileno())
        except FileExistsError:raise ServiceError('本账号今日已有G分签到尝试记录；请只读查询，不重复提交。') from None
        self.receipt_path=marker.with_suffix('.response.dpapi')
        # Native field order: tag 1 watchAd=false, tag 2 the current page giftId.
        body=b'\x08\x00'+p.message_string(2,before.gift_id)
        # This endpoint may omit an empty data object. Check the envelope ourselves, never replay it.
        from .auth import BGW
        self.dispatched=True
        response=self.session.request(BGW+'xyapi.PageService/GScoreSignWithAd',body,account['headers'])
        self.retain_response('xyapi.PageService/GScoreSignWithAd',response)
        if response.status!=200:raise ServiceError('G分签到响应异常；结果待确认，不重试。')
        if 'json' in response.headers.get('Content-Type','').lower():
            raise ServiceError('G分签到网关响应待确认；请查询状态，不重试。')
        result=p.parse(response.body)
        ret=p.get(result,1,0)
        if ret!=0:raise ServiceError(f'G分签到服务器返回 {ret}；不重试，请查询状态。')
        after=self.query(account)
        verified=after.valid and after.status==1
        self.result_status='success' if verified else 'uncertain'
        # The receipt's total is this sign's reward; the page balance can also change for unrelated actions.
        self.actual_rewards=score_rewards(p.parse(p.get(result,3,b''))) if verified else ()
        marker.write_text(json.dumps({'state':'confirmed' if verified else 'uncertain',
            'actual_rewards':self.actual_rewards,'before_balance':before.balance,'after_balance':after.balance,'before_days':before.days,'after_days':after.days}),encoding='utf-8')
        earned=f'本次获得 {self.actual_rewards[0][1]} G分；' if self.actual_rewards else '回执奖励数量未解析；'
        if verified:return f'G分普通签到已确认：{earned}{before.balance} → {after.balance}（变化 {after.balance-before.balance:+d}）；连续签到 {before.days} → {after.days} 天。'
        return 'G分签到已提交一次，服务器状态待确认；不会重复提交，请只读查询。'
