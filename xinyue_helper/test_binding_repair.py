"""Offline regression coverage for restricted existing bindings and explicitly confirmed one-shot repair."""
import tempfile
import unittest
from .test_roles import RoleSession
from .test_gifts import number,nested,response
from .roles import RoleClient,LoginChoice,Partition
from .auth import Credentials
from .transport import Response,ServiceError
from . import protocol as p


class RepairSession(RoleSession):
    """Simulate exact-current-recipient unbind/rebind with failures at either mutating boundary."""
    def __init__(self):
        super().__init__();self.restricted=True;self.fail_unbind=False;self.keep_bound=False;self.still_restricted=False

    def request(self,url,body=None,headers=None,timeout=20):
        """Accept only the observed binding APIs, recording each write and exposing configurable server flags."""
        path=url.rsplit('/',1)[-1]
        if path=='GetPassCardV2':
            self.calls.append((path,body,headers['T-OPENID']))
            game=number(1,1187)+nested(5,self.bound)+number(10,int(self.restricted))+number(12,int(self.restricted))
            return response(number(6,int(self.restricted))+(nested(3,game) if self.bound else b''))
        if path=='PassCardUnbindGameRole':
            self.calls.append((path,body,headers['T-OPENID']))
            assert p.get(p.parse(body),1)==1187
            assert p.get(p.parse(body),2)==self.bound
            if self.fail_unbind:raise ServiceError('模拟解除结果未知')
            if not self.keep_bound:self.bound=b''
            return Response(200,{'Content-Type':'application/proto'},b'')
        result=super().request(url,body,headers,timeout)
        if path=='PassCardBindGameRoleV2':self.restricted=self.still_restricted
        return result


class BindingRepairTests(unittest.TestCase):
    def setUp(self):
        """Create an already bound iOS fixture, matching the reported real-account restriction pattern."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=RepairSession();self.client=RoleClient(self.session,self.temp.name)
        self.account={'profile_id':'a'*64,'provider':'wx','nickname':'测试',
                      'headers':Credentials('wx','fake-token','fake-openid').headers()}
        self.role=self.client.roles(self.account,LoginChoice('ios','wx'),Partition(7,'测试'))[0]
        self.session.bound=self.role.wire()

    def count(self,path):
        """Count writes separately from read-only preflight/verification calls."""
        return sum(c[0]==path for c in self.session.calls)

    def test_restricted_same_role_is_not_reported_as_normal_binding_success(self):
        """Native role acknowledgement alone must not falsely clear unchanged server restriction flags."""
        with self.assertRaisesRegex(ServiceError,'仍受限'):self.client.bind(self.account,self.role)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),0)

    def test_prepare_reads_actual_ios_binding_without_mutation(self):
        """The repair candidate comes from the server binding, never a separately selected Android role."""
        snapshot=self.client.prepare_repair(self.account)
        self.assertEqual(snapshot.role.choice,LoginChoice('ios','wx'));self.assertTrue(snapshot.restricted)
        self.assertEqual(self.count('PassCardUnbindGameRole'),0)

    def test_native_role_acknowledgement_can_clear_flags_without_rebinding(self):
        """The missing native selection stage is allowed once for the same confirmed recipient, without unbinding."""
        original=self.session.json
        def acknowledge(url,body,headers):
            """Emulate the native role-registration side effect separately from pass-card binding."""
            result=original(url,body,headers)
            if url.endswith('BindRole'):self.session.restricted=False
            return result
        self.session.json=acknowledge
        result=self.client.bind(self.account,self.role)
        self.assertIn('已补全原生角色确认',result)
        self.assertEqual(self.count('BindRole'),1)
        self.assertEqual(self.count('PassCardUnbindGameRole'),0)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),0)

    def test_success_unbinds_once_then_rebinds_exact_same_recipient(self):
        """Readback must show both the original recipient and cleared restriction before reporting success."""
        snapshot=self.client.prepare_repair(self.account)
        result=self.client.repair(self.account,snapshot)
        self.assertIn('处理成功',result);self.assertEqual(self.count('PassCardUnbindGameRole'),1)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),1)
        writes=[call for call in self.session.calls if call[0] in ('PassCardUnbindGameRole','PassCardBindGameRoleV2')]
        self.assertEqual(writes[0][1],writes[1][1]);self.assertEqual(self.session.bound,snapshot.wire)
        self.client.repair(self.account,snapshot)
        self.assertEqual(self.count('PassCardUnbindGameRole'),1)

    def test_changed_current_binding_aborts_before_unbinding(self):
        """A role change after the confirmation snapshot invalidates that confirmation completely."""
        snapshot=self.client.prepare_repair(self.account);self.session.bound=p.message_string(7,'other')
        with self.assertRaisesRegex(ServiceError,'已变化'):self.client.repair(self.account,snapshot)
        self.assertEqual(self.count('PassCardUnbindGameRole'),0)

    def test_unbind_timeout_never_rebinds_and_guard_survives_restart(self):
        """An unknown first-write result stops the pipeline; a new client cannot replay it."""
        snapshot=self.client.prepare_repair(self.account);self.session.fail_unbind=True
        with self.assertRaisesRegex(ServiceError,'解除绑定阶段停止'):self.client.repair(self.account,snapshot)
        self.session.fail_unbind=False
        with self.assertRaisesRegex(ServiceError,'已有受限处理记录'):
            RoleClient(self.session,self.temp.name).repair(self.account,snapshot)
        self.assertEqual(self.count('PassCardUnbindGameRole'),1);self.assertEqual(self.count('PassCardBindGameRoleV2'),0)

    def test_unbind_success_with_remaining_binding_never_overwrites_it(self):
        """Even a successful unbind envelope requires an empty readback before the rebind write."""
        snapshot=self.client.prepare_repair(self.account);self.session.keep_bound=True
        with self.assertRaisesRegex(ServiceError,'仍有绑定'):self.client.repair(self.account,snapshot)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),0)

    def test_rebind_timeout_stops_with_empty_binding_and_no_retry(self):
        """The partial-completion state is explicit; a later click cannot replay either mutation."""
        snapshot=self.client.prepare_repair(self.account);self.session.timeout=True
        with self.assertRaisesRegex(ServiceError,'重新绑定阶段停止'):self.client.repair(self.account,snapshot)
        self.assertEqual(self.session.bound,b'')
        with self.assertRaises(ServiceError):self.client.repair(self.account,snapshot)
        self.assertEqual(self.count('PassCardUnbindGameRole'),1);self.assertEqual(self.count('PassCardBindGameRoleV2'),1)

    def test_remaining_server_restriction_is_not_success(self):
        """Rebinding the right role does not prove eligibility; server restriction flags remain authoritative."""
        snapshot=self.client.prepare_repair(self.account);self.session.still_restricted=True
        with self.assertRaisesRegex(ServiceError,'仍返回受限'):self.client.repair(self.account,snapshot)
        self.assertEqual(self.session.bound,snapshot.wire)


if __name__=='__main__':unittest.main()
