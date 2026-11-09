"""Offline checks for the real claim boundary, native header, role changes, and durable duplicate prevention."""
import base64
import tempfile
import time
import unittest
from .auth import Credentials
from .gifts import GiftClient
from .secure_store import AccountStore
from .transport import Response,ServiceError
from . import protocol as p


def number(tag,value):
    """Encode a numeric fixture field using the real protobuf wire codec."""
    return p.varint(tag*8)+p.varint(value)


def nested(tag,data):
    """Encode an embedded fixture message without altering its raw bytes."""
    return p.varint(tag*8+2)+p.varint(len(data))+data


def response(data):
    """Wrap a successful service fixture in its real response envelope."""
    return Response(200,{'Content-Type':'application/proto'},nested(3,data))


class GiftSession:
    """Return binding/status fixtures and count the sole mutating endpoint; never contact a server."""
    def __init__(self):
        self.calls=[];self.status=0;self.days=6;self.restricted=False;self.role=b'role-A'
        self.timeout=False;self.reject=False

    def request(self,url,body=None,headers=None,timeout=20):
        """Emulate the relevant server transitions and assert native scene/header use at the claim boundary."""
        self.calls.append(url.rsplit('/',1)[-1])
        if url.endswith('GetPassCardV2'):
            role=p.message_string(8,base64.b64encode('秋风'.encode()).decode())+p.message_string(6,base64.b64encode('QQ大区'.encode()).decode())+nested(5,self.role)
            game=number(1,1187)+nested(5,role)+number(10,int(self.restricted))
            return response(nested(3,game))
        if url.endswith('GetGamesGifts'):
            self.assert_query=body==bytes.fromhex('0a067369676e696e10a309')
            return response(nested(1,p.message_string(1,'七天签到礼')+number(5,self.days)+number(6,self.status)))
        if url.endswith('ReceiveGamesGift'):
            assert body==p.message_string(1,'signin')
            assert headers['T-GIFT-TYPE']=='signin'
            if self.timeout:raise ServiceError('模拟超时')
            if self.reject:return Response(200,{'Content-Type':'application/proto'},number(1,10010))
            self.status=5;self.days=7
            return response(number(3,1)+number(4,0))
        raise AssertionError('Unexpected endpoint')


class GiftTests(unittest.TestCase):
    def setUp(self):
        """Create isolated fake identities and attempt directories for every test."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=GiftSession();self.client=GiftClient(self.session,self.temp.name)
        self.account={'profile_id':'a'*64,'nickname':'测试','provider':'qq','headers':Credentials('qq','fake-token','fake-identity').headers()}

    def test_native_header_single_claim_and_verified_status(self):
        """Successful flow sends exactly one native-shaped claim and verifies the server transition."""
        state=self.client.query(self.account)
        self.assertIn('秋风',state.role_label);self.assertIn('QQ大区',state.role_label)
        result=self.client.signin(self.account,state.role_key)
        self.assertIn('签到成功',result)
        self.assertEqual(self.session.calls.count('ReceiveGamesGift'),1)
        self.assertEqual(self.client.last_state.days,7)
        self.client.signin(self.account,state.role_key)
        self.assertEqual(self.session.calls.count('ReceiveGamesGift'),1)

    def test_changed_role_never_claims(self):
        """A binding changed after UI confirmation must require a new explicit confirmation."""
        state=self.client.query(self.account);self.session.role=b'role-B'
        with self.assertRaises(ServiceError):self.client.signin(self.account,state.role_key)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)

    def test_first_day_received_does_not_mean_entire_cycle_complete(self):
        """Observed first-day status 5 means today's claim is done, even while six days remain in the cycle."""
        self.session.days=1;self.session.status=5
        state=self.client.query(self.account)
        self.assertFalse(state.available)
        self.assertIn('今日已签到',state.describe())
        self.assertNotIn('本轮已完成',state.describe())
        self.client.signin(self.account,state.role_key)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)

    def test_binding_restriction_and_unknown_status_never_claim(self):
        """Server restriction flags and unrecognized enums fail closed before any mutation."""
        state=self.client.query(self.account);self.session.restricted=True
        self.client.signin(self.account,state.role_key)
        self.session.restricted=False;self.session.status=42
        self.client.signin(self.account,state.role_key)
        self.assertNotIn('ReceiveGamesGift',self.session.calls)

    def test_timeout_and_restart_cannot_duplicate_claim(self):
        """The on-disk guard survives an unknown result and a completely new client object."""
        state=self.client.query(self.account);self.session.timeout=True
        with self.assertRaises(ServiceError):self.client.signin(self.account,state.role_key)
        self.session.timeout=False
        restarted=GiftClient(self.session,self.temp.name)
        with self.assertRaises(ServiceError):restarted.signin(self.account,state.role_key)
        self.assertEqual(self.session.calls.count('ReceiveGamesGift'),1)

    def test_server_rejection_is_not_retried(self):
        """A definitive 10010 remains a reported error; the helper never silently repairs bindings or retries."""
        state=self.client.query(self.account);self.session.reject=True
        with self.assertRaisesRegex(ServiceError,'10010'):self.client.signin(self.account,state.role_key)
        self.assertEqual(self.session.calls.count('ReceiveGamesGift'),1)

    def test_role_consent_encrypted_and_account_specific(self):
        """Thirty-day consent stays encrypted with its own identity and survives token renewal for that identity."""
        store=AccountStore(self.temp.name);a=Credentials('qq','fake-token-A','fake-openid-A');b=Credentials('qq','fake-token-B','fake-openid-B')
        ar=store.save(a,a.headers());br=store.save(b,b.headers())
        store.confirm_role(ar['profile_id'],'role-hash','秋风',True)
        saved=store.load(ar['profile_id'])['role_confirmation']
        self.assertGreater(saved['expires_at'],time.time()+29*86400)
        self.assertNotIn('role_confirmation',store.load(br['profile_id']))
        store.save(a,a.headers())
        self.assertEqual(store.load(ar['profile_id'])['role_confirmation']['role_key'],'role-hash')
        for path in store.folder.glob('*.dpapi'):
            self.assertNotIn(b'fake-token',path.read_bytes());self.assertNotIn('秋风'.encode(),path.read_bytes())


if __name__=='__main__':unittest.main()
