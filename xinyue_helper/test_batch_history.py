"""Offline end-to-end batch scheduling, persistent history and stop/ambiguity boundaries."""
import tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from .batch import BatchRunner
from .history import HistoryStore,ClaimRecorder
from .gscore import GScoreClient
from .weekly import WeeklyClient
from .bounty import BountyClient
from .test_gscore import PointSession
from .test_weekly import WeekSession
from .test_bounty import TaskSession
from .test_gifts import number,nested,response
from .transport import ServiceError
from . import protocol as p


class BothTasks(TaskSession):
    """Model both free tasks and distinct actual rewards, never reusing candidate rewards as receipts."""
    def __init__(self):
        super().__init__();self.daily_used=0

    def request(self,url,body=None,headers=None,timeout=20):
        """Add a daily task alongside the existing draw fixture and keep their counters independent."""
        if url.endswith('GetGamesGifts'):
            original=super().request(url,body,headers,timeout)
            data=p.parse(p.get(p.parse(original.body),3));games=p.parse(p.get(data,2));game=p.get(games,1)
            daily=(p.message_string(1,'381')+nested(4,p.message_string(1,'每日礼包'))+number(6,self.daily_used)
                   +number(7,1)+number(8,self.daily_used)+number(9,1)+number(14,1))
            return response(nested(2,nested(1,game+nested(7,daily))))
        if url.endswith('ReceiveGift') and p.text(p.get(p.parse(body),3))=='381':
            self.calls.append('ReceiveGift');self.daily_used=1
            return response(number(1,1)+nested(12,p.message_string(2,'酒馆刷新')+number(4,1)))
        return super().request(url,body,headers,timeout)


