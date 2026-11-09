"""Offline guards for free daily/lottery gifts; no tests contact the real service."""
import tempfile
import unittest
from .auth import Credentials
from .bounty import BountyClient
from .transport import ServiceError
from .test_gifts import GiftSession,number,nested,response
from . import protocol as p


class TaskSession(GiftSession):
    """Emulate current bounty costs, config and server-determined rewards without a local draw algorithm."""
    def __init__(self):
        super().__init__();self.used=0;self.cost=0;self.gift_id='4156';self.task_status=0;self.fail=False;self.wrapped=False

    def request(self,url,body=None,headers=None,timeout=20):
        """Supply task messages while reusing the real binding fixture from the existing sign-in tests."""
        if url.endswith('GetPassCardV2'):return super().request(url,body,headers,timeout)
        self.calls.append(url.rsplit('/',1)[-1])
        if url.endswith('GetGamesGifts'):
            assert body==p.message_string(1,'task')+number(2,1187)
            desc=p.message_string(1,'抽奖礼包')
            item=p.message_string(2,'候选奖品')+number(4,99)
            gift=(p.message_string(1,self.gift_id)+number(2,1)+nested(4,desc)+nested(5,item)
                +number(6,self.task_status)+number(7,1)+number(8,self.used)+number(9,1)+number(10,self.cost)+number(14,1))
            return response(nested(2,nested(1,number(3,1187)+nested(7,gift))))
        if url.endswith('ReceiveGift'):
            assert body==number(1,1187)+p.message_string(2,'task')+p.message_string(3,self.gift_id)
            assert not any(k.lower()=='t-gift-type' for k in headers)
            if self.fail:raise ServiceError('模拟结果不明')
            self.used=1;self.task_status=1
            data=number(1,1)+number(5,1)+number(6,1)+nested(12,p.message_string(2,'实际服务器奖品')+number(4,3))
            return response(nested(1,data) if self.wrapped else data)
        raise AssertionError('Unexpected endpoint')


class BountyTests(unittest.TestCase):
    def setUp(self):
        """Give every test its own fake identity, fixtures and durable attempt storage."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=TaskSession();self.client=BountyClient(self.session,self.temp.name)
        c=Credentials('qq','fake-token','fake-openid')
        self.account={'profile_id':'b'*64,'nickname':'测试','headers':c.headers()}

    def test_one_draw_uses_server_reward_not_candidates(self):
        """Verify the task-specific protocol and one mutation, then use actual response rewards only."""
        state=self.client.query(self.account)
        result=self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.assertIn('实际服务器奖品 ×3',result)
        self.assertNotIn('候选奖品',result)
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)
        with self.assertRaises(ServiceError):self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)

    def test_cost_change_before_dispatch_blocks_draw(self):
        """A zero-cost UI snapshot cannot authorize a later nonzero-cost draw."""
        state=self.client.query(self.account);self.session.cost=10
        with self.assertRaises(ServiceError):self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_wrapped_receipt_and_encrypted_preservation(self):
        """Parse the generic per-game envelope and retain only encrypted raw receipt bytes for later diagnostics."""
        self.session.wrapped=True;state=self.client.query(self.account)
        result=self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.assertIn('实际服务器奖品 ×3',result)
        self.assertTrue(self.client.receipt_path.exists())
        self.assertNotIn('实际服务器奖品'.encode(),self.client.receipt_path.read_bytes())

    def test_changed_role_or_task_id_blocks_claim(self):
        """Recheck both the bound hero role and the server-provided gift configuration before any mutation."""
        state=self.client.query(self.account);self.session.role=b'changed-role'
        with self.assertRaises(ServiceError):self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.session.role=b'role-A';self.session.gift_id='new-gift'
        with self.assertRaises(ServiceError):self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_unknown_status_and_non_daily_task_are_blocked(self):
        """Unknown states and unrelated recharge gifts never become eligible via a shared generic endpoint."""
        state=self.client.query(self.account);self.session.task_status=42
        with self.assertRaises(ServiceError):self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        with self.assertRaises(ServiceError):self.client.receive(self.account,'充值礼包',state.role_key,'4156')
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_timeout_guard_survives_new_client(self):
        """An uncertain draw stays blocked after restart, even if a stale read still says available."""
        state=self.client.query(self.account);self.session.fail=True
        with self.assertRaises(ServiceError):self.client.receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.session.fail=False
        with self.assertRaises(ServiceError):BountyClient(self.session,self.temp.name).receive(self.account,'抽奖礼包',state.role_key,'4156')
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)


if __name__=='__main__':unittest.main()
