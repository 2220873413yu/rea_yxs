"""Offline account/platform discovery and binding-boundary checks; no real tickets or network calls."""
import base64
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from .auth import Credentials
from .roles import LoginChoice,RoleClient,Partition,RoleConsentRequired,decode_label
from .transport import Response,ServiceError
from .secure_store import AccountStore
from .test_gifts import number,nested,response
from . import protocol as p


def encoded(text):
    """Emulate the observed URL-safe, unpadded labels without any real role data."""
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


class RoleSession:
    """Model only native role reads, consent and one pass-card binding; reject every claim endpoint."""
    def __init__(self):
        self.calls=[];self.bound=b'';self.gated=False;self.timeout=False;self.confirm_binding=True
        self.device_override=None;self.name='测试旅行';self.paged=False;self.changed=False

    def json(self,url,body,headers):
        """Return platform-specific fixtures and record exact inputs for account isolation assertions."""
        path=url.rsplit('/',1)[-1];self.calls.append((path,body,headers['T-OPENID']))
        if self.gated:return {'ret':400000}
        assert body['is_auth'] is True
        assert body['device'] in ('ios','android')
        if path=='BindRole':
            assert body['scene']=='xinyue' and body['role']['device']==body['device']
            return {'ret':0}
        if path=='GetPartitionList':return {'ret':0,'list':[{'id':7,'name':encoded('服务器区服标签')}]}
        if path=='GetSpecifyRoleList':
            device=self.device_override or body['device']
            raw={'game_open_id':'synthetic-game-openid','game_app_id':'synthetic-app',
                 'area_id':1,'plat_id':0 if device=='ios' else 1,'partition_id':body['partition_id'],
                 'partition_name':encoded('微信大区'),'role_id':'changed' if self.changed else 'synthetic-role',
                 'role_name':encoded(self.name),'device':device}
            return {'ret':0,'roles':[raw],'next_page_no':2 if self.paged and body['page_no']==1 else -1}
        raise AssertionError('Unexpected read endpoint')

    def request(self,url,body=None,headers=None,timeout=20):
        """Simulate binding receipts and fresh readback, never permit sign-in, prizes or exchanges."""
        path=url.rsplit('/',1)[-1];self.calls.append((path,body,headers['T-OPENID']))
        if path=='CheckBind':return response(number(2,3))
        if path=='UpdateSettingSwitch':
            self.gated=False
            return Response(200,{'Content-Type':'application/proto'},b'')
        if path=='GetPassCardV2':
            return response(nested(3,number(1,1187)+nested(5,self.bound)) if self.bound else b'')
        if path=='PassCardBindGameRoleV2':
            assert p.get(p.parse(body),1)==1187
            if self.timeout:raise ServiceError('模拟绑定结果未知')
            if self.confirm_binding:self.bound=p.get(p.parse(body),2)
            return Response(200,{'Content-Type':'application/proto'},b'')
        raise AssertionError('Unexpected business endpoint: '+path)


