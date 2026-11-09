"""Offline weekly eligibility and replay guards; no test contacts the service or claims real rewards."""
import tempfile
import unittest
from .auth import Credentials
from .weekly import WeeklyClient
from .transport import ServiceError
from .test_gifts import GiftSession,number,nested,response
from . import protocol as p


class WeekSession(GiftSession):
    """Emulate server qualification, zero-cost weekly config and a verified one-claim transition."""
    def __init__(self):
        super().__init__();self.used=0;self.limit=1;self.cost=0;self.gift_id='734';self.gift_status=0
        self.summary_status=0;self.button='领取';self.next_receive=0;self.summary='超级周礼包';self.fail=False

    def request(self,url,body=None,headers=None,timeout=20):
        """Assert the weekly scene is kept distinct from sign-in and task gift protocols."""
        if url.endswith(('GetPassCardV2','CheckBind')):return super().request(url,body,headers,timeout)
        self.calls.append(url.rsplit('/',1)[-1])
        if url.endswith('GetGamesGifts'):
            assert body==p.message_string(1,'weekGift')+number(2,1187)
            desc=p.message_string(1,self.summary)+number(6,self.summary_status)+number(9,self.next_receive)
            gift=(p.message_string(1,self.gift_id)+nested(4,p.message_string(1,'每周礼包')+p.message_string(7,self.button))
                  +number(6,self.gift_status)+number(7,2)+number(8,self.used)+number(9,self.limit)+number(10,self.cost)+number(14,1))
            return response(nested(1,desc)+nested(2,nested(1,number(3,1187)+nested(7,gift))))
        if url.endswith('ReceiveGamesGift'):
            assert body==p.message_string(1,'weekGift')
            assert headers['T-GIFT-TYPE']=='weekGift'
            if self.fail:raise ServiceError('模拟领取超时')
            self.used+=1;self.gift_status=1
            return response(number(3,1)+number(4,0))
        raise AssertionError('Unexpected endpoint')


class WeekTests(unittest.TestCase):
    def setUp(self):
        """Use isolated storage and fake credentials so guard tests cannot affect local real accounts."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=WeekSession();self.client=WeeklyClient(self.session,self.temp.name)
        self.account={'profile_id':'c'*64,'nickname':'测试','headers':Credentials('qq','fake-token','fake-openid').headers()}

    def test_available_claim_is_once_and_verified(self):
        """Verify response counts and refreshed server usage; a second click must not dispatch again."""
        before=self.client.query(self.account)
        self.assertTrue(before.available)
        result=self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertIn('领取成功',result)
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.session.calls.count('ReceiveGamesGift'),1)

    def test_eligibility_activation_cost_and_time_fail_closed(self):
        """An old available snapshot cannot bypass newly restricted, unactivated, paid or time-limited state."""
        before=self.client.query(self.account)
        for field,value in [('restricted',True),('gift_status',42),('summary_status',3),('button','去激活'),
                            ('cost',1),('next_receive',2000000000),('limit',0),('summary','其他活动')]:
            old=getattr(self.session,field);setattr(self.session,field,value)
            with self.subTest(field=field),self.assertRaises(ServiceError):
                self.client.receive(self.account,before.role_key,before.gift_id)
            setattr(self.session,field,old)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)

    def test_role_and_configuration_changes_block_claim(self):
        """Explicit consent applies only to the current role and server-selected weekly gift ID."""
        before=self.client.query(self.account);self.session.role=b'changed-role'
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.session.role=b'role-A';self.session.gift_id='updated-id'
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)

    def test_timeout_guard_survives_restart_and_changed_gift_id(self):
        """A fresh week-like configuration cannot bypass a same-week ambiguous claim record."""
        before=self.client.query(self.account);self.session.fail=True
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.session.fail=False;self.session.gift_id='changed-after-timeout'
        restarted=WeeklyClient(self.session,self.temp.name);state=restarted.query(self.account)
        with self.assertRaises(ServiceError):restarted.receive(self.account,state.role_key,state.gift_id)
        self.assertEqual(self.session.calls.count('ReceiveGamesGift'),1)


if __name__=='__main__':unittest.main()