class BatchHistoryTests(unittest.TestCase):
    def setUp(self):
        """Use real clients over isolated in-memory server fixtures and a temporary SQLite database."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        self.history=HistoryStore(self.folder/'history.sqlite3');self.stop=threading.Event()
        self.accounts={key:{'profile_id':key,'nickname':name,'headers':{'Test-Account':key}} for key,name in [('a'*64,'甲'),('b'*64,'乙')]}
        accounts=self.accounts
        class Store:
            def load(self,key):return accounts[key]
        self.rows=[{'profile_id':k,'nickname':a['nickname']} for k,a in self.accounts.items()]
        self.servers={k:{'gscore':PointSession(),'weekly':WeekSession(),'bounty':BothTasks()} for k in accounts}
        self.after_mutation=None;self.reject_query=None;outer=self
        class Mux:
            def __init__(self,kind):self.kind=kind
            def request(self,url,body=None,headers=None,timeout=20):
                key=headers['Test-Account']
                if outer.reject_query==(key,self.kind) and not any(s in url for s in ['Receive','SignWithAd']):raise ServiceError('模拟查询失败')
                result=outer.servers[key][self.kind].request(url,body,headers,timeout)
                if any(url.endswith(x) for x in ['ReceiveGift','ReceiveGamesGift','GScoreSignWithAd']) and outer.after_mutation:outer.after_mutation()
                return result
        factories={kind:(lambda kind=kind,cls=cls:cls(Mux(kind),self.folder/kind)) for kind,cls in [('gscore',GScoreClient),('weekly',WeeklyClient),('bounty',BountyClient)]}
        self.runner=BatchRunner(Store(),self.history,factories)

    def mutations(self):
        """Count only mutating calls across every fake account/service."""
        return sum(sum(c in ['ReceiveGift','ReceiveGamesGift','GScoreSignWithAd'] for c in s.calls) for services in self.servers.values() for s in services.values())

    def test_two_accounts_four_actions_then_skip_all_on_next_run(self):
        """Preflight cannot claim; confirmed execution is once per item and a second batch only records skips."""
        plan=self.runner.prepare(self.rows,self.stop);self.assertEqual(len(plan),8);self.assertEqual(self.mutations(),0)
        totals=self.runner.execute(plan,self.stop);self.assertEqual(totals['success'],8);self.assertEqual(self.mutations(),8)
        rows=self.history.list();self.assertEqual(len(rows),8)
        draw=next(r for r in rows if r['action']=='赏金抽奖礼包');self.assertEqual(draw['rewards'],'实际服务器奖品 ×3');self.assertNotIn('候选',draw['rewards'])
        totals=self.runner.execute(self.runner.prepare(self.rows,self.stop),self.stop)
        self.assertEqual(totals['skipped'],8);self.assertEqual(self.mutations(),8);self.assertEqual(len(self.history.list()),16)

    def test_uncertain_account_stops_but_other_account_continues(self):
        """A timed-out sign blocks its own remaining three steps without aborting the next account."""
        self.servers['a'*64]['gscore'].fail=True
        totals=self.runner.execute(self.runner.prepare(self.rows,self.stop),self.stop)
        self.assertEqual(totals['uncertain'],1);self.assertEqual(totals['skipped'],3);self.assertEqual(totals['success'],4)
        self.assertEqual(self.mutations(),5)

    def test_stop_during_request_keeps_its_verification_and_skips_future_dispatch(self):
        """Cancellation during a request must still commit its confirmed result before stopping."""
        plan=self.runner.prepare(self.rows,self.stop);self.after_mutation=self.stop.set
        totals=self.runner.execute(plan,self.stop)
        self.assertEqual(totals['success'],1);self.assertEqual(totals['cancelled'],1)
        self.assertEqual(self.mutations(),1);self.assertEqual(self.history.list()[0]['status'],'success')

    def test_query_failure_skips_only_that_item(self):
        """A read timeout makes one failed plan entry, with no fabricated eligibility or whole-batch abort."""
        self.reject_query=('a'*64,'gscore')
        plan=self.runner.prepare(self.rows,self.stop);self.assertEqual(plan[0].status,'failed')
        totals=self.runner.execute(plan,self.stop);self.assertEqual(totals['failed'],1);self.assertEqual(totals['success'],7)

    def test_preflight_role_or_cost_changes_cannot_bypass_client_checks(self):
        """Confirmed plan values are still checked by the original mutation clients immediately before dispatch."""
        plan=self.runner.prepare(self.rows,self.stop);self.servers['a'*64]['weekly'].role=b'new-role';self.servers['b'*64]['bounty'].cost=10
        totals=self.runner.execute(plan,self.stop)
        self.assertGreaterEqual(totals['failed'],2)
        self.assertEqual(self.servers['a'*64]['weekly'].calls.count('ReceiveGift'),0)
        self.assertEqual(self.servers['b'*64]['bounty'].calls.count('ReceiveGift'),1)  # daily only, paid draw blocked

    def test_batch_weekly_multi_game_and_already_claimed_after_preflight(self):
        """Batch uses the same targeted client and skips a claim completed after its preview."""
        first=self.servers['a'*64]['weekly'];second=self.servers['b'*64]['weekly']
        first.multi_game=True;second.multi_game=True
        plan=self.runner.prepare(self.rows,self.stop)
        second.used=1;second.gift_status=1
        totals=self.runner.execute(plan,self.stop)
        self.assertEqual(totals['success'],7);self.assertEqual(totals['skipped'],1)
        self.assertEqual(len(first.claim_bodies),1);self.assertEqual(second.claim_bodies,[])
        self.assertEqual(first.peace_used,0);self.assertEqual(second.peace_used,0)

    def test_batch_uncertain_weekly_stops_account_remaining_claims(self):
        """No counter confirmation after a weekly mutation blocks subsequent rewards for that account."""
        server=self.servers['a'*64]['weekly'];server.multi_game=True;server.advance=False
        totals=self.runner.execute(self.runner.prepare(self.rows,self.stop),self.stop)
        self.assertEqual(totals['uncertain'],1);self.assertEqual(totals['skipped'],2)
        self.assertEqual(totals['success'],5);self.assertEqual(len(server.claim_bodies),1)
        self.assertEqual(self.servers['a'*64]['bounty'].calls.count('ReceiveGift'),0)

    def test_pending_history_persists_and_never_copies_extra_account_fields(self):
        """Interrupted rows survive restart, while private dictionaries never enter the history schema."""
        self.history.begin('a'*64,'甲','角色','测试领取')
        reopened=HistoryStore(self.history.path);row=reopened.list()[0]
        self.assertEqual(row['status'],'uncertain');self.assertIn('需核对',row['detail'])
        self.assertNotIn('headers',row);self.assertNotIn('Token',row)

    def test_history_write_failure_prevents_request_and_postwrite_failure_never_replays(self):
        """A prewrite failure blocks mutation; a postwrite failure keeps the single dispatched operation."""
        class Broken:
            def begin(self,*args):raise OSError('disk')
        called=[];client=SimpleNamespace(dispatched=False,result_status='success',actual_rewards=())
        with self.assertRaises(OSError):ClaimRecorder(Broken()).execute(self.accounts['a'*64],'角色','测试',client,lambda:called.append(1))
        self.assertEqual(called,[])
        class PostBroken:
            def begin(self,*args):return 1
            def finish(self,*args):raise OSError('disk')
        with self.assertRaises(ServiceError):ClaimRecorder(PostBroken()).execute(self.accounts['a'*64],'角色','测试',client,lambda:called.append(1))
        self.assertEqual(called,[1])

    def test_unknown_draw_reward_is_never_replaced_by_candidate_pool(self):
        """A confirmed draw with an undecoded prize gets an explicit unknown-reward history entry."""
        client=SimpleNamespace(dispatched=True,result_status='success',actual_rewards=())
        ClaimRecorder(self.history).execute(self.accounts['a'*64],'角色','赏金抽奖礼包',client,lambda:'已确认领取')
        self.assertEqual(self.history.list()[0]['rewards'],'实际奖品待核对')


if __name__=='__main__':unittest.main()
