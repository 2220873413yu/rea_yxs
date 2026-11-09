"""An explicitly confirmed, sequential batch of four free actions; no scheduler or exchange import."""
from dataclasses import dataclass
from collections import Counter
from .gscore import GScoreClient
from .weekly import WeeklyClient
from .bounty import BountyClient
from .history import ClaimRecorder
from .transport import ServiceError


@dataclass(frozen=True)
class Step:
    """A public preflight snapshot; credentials are loaded only when its operation is executed."""
    account_key:str
    account_name:str
    kind:str
    action:str
    role_label:str
    state:object=None
    gift:object=None
    status:str='skipped'
    reason:str=''


class BatchRunner:
    """Preflight separately from execution so one confirmation covers the exact account/role plan."""
    def __init__(self,store,history,factories=None):
        """Inject clients and storage for fully offline orchestration and cancellation tests."""
        self.store=store;self.history=history;self.recorder=ClaimRecorder(history)
        self.factories=factories or {'gscore':GScoreClient,'weekly':WeeklyClient,'bounty':BountyClient}

    def prepare(self,rows,stop,on_state=lambda *args:None,on_progress=lambda value:None):
        """Read each account's three pages, reuse the bounty page for both tasks, and never claim here."""
        plan=[]
        for index,row in enumerate(rows):
            if stop.is_set():break
            key=row['profile_id'];name=row.get('nickname') or 'QQ账号'
            on_progress(f'预查账号 {index+1}/{len(rows)}：{name}')
            for kind in ('gscore','weekly','bounty'):
                if stop.is_set():break
                actions=['G分签到'] if kind=='gscore' else ['周礼包'] if kind=='weekly' else ['赏金每日礼包','赏金抽奖礼包']
                try:
                    state=self.factories[kind]().query(self.store.load(key));on_state(kind,key,state)
                    for action in actions:
                        gift=None
                        if kind=='gscore':ready=state.available;reason=state.describe();role='心悦账号G分'
                        elif kind=='weekly':ready=state.available;reason=state.describe();role=state.role_label
                        else:
                            title='每日礼包' if action=='赏金每日礼包' else '抽奖礼包'
                            matches=[t for t in state.tasks if t.title==title];gift=matches[0] if len(matches)==1 else None
                            ready=bool(gift and gift.available and state.role_key and not state.binding_restricted)
                            reason=gift.describe() if gift else '未找到唯一任务配置'
                            if state.binding_restricted or not state.role_key:reason='绑定未确认或受限'
                            role=state.role_label
                        plan.append(Step(key,name,kind,action,role,state,gift,'ready' if ready else 'skipped',reason))
                except Exception as error:
                    reason=str(error) if isinstance(error,ServiceError) else '查询未完成，请重新扫码或手动核对'
                    plan.extend(Step(key,name,kind,action,'',status='failed',reason=reason) for action in actions)
        return tuple(plan)

    @staticmethod
    def summary(plan):
        """Show every account, recipient and eligible action without exposing credential or role identifiers."""
        lines=[]
        for step in plan:
            lines.append(f'{step.account_name} / {step.role_label or "角色未确认"}：{step.action} — '+('可领取' if step.status=='ready' else step.reason))
        return '\n'.join(lines)

    def execute(self,plan,stop,on_state=lambda *args:None,on_progress=lambda value:None):
        """Run serially with fresh client checks; ambiguous mutation stops only that account, with no retry."""
        totals=Counter();blocked={}
        for index,step in enumerate(plan):
            if stop.is_set():break
            on_progress(f'处理 {index+1}/{len(plan)}：{step.account_name} / {step.action}')
            if step.status!='ready' or step.account_key in blocked:
                status=step.status if step.status!='ready' else 'skipped'
                reason=step.reason if step.account_key not in blocked else blocked[step.account_key]
                key=self.history.begin(step.account_key,step.account_name,step.role_label,step.action)
                self.history.finish(key,status,detail=reason);totals[status]+=1;continue
            try:account=self.store.load(step.account_key);client=self.factories[step.kind]()
            except Exception:
                key=self.history.begin(step.account_key,step.account_name,step.role_label,step.action)
                self.history.finish(key,'failed',detail='本地账号不可用，请重新扫码；未提交领取。')
                totals['failed']+=1;blocked[step.account_key]='本地账号不可用，停止本账号后续领取；请重新扫码';continue
            def operation():
                """Dispatch only the four approved free actions using their original fresh-preflight clients."""
                if step.kind=='gscore':return client.signin(account)
                if step.kind=='weekly':return client.receive(account,step.state.role_key,step.state.gift_id)
                if step.kind=='bounty':return client.receive(account,step.gift.title,step.state.role_key,step.gift.gift_id)
                raise ServiceError('未开放的批量项目')
            status,message=self.recorder.execute(account,step.role_label,step.action,client,operation)
            totals[status]+=1
            if hasattr(client,'last_state'):on_state(step.kind,step.account_key,client.last_state)
            on_progress(step.account_name+' / '+step.action+'：'+message)
            if status=='uncertain':blocked[step.account_key]='本账号上一步结果待确认，停止后续领取'
        totals['cancelled']=int(stop.is_set())
        return dict(totals)