class RolesTests(unittest.TestCase):
    def setUp(self):
        """Give every test isolated synthetic credentials and durable attempt files."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=RoleSession();self.client=RoleClient(self.session,self.temp.name)
        self.account={'profile_id':'a'*64,'nickname':'测试账号','provider':'wx',
                      'headers':Credentials('wx','fake-token','fake-openid').headers()}
        self.choice=LoginChoice('ios','wx');self.partition=Partition(7,'测试区服')

    def role(self):
        """Obtain a fresh fixture role using the actual bounded server parsing path."""
        return self.client.roles(self.account,self.choice,self.partition)[0]

    def count(self,name):
        """Count only the selected endpoint, independent of readback volume."""
        return sum(call[0]==name for call in self.session.calls)

    def test_explicit_choices_and_no_implicit_platform(self):
        """All four combinations are accepted; absent or unsupported selections fail before networking."""
        for device in ('ios','android'):
            for provider in ('qq','wx'):
                choice=LoginChoice(device,provider)
                account={**self.account,'provider':provider,'headers':Credentials(provider,'fake-token','fake-openid').headers()}
                parts=self.client.partitions(account,choice)
                roles=self.client.roles(account,choice,parts[0])
                self.assertEqual(roles[0].choice,choice)
                self.assertEqual(self.session.calls[-1][1]['partition_id'],7)
                self.assertEqual(self.session.calls[-1][1]['device'],device)
        for device,provider in (('','wx'),('ios',''),('windows','qq')):
            with self.assertRaises(ServiceError):LoginChoice(device,provider)

    def test_privacy_gate_is_not_bypassed_and_private_consent_matches_native_wire(self):
        """A gated read cannot silently authorize; the explicit consent call uses map GameRole action 2."""
        self.session.gated=True
        with self.assertRaises(RoleConsentRequired):self.client.partitions(self.account,self.choice)
        self.assertEqual(self.count('UpdateSettingSwitch'),0)
        self.client.consent_private(self.account,self.choice)
        wire=next(c[1] for c in self.session.calls if c[0]=='UpdateSettingSwitch')
        entry=p.parse(p.get(p.parse(wire),1))
        self.assertEqual(p.text(p.get(entry,1)),'GameRole')
        self.assertEqual(p.text(p.get(entry,2)),'{"gid":1187, "authAction":2}')
        self.assertEqual(self.client.partitions(self.account,self.choice)[0].id,7)

    def test_pagination_deduplicates_and_decodes_actual_role_area(self):
        """Picker labels may differ from role labels; the role keeps its own returned area and name."""
        self.session.paged=True
        roles=self.client.roles(self.account,self.choice,self.partition)
        self.assertEqual(len(roles),1);self.assertEqual(self.count('GetSpecifyRoleList'),2)
        self.assertEqual(roles[0].name,'测试旅行');self.assertEqual(roles[0].partition_name,'微信大区')
        self.assertNotIn('synthetic-role',repr(roles[0]))
        self.assertEqual(decode_label('5b6u5L-h5aSn5Yy6'),'微信大区')

    def test_wrong_provider_or_returned_platform_is_rejected(self):
        """No provider mismatch request or silently substituted device is allowed."""
        with self.assertRaises(ServiceError):self.client.partitions(self.account,LoginChoice('ios','qq'))
        self.assertEqual(self.session.calls,[])
        self.session.device_override='android'
        with self.assertRaisesRegex(ServiceError,'平台'):self.role()

    def test_query_does_not_bind_or_claim(self):
        """Discovery performs only the two observed read endpoints."""
        self.client.partitions(self.account,self.choice);self.role()
        self.assertEqual([c[0] for c in self.session.calls],['CheckBind','GetPartitionList','GetSpecifyRoleList'])

    def test_selected_role_revalidated_then_bind_once_and_read_back(self):
        """The binding wire preserves the confirmed own role and readback prevents a false success."""
        role=self.role();message=self.client.bind(self.account,role)
        self.assertIn('绑定成功',message);self.assertEqual(self.count('PassCardBindGameRoleV2'),1)
        self.assertEqual(p.get(p.parse(next(c[1] for c in self.session.calls if c[0]=='PassCardBindGameRoleV2')),2),role.wire())
        self.assertTrue(all(c[2]=='fake-openid' for c in self.session.calls))
        self.assertIn('未重复提交',self.client.bind(self.account,role))
        self.assertEqual(self.count('PassCardBindGameRoleV2'),1)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.dpapi'))),2)
        self.assertEqual(self.count('BindRole'),1)
        names=[call[0] for call in self.session.calls]
        self.assertLess(names.index('BindRole'),names.index('PassCardBindGameRoleV2'))

    def test_other_account_changed_role_and_existing_other_binding_never_write(self):
        """A stale/cross-account role or existing different recipient cannot cause an implicit rebind."""
        role=self.role()
        with self.assertRaises(ServiceError):self.client.bind({**self.account,'profile_id':'b'*64},role)
        self.session.changed=True
        with self.assertRaises(ServiceError):self.client.bind(self.account,role)
        self.session.changed=False
        self.session.bound=p.message_string(7,'another-role')
        with self.assertRaisesRegex(ServiceError,'不会自动解绑'):self.client.bind(self.account,role)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),0)

    def test_uncertain_submission_stays_blocked_across_client_restart_and_rename(self):
        """A timeout creates a durable guard that cannot be bypassed by nickname changes or a restart."""
        role=self.role();self.session.timeout=True
        with self.assertRaises(ServiceError):self.client.bind(self.account,role)
        self.session.timeout=False;self.session.name='新昵称'
        again=RoleClient(self.session,self.temp.name);new_role=again.roles(self.account,self.choice,self.partition)[0]
        self.assertNotEqual(role.identity(),new_role.identity());self.assertEqual(role.binding_key(),new_role.binding_key())
        with self.assertRaisesRegex(ServiceError,'结果未确认'):again.bind(self.account,new_role)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),1)

    def test_empty_readback_is_not_reported_as_binding_success(self):
        """ret=0 without a matching server binding remains uncertain and never triggers a second write."""
        self.session.confirm_binding=False;role=self.role()
        with self.assertRaisesRegex(ServiceError,'尚未核对一致'):self.client.bind(self.account,role)
        with self.assertRaisesRegex(ServiceError,'结果未确认'):self.client.bind(self.account,role)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),1)

    def test_verified_history_does_not_block_new_explicit_binding_when_server_is_empty(self):
        """Reproduce the reported old verified marker plus a fresh empty server binding without deleting history."""
        role=self.role();self.client.bind(self.account,role)
        original=Path(self.temp.name)/(role.binding_key()+'.json')
        original_bytes=original.read_bytes()
        self.session.bound=b''
        result=RoleClient(self.session,self.temp.name).bind(self.account,role)
        self.assertIn('绑定成功',result);self.assertEqual(self.count('PassCardBindGameRoleV2'),2)
        self.assertEqual(original.read_bytes(),original_bytes)
        self.assertTrue(original.with_name(role.binding_key()+'-2.json').exists())

    def test_uncertain_new_revision_still_blocks_after_verified_history(self):
        """A completed first attempt cannot mask an uncertain later attempt across another process restart."""
        role=self.role();self.client.bind(self.account,role);self.session.bound=b'';self.session.timeout=True
        with self.assertRaises(ServiceError):self.client.bind(self.account,role)
        self.session.timeout=False
        with self.assertRaisesRegex(ServiceError,'结果未确认'):
            RoleClient(self.session,self.temp.name).bind(self.account,role)
        self.assertEqual(self.count('PassCardBindGameRoleV2'),2)

    def test_saved_platform_survives_ticket_refresh_and_clears_old_claim_consent(self):
        """DPAPI stores explicit platform metadata without exposing ticket data or retaining old recipient approval."""
        store=AccountStore(Path(self.temp.name)/'accounts');credentials=Credentials('wx','fake-token','fake-openid',nickname='测试')
        row=store.save(credentials,credentials.headers());key=row['profile_id']
        store.set_game_device(key,'ios');store.confirm_role(key,'old-role','测试',True)
        store.save(credentials,credentials.headers())
        self.assertEqual(store.load(key)['game_device'],'ios')
        store.set_game_device(key,'ios',clear_confirmation=True)
        self.assertNotIn('role_confirmation',store.load(key))
        self.assertEqual(store.list()[0]['game_device'],'ios')


if __name__=='__main__':unittest.main()
