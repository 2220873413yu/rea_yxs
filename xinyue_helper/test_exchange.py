"""Offline spending consent and native-body tests; no real accounts or network requests."""
import tempfile,unittest
from .exchange import ExchangeClient
from .transport import ServiceError
from .test_gifts import GiftSession,number,nested,response
from . import protocol as p


class ExchangeSession(GiftSession):
    """Emulate independent daily and weekly quotas, with controlled balance and response failures."""
    def __init__(self):
        """Initialize the two observed gift definitions and an isolated fake G-score balance."""
        super().__init__();self.balance=500;self.fail=False;self.apply=True;self.deduction=None
        self.defs={
            '粮木矿礼盒':{'id':'1482','qty':10,'cost':90,'cycle':2,'used':0,'status':0,'total':1},
            '元神宝盒':{'id':'1481','qty':5,'cost':150,'cycle':1,'used':0,'status':0,'total':1}}

    def request(self,url,body=None,headers=None,timeout=20):
        """Assert score scene, exact current binding and absence of unrelated optional mutation fields."""
        if url.endswith('GetPassCardV2'):
            value=super().request(url,body,headers,timeout)
            card=p.parse(p.get(p.parse(value.body),3));game=p.parse(p.get(card,3));self.bound_role=p.get(game,5)
            return value
        self.calls.append(url.rsplit('/',1)[-1])
        if url.endswith('GScorePageNew'):
            assert body==b''
            gifts=b''
            for name,d in self.defs.items():
                gift=(p.message_string(1,d['id'])+number(2,11)+nested(5,p.message_string(2,name)+number(4,d['qty']))
                      +number(6,d['status'])+number(7,d['cycle'])+number(8,d['used'])+number(9,d['total'])
                      +number(13,d['cost'])+number(14,1))
                gifts+=nested(7,gift)
            return response(nested(1,number(1,self.balance))+nested(4,nested(3,number(3,1187)+gifts)))
        if url.endswith('ReceiveGift'):
            fields=p.parse(body)
            assert [t for t,w,v in fields]==[1,2,3,4]
            assert p.get(fields,1)==1187 and p.text(p.get(fields,2))=='score'
            assert p.get(fields,4)==self.bound_role
            assert all(k.lower()!='t-gift-type' for k in headers)
            gift=next(d for d in self.defs.values() if d['id']==p.text(p.get(fields,3)))
            if self.fail:raise ServiceError('模拟兑换超时')
            if self.apply:
                gift['used']+=1;gift['status']=1
                self.balance-=gift['cost'] if self.deduction is None else self.deduction
            return response(number(1,1)+number(5,gift['used'])+number(6,gift['total']))
        raise AssertionError('Unexpected endpoint')


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        """Keep all attempt records and fake account identity separate from the production helper."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=ExchangeSession();self.client=ExchangeClient(self.session,self.temp.name)
        self.account={'profile_id':'f'*64,'nickname':'测试','headers':{'T-GIFT-TYPE':'must-be-removed'}}

    def snapshot(self,title='粮木矿礼盒'):
        """Return the exact recipient and gift snapshot a spending confirmation would show."""
        state=self.client.query(self.account)
        return state,next(g for g in state.gifts if g.title==title)

    def test_native_shape_and_both_successes(self):
        """Two separate clicks consume their own quotas and verify 500→410→260, without extra mutations."""
        for title in ['粮木矿礼盒','元神宝盒']:
            state,gift=self.snapshot(title)
            self.assertIn('兑换已确认',self.client.receive(self.account,state.role_key,gift))
        self.assertEqual(self.session.balance,260);self.assertEqual(self.session.calls.count('ReceiveGift'),2)

    def test_query_never_spends(self):
        """A status query performs only binding and page reads, even for an eligible gift."""
        state,gift=self.snapshot();self.assertTrue(state.eligible(gift))
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_role_cost_reward_id_or_quota_change_blocks(self):
        """Confirmed consent cannot authorize a new recipient, price, reward or gift configuration."""
        for field,value in [('cost',91),('qty',11),('id','9999'),('cycle',1),('total',2),('used',1)]:
            state,gift=self.snapshot();definition=self.session.defs[gift.title];old=definition[field];definition[field]=value
            with self.subTest(field=field),self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
            definition[field]=old
        state,gift=self.snapshot();self.session.role=b'changed'
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_insufficient_balance_restriction_and_unknown_status_block(self):
        """Known prices do not override insufficient funds, server binding restrictions or unknown enums."""
        state,gift=self.snapshot();self.session.balance=89
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        self.session.balance=500;self.session.restricted=True
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        self.session.restricted=False;self.session.defs[gift.title]['status']=42
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_completed_exchange_cannot_repeat(self):
        """Both a stale confirmation and a newly queried spent gift are rejected without a second spend."""
        state,gift=self.snapshot();self.client.receive(self.account,state.role_key,gift)
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        new,current=self.snapshot()
        with self.assertRaises(ServiceError):self.client.receive(self.account,new.role_key,current)
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)

    def test_timeout_guard_survives_restart_and_gift_id_change(self):
        """A changed server gift ID cannot bypass the period guard for the same requested reward."""
        state,gift=self.snapshot();self.session.fail=True
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        self.client=ExchangeClient(self.session,self.temp.name);self.session.defs[gift.title]['id']='9999'
        state,current=self.snapshot()
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,current)
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)

    def test_success_response_requires_quota_and_exact_deduction(self):
        """HTTP success alone cannot verify a spend if counters did not change or the deduction differs."""
        for apply,deduction in [(False,None),(True,1)]:
            with self.subTest(apply=apply),tempfile.TemporaryDirectory() as folder:
                session=ExchangeSession();session.apply=apply;session.deduction=deduction
                client=ExchangeClient(session,folder);state=client.query(self.account);gift=state.gifts[0]
                self.assertIn('尚未核对一致',client.receive(self.account,state.role_key,gift))
                with self.assertRaises(ServiceError):client.receive(self.account,state.role_key,gift)
                self.assertEqual(session.calls.count('ReceiveGift'),1)

    def test_accounts_have_independent_guards(self):
        """A pending attempt on one account does not authorize or block another account's separate click."""
        state,gift=self.snapshot();self.session.fail=True
        with self.assertRaises(ServiceError):self.client.receive(self.account,state.role_key,gift)
        self.session.fail=False;other={**self.account,'profile_id':'e'*64}
        self.assertIn('兑换已确认',self.client.receive(other,state.role_key,gift))


if __name__=='__main__':unittest.main()
