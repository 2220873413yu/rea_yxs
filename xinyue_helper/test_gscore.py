"""Offline no-ad, fresh-state and durable duplicate guards; never contact real accounts."""
import tempfile
import unittest
from .gscore import GScoreClient
from .transport import ServiceError
from .test_gifts import number,nested,response
from . import protocol as p


class PointSession:
    """Model ordinary server signing independently from gift-role binding and advertisements."""
    def __init__(self):
        self.calls=[];self.balance=2885;self.days=0;self.status=0;self.fail=False;self.complete=True;self.missing=False

    def request(self,url,body=None,headers=None,timeout=20):
        """Reject all unexpected endpoints and require the explicit false watchAd field."""
        self.calls.append(url.rsplit('/',1)[-1])
        if url.endswith('GScorePageNew'):
            assert body==b''
            if self.missing:return response(b'')
            return response(nested(1,number(1,self.balance))+nested(2,number(4,self.days)+number(5,self.status)+p.message_string(9,'4331')))
        if url.endswith('GScoreSignWithAd'):
            assert body==bytes.fromhex('0800120434333331')
            if self.fail:raise ServiceError('模拟超时')
            if self.complete:self.balance+=4;self.days+=1;self.status=1
            return response(b'')
        raise AssertionError('Unexpected request: '+url)


class PointTests(unittest.TestCase):
    def setUp(self):
        """Isolate test attempts from all saved credentials and real duplicate guards."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=PointSession();self.client=GScoreClient(self.session,self.temp.name)
        self.account={'profile_id':'d'*64,'headers':{}}

    def test_unsigned_is_once_and_verified(self):
        """An ordinary attempt adds only the base reward and a second invocation only reads."""
        result=self.client.signin(self.account)
        self.assertIn('2885 → 2889',result);self.assertIn('0 → 1',result)
        self.assertIn('已跳过',self.client.signin(self.account))
        self.assertEqual(self.session.calls.count('GScoreSignWithAd'),1)

    def test_fresh_signed_state_skips_without_mutation(self):
        """An earlier unsigned UI snapshot cannot bypass a newer native sign-in."""
        self.assertTrue(self.client.query(self.account).available)
        self.session.status=1;self.session.days=1
        self.assertIn('已跳过',self.client.signin(self.account))
        self.assertNotIn('GScoreSignWithAd',self.session.calls)

    def test_unknown_and_missing_state_block(self):
        """No unknown enum or absent page module can be mistaken for default unsigned state."""
        self.session.status=99
        with self.assertRaises(ServiceError):self.client.signin(self.account)
        self.session.status=0;self.session.missing=True
        with self.assertRaises(ServiceError):self.client.signin(self.account)
        self.assertNotIn('GScoreSignWithAd',self.session.calls)

    def test_timeout_guard_survives_restart(self):
        """A timeout consumes the local attempt guard even while the visible server state stays unsigned."""
        self.session.fail=True
        with self.assertRaises(ServiceError):self.client.signin(self.account)
        restarted=GScoreClient(self.session,self.temp.name)
        with self.assertRaises(ServiceError):restarted.signin(self.account)
        self.assertEqual(self.session.calls.count('GScoreSignWithAd'),1)

    def test_unconfirmed_success_never_repeats(self):
        """HTTP success without a signed post-state remains uncertain and cannot be resent."""
        self.session.complete=False
        self.assertIn('状态待确认',self.client.signin(self.account))
        with self.assertRaises(ServiceError):self.client.signin(self.account)
        self.assertEqual(self.session.calls.count('GScoreSignWithAd'),1)

    def test_account_guards_are_separate(self):
        """A pending attempt for one saved account cannot block a different account's ordinary signing."""
        self.session.fail=True
        with self.assertRaises(ServiceError):self.client.signin(self.account)
        self.session.fail=False
        self.assertIn('已确认',self.client.signin({'profile_id':'e'*64,'headers':{}}))


if __name__=='__main__':unittest.main()
