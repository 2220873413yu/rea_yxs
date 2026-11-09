"""Protocol safety checks with fake identities; never contact providers or use saved accounts."""
import unittest
from .auth import QQAuth, Credentials, Challenge
from .transport import Session, ServiceError, Response
from . import protocol
import time
import urllib.parse


class FakeSession:
    """Supply deterministic official-shaped callback responses without real network access."""
    def __init__(self, body):
        self.body = body
        self.calls = []

    def cookie(self, name):
        return 'a'

    def request(self, url, body=None, headers=None, timeout=20):
        self.calls.append(url)
        return Response(200, {}, self.body)


class AuthorizationTests(unittest.TestCase):
    def test_official_proxy_resolves_callback_without_executing_javascript(self):
        """Resolve only the exact official proxy and require its declared app to match this helper."""
        session = FakeSession(b'_Callback({"ret":0,"url":"auth://tauth.qq.com/#access_token=fake&openid=identity&expires_in=60"});')
        result = QQAuth(session).finish('https://imgcache.qq.com/open/connect/widget/mobile/login/proxy.htm'
            '#appid=101484782&redirect_uri_key=fake-key', '')
        self.assertEqual(result.openid, 'identity')
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.calls[0].startswith('https://openmobile.qq.com/oauth2.0/m_get_redirect_url?'))
        for target in ('https://imgcache.qq.com/other#appid=101484782&redirect_uri_key=fake-key',
                       'https://imgcache.qq.com/open/connect/widget/mobile/login/proxy.htm#appid=other&redirect_uri_key=fake-key'):
            with self.assertRaises(ServiceError):
                QQAuth(FakeSession(b'')).finish(target, '')

    def test_official_http_grant_is_upgraded_before_any_request(self):
        """QQ's supported grant hosts must never receive a plaintext callback ticket."""
        session = FakeSession(b'')
        session.request = lambda url,**kwargs: (session.calls.append(url) or Response(302,
            {'Location': 'auth://tauth.qq.com/#access_token=fake&openid=identity'}, b''))
        result = QQAuth(session).finish('http://ssl.ptlogin2.qq.com/check_sig?ticket=fake', '')
        self.assertEqual(result.openid, 'identity')
        self.assertEqual(urllib.parse.urlsplit(session.calls[0]).scheme, 'https')

    def test_unknown_redirect_and_callback_userinfo_are_rejected(self):
        """A QQ-looking suffix or callback userinfo cannot turn an arbitrary site into a trusted endpoint."""
        for url in ('https://ssl.ptlogin2.qq.com.example.org/check_sig',
                    'auth://user@tauth.qq.com/#access_token=fake&openid=identity'):
            session = FakeSession(b'')
            with self.assertRaises(ServiceError):
                QQAuth(session).finish(url, '')
            self.assertEqual(session.calls, [])

    def test_account_headers_never_borrow_another_identity(self):
        first = Credentials('qq', 'fake-token-first', 'fake-openid-first')
        second = Credentials('wx', 'fake-token-second', 'fake-openid-second')
        self.assertNotIn(first.access_token, repr(first))
        self.assertNotIn(first.openid, repr(first))
        self.assertNotIn(second.access_token, str(first.headers()))
        self.assertNotIn(first.access_token, str(second.headers()))
        self.assertIn('acctype=wx', second.headers()['Cookie'])
        self.assertEqual(first.headers()['T-APPID'], '101484782')
        self.assertEqual(first.headers()['T-ACCOUNT-TYPE'], 'qc')
        self.assertIn('acctype=qc', first.headers()['Cookie'])

    def test_waiting_does_not_exchange_or_save_credentials(self):
        session = FakeSession(b"ptuiCB('66','0','','0','waiting','');")
        provider = QQAuth(session)
        challenge = Challenge(b'', time.monotonic()+60, {'params': {'appid':'716027609'},
            'u1':'http://connect.qq.com','open_data':'client_id=101484782','version':'1','finished':False})
        state, value = provider.poll(challenge)
        self.assertEqual(state, 'waiting')
        self.assertIsNone(value)
        self.assertEqual(len(session.calls), 1)
        self.assertIn('ptqrtoken=97', session.calls[0])
        self.assertFalse(challenge.state['finished'])

    def test_expired_challenge_sends_no_request(self):
        session = FakeSession(b'')
        state, value = QQAuth(session).poll(Challenge(b'', time.monotonic()-1, {}))
        self.assertEqual(state, 'expired')
        self.assertEqual(session.calls, [])

    def test_token_callback_requires_both_identity_and_token(self):
        provider = QQAuth(FakeSession(b''))
        with self.assertRaises(ServiceError):
            provider.finish('auth://tauth.qq.com/#access_token=fake-only', '')
        result = provider.finish('auth://tauth.qq.com/#access_token=fake&openid=identity&expires_in=60', 'test')
        self.assertEqual(result.provider, 'qq')
        self.assertEqual(result.nickname, 'test')
        self.assertGreater(result.expires_at, time.time())

    def test_callback_is_not_executed_as_javascript(self):
        with self.assertRaises(ServiceError):
            QQAuth.callback_values(b"__import__('os').system('bad')")
        self.assertEqual(QQAuth.callback_values(b"ptuiCB('67','0','','0','scanned','');")[0], '67')

    def test_nonprovider_target_rejected_before_network(self):
        for target in ('http://bgw.xinyue.qq.com/x','https://example.com/x','https://bgw.xinyue.qq.com@example.com/x'):
            with self.assertRaises(ServiceError) as error:
                Session().request(target, headers={'T-ACCESS-TOKEN':'fake-secret'})
            self.assertNotIn('fake-secret', str(error.exception))

    def test_protobuf_query_encoding_and_truncation(self):
        data = protocol.message_string(1, 'signin') + protocol.varint(16) + protocol.varint(1187)
        self.assertEqual(data.hex(), '0a067369676e696e10a309')
        self.assertEqual(protocol.parse(data), [(1,2,b'signin'),(2,0,1187)])
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse(b'\x0a\x06x')


if __name__ == '__main__':
    unittest.main()
