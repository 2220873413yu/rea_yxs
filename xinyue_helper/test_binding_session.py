"""Reproduce old-ticket cached binding restrictions versus the native strict CheckBind validation."""
import json
import unittest
from .auth import Credentials
from .binding_session import LoginExpiredError,check_binding_session
from .roles import RoleClient,LoginChoice
from .test_gifts import GiftSession,number,response
from .gifts import GiftClient
from .transport import Response,ServiceError


class OldTicketSession(GiftSession):
    """Return the observed cached restricted pass card, then reject its obsolete login ticket with 7001."""
    def __init__(self):
        super().__init__();self.restricted=True

    def request(self,url,body=None,headers=None,timeout=20):
        """Fail only the strict native session validation while keeping the misleading old cache readable."""
        if url.endswith('CheckBind'):
            self.calls.append('CheckBind')
            return Response(200,{'Content-Type':'application/json'},json.dumps({'ret':7001,'msg':'invalid credential'}).encode())
        return super().request(url,body,headers,timeout)


class BindingSessionTests(unittest.TestCase):
    def setUp(self):
        """Use a fake account; never load local real tickets or call the network."""
        self.account={'profile_id':'a'*64,'provider':'wx','headers':Credentials('wx','fake-token','fake-openid').headers()}

    def test_cached_restriction_with_old_ticket_requires_login_not_rebinding(self):
        """The user's symptom must become a clear stale-ticket error before displaying repair advice."""
        session=OldTicketSession()
        with self.assertRaisesRegex(LoginExpiredError,'不是需要解绑'):
            GiftClient(session).binding(self.account)
        self.assertEqual(session.calls,['GetPassCardV2','CheckBind'])

    def test_stale_ticket_cannot_enter_role_selection_or_unbind(self):
        """An obsolete ticket stops at CheckBind before platform queries or binding writes."""
        session=OldTicketSession()
        with self.assertRaises(LoginExpiredError):RoleClient(session).partitions(self.account,LoginChoice('ios','wx'))
        self.assertEqual(session.calls,['CheckBind'])

    def test_known_native_available_result_can_proceed_without_writes(self):
        """The observed native result=0,num=3 is an eligibility result, not an activation or claim."""
        session=GiftSession()
        self.assertEqual(check_binding_session(self.account,session,True),(0,3))
        self.assertEqual(session.calls,['CheckBind'])

    def test_unknown_eligibility_does_not_guess_permission_to_bind(self):
        """A valid session with a different eligibility result can be read, but cannot create a new binding."""
        class Session:
            def request(self,*args,**kwargs):
                """Supply a synthetic nonzero native eligibility state."""
                return response(number(1,2))
        self.assertEqual(check_binding_session(self.account,Session()),(2,0))
        with self.assertRaises(ServiceError):check_binding_session(self.account,Session(),True)


if __name__=='__main__':unittest.main()
