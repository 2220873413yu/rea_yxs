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
        self.multi_game=False;self.peace_used=0;self.advance=True;self.business_ret=0;self.change_role=False
        self.claim_bodies=[];self.wrap=False;self.duplicate=False

    def request(self,url,body=None,headers=None,timeout=20):
        """Assert the weekly scene is kept distinct from sign-in and task gift protocols."""
        if url.endswith(('GetPassCardV2','CheckBind')):
            original=super().request(url,body,headers,timeout)
            if self.multi_game and url.endswith('GetPassCardV2'):
                data=p.get(p.parse(original.body),3)
                return response(data+nested(3,number(1,1279)+nested(5,b'foreign-role')))
            return original
        self.calls.append(url.rsplit('/',1)[-1])
        if url.endswith('GetGamesGifts'):
            assert body==p.message_string(1,'weekGift')+number(2,1187)
            desc=p.message_string(1,self.summary)+number(6,self.summary_status)+number(9,self.next_receive)
            gift=(p.message_string(1,self.gift_id)+nested(4,p.message_string(1,'每周礼包')+p.message_string(7,self.button))
                  +number(6,self.gift_status)+number(7,2)+number(8,self.used)+number(9,self.limit)+number(10,self.cost)+number(14,1))
            games=nested(1,number(3,1187)+nested(7,gift)*(2 if self.duplicate else 1))
            if self.multi_game:
                foreign=p.message_string(1,'9473')+number(8,self.peace_used)
                games+=nested(1,number(3,1279)+nested(7,foreign))
            return response(nested(1,desc)+nested(2,games))
        if url.endswith('ReceiveGift'):
            fields=p.parse(body)
            assert p.get(fields,1)==1187
            assert p.text(p.get(fields,2))=='weekGift'
            assert p.text(p.get(fields,3))==self.gift_id
            assert p.get(fields,4)==self.binding_role()
            assert not any(k.lower()=='t-gift-type' for k in headers)
            self.claim_bodies.append(body)
            if self.fail:raise ServiceError('模拟领取超时')
            if self.advance and not self.business_ret:self.used+=1;self.gift_status=1
            if self.change_role:self.role=b'changed-after-claim'
            result=number(1,1)+number(8,self.business_ret)+nested(12,p.message_string(2,'7级野怪卡')+number(4,3))
            return response(nested(1,result) if self.wrap else result)
        raise AssertionError('Unexpected endpoint')

    def binding_role(self):
        """Return the exact fake native role message, not just its inner role identifier."""
        import base64
        return (p.message_string(8,base64.b64encode('秋风'.encode()).decode())
                +p.message_string(6,base64.b64encode('QQ大区'.encode()).decode())+nested(5,self.role))


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
        self.assertIn('跳过',self.client.receive(self.account,before.role_key,before.gift_id))
        self.assertEqual(self.client.result_status,'skipped')
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)

    def test_eligibility_activation_cost_and_time_fail_closed(self):
        """An old available snapshot cannot bypass newly restricted, unactivated, paid or time-limited state."""
        before=self.client.query(self.account)
        for field,value in [('restricted',True),('gift_status',42),('summary_status',3),('button','去激活'),
                            ('cost',1),('next_receive',2000000000),('limit',0),('summary','其他活动')]:
            old=getattr(self.session,field);setattr(self.session,field,value)
            with self.subTest(field=field),self.assertRaises(ServiceError):
                self.client.receive(self.account,before.role_key,before.gift_id)
            setattr(self.session,field,old)
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_role_and_configuration_changes_block_claim(self):
        """Explicit consent applies only to the current role and server-selected weekly gift ID."""
        before=self.client.query(self.account);self.session.role=b'changed-role'
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.session.role=b'role-A';self.session.gift_id='updated-id'
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertNotIn('ReceiveGift',self.session.calls)

    def test_timeout_guard_survives_restart_and_changed_gift_id(self):
        """A fresh week-like configuration cannot bypass a same-week ambiguous claim record."""
        before=self.client.query(self.account);self.session.fail=True
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.session.fail=False;self.session.gift_id='changed-after-timeout'
        restarted=WeeklyClient(self.session,self.temp.name);state=restarted.query(self.account)
        with self.assertRaises(ServiceError):restarted.receive(self.account,state.role_key,state.gift_id)
        self.assertEqual(self.session.calls.count('ReceiveGift'),1)

    def test_multi_game_account_only_claims_current_hero_kill_gift(self):
        """A second binding must not block Hero Kill or cause a foreign-game mutation."""
        self.session.multi_game=True;self.session.gift_id='736'
        self.account['headers']['t-gift-type']='old-bulk-header'
        before=self.client.query(self.account)
        self.assertTrue(before.available);self.assertEqual(set(self.client.bound_game_ids),{1187,1279})
        self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.client.result_status,'success');self.assertEqual(self.session.used,1)
        self.assertEqual(self.session.peace_used,0);self.assertEqual(len(self.session.claim_bodies),1)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)
        self.assertEqual(self.client.actual_rewards,(('7级野怪卡',3),))

    def test_uncertain_response_never_repeats_after_restart(self):
        """A response without a confirmed usage transition stays uncertain and keeps its durable guard."""
        self.session.advance=False
        before=self.client.query(self.account)
        self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.client.result_status,'uncertain')
        restarted=WeeklyClient(self.session,self.temp.name)
        with self.assertRaises(ServiceError):restarted.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(len(self.session.claim_bodies),1)

    def test_business_rejection_never_falls_back_to_bulk(self):
        """A rejected single-gift mutation cannot trigger another endpoint or a second submission."""
        self.session.business_ret=10010
        before=self.client.query(self.account)
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(len(self.session.claim_bodies),1)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)

    def test_role_change_during_verification_is_uncertain(self):
        """An advanced counter from a different role must not confirm the original claim."""
        self.session.change_role=True
        before=self.client.query(self.account)
        self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.client.result_status,'uncertain')

    def test_ambiguous_gift_configuration_blocks_dispatch(self):
        """Multiple matching Hero Kill gifts are not guessed even when other games are bound."""
        self.session.multi_game=True;self.session.duplicate=True
        before=self.client.query(self.account)
        self.assertFalse(before.available)
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.session.claim_bodies,[])

    def test_wrapped_single_receipt_is_verified(self):
        """Accept the native per-game wrapper without interpreting bulk success counters."""
        self.session.wrap=True
        before=self.client.query(self.account)
        self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.client.result_status,'success')

    def test_legacy_attempt_guard_still_blocks_single_endpoint(self):
        """An old bulk claim record must remain authoritative after switching endpoints."""
        from datetime import datetime,timezone,timedelta
        from pathlib import Path
        year,week,_=datetime.now(timezone(timedelta(hours=8))).isocalendar()
        (Path(self.temp.name)/(self.account['profile_id']+f'-{year}-W{week:02d}.json')).write_text(
            '{"state":"dispatched_do_not_repeat"}',encoding='utf-8')
        before=self.client.query(self.account)
        with self.assertRaises(ServiceError):self.client.receive(self.account,before.role_key,before.gift_id)
        self.assertEqual(self.session.claim_bodies,[])


if __name__=='__main__':unittest.main()
