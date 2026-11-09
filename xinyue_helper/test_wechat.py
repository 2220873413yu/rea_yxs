"""Offline native WeChat user-info request checks; test tickets are synthetic and never sent externally."""
import unittest
from .auth import WeChatAuth,Credentials
from .test_gifts import response
from .gifts import GiftClient
from .transport import Response,ServiceError
from . import protocol as p


class WeChatTests(unittest.TestCase):
    def test_native_user_info_request_uses_current_ticket_only(self):
        """Follow the native post-token read with body tag1 token/tag2 OpenID and isolated wx headers."""
        calls=[]
        class Session:
            def request(self,url,body=None,headers=None):
                calls.append(url)
                self_fields=p.parse(body)
                assert p.text(p.get(self_fields,1))=='fake-wx-token'
                assert p.text(p.get(self_fields,2))=='fake-wx-openid'
                assert headers['T-ACCOUNT-TYPE']=='wx'
                return response(p.message_string(1,'微信测试昵称'))
        nickname=WeChatAuth(Session()).user_info(Credentials('wx','fake-wx-token','fake-wx-openid'))
        self.assertEqual(nickname,'微信测试昵称')
        self.assertEqual(calls,['https://bgw.xinyue.qq.com/XySrv.UserSrv/WechatUserInfo'])

    def test_unbound_hero_query_explains_10020_without_changing_binding(self):
        """The observed 10020 means a missing game binding, not a reason to repeat OAuth or claim."""
        calls=[]
        class Session:
            def request(self,url,body=None,headers=None):
                calls.append(url)
                return Response(200,{'Content-Type':'application/proto'},b'\x08'+p.varint(10020)+p.message_string(2,'请绑定游戏角色'))
        with self.assertRaisesRegex(ServiceError,'绑定'):
            GiftClient(Session()).request('xyapp.GiftSrv/GetGamesGifts',b'',{})
        self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
