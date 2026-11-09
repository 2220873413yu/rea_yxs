"""Reproduce an iOS binding falsely reported as restricted by an Android request context."""
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from .auth import Credentials
from .gifts import GiftClient
from .roles import RoleClient, LoginChoice, Partition
from .test_gifts import number, nested, response
from .test_roles import RoleSession, encoded
from . import protocol as p
from .context import request_headers
from .transport import ServiceError


class PlatformSession(RoleSession):
    """Mirror the observed read-only platform difference and forbid every binding/claim write."""

    def __init__(self):
        super().__init__()
        self.seen_headers = []

    def request(self, url, body=None, headers=None, timeout=20):
        """A stored iOS role is valid for iOS queries and restricted for Android queries."""
        path = url.rsplit('/', 1)[-1]
        self.seen_headers.append(dict(headers))
        if path == 'GetPassCardV2':
            self.calls.append((path, body, headers['T-OPENID']))
            restricted = next(v for k, v in headers.items() if k.lower() == 't-device-type') != 'ios'
            return response(number(6, int(restricted)) + nested(3,
                number(1, 1187) + nested(5, self.bound) + number(10, int(restricted)) + number(12, int(restricted))))
        if path == 'GetGamesGifts':
            self.calls.append((path, body, headers['T-OPENID']))
            return response(nested(1, number(5, 1) + number(6, 5)))
        if path != 'CheckBind':
            raise AssertionError('No binding, acknowledgement or claim is allowed: ' + path)
        return super().request(url, body, headers, timeout)

    def json(self, url, body, headers):
        """Explicit role-picker selection must govern both the JSON body and the HTTP platform header."""
        self.seen_headers.append(dict(headers))
        assert url.rsplit('/', 1)[-1] != 'BindRole', 'An existing valid binding needs no new role acknowledgement'
        if url.endswith('GetPartitionList') or url.endswith('GetSpecifyRoleList'):
            assert headers['T-DEVICE-TYPE'] == body['device'], 'Selected platform was lost in the HTTP context'
        return super().json(url, body, headers)


class PlatformContextTests(unittest.TestCase):
    """Use actual service entrypoints so a missed header application reproduces the user-visible failure."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = PlatformSession()
        self.session.name = '测试'
        self.account = {'profile_id': 'a' * 64, 'provider': 'wx', 'nickname': '测试', 'game_device': 'ios',
                        'headers': Credentials('wx', 'fake-token', 'fake-openid').headers()}
        self.role_client = RoleClient(self.session, self.temp.name)

    def install_role(self):
        """Provide the same stable bound recipient independently of the request platform."""
        raw = {'game_open_id': 'synthetic-game-openid', 'game_app_id': 'synthetic-app', 'area_id': 1,
               'plat_id': 0, 'partition_id': 7, 'partition_name': encoded('微信大区'),
               'role_id': 'synthetic-role', 'role_name': encoded('测试'), 'device': 'ios'}
        from .roles import Role
        role = Role(self.account['profile_id'], LoginChoice('ios', 'wx'), 7, '测试', '微信大区', raw)
        self.session.bound = role.wire()
        return role

    def test_saved_ios_selection_removes_false_restriction_without_any_write(self):
        """This is the exact Android-header/iOS-binding symptom observed against the live read-only API."""
        self.install_role()
        before = dict(self.account['headers'])
        state = GiftClient(self.session).query(self.account)
        self.assertFalse(state.binding_restricted)
        self.assertEqual(state.status, 5)
        self.assertEqual(self.account['headers'], before)
        self.assertEqual([c[0] for c in self.session.calls], ['GetPassCardV2', 'GetGamesGifts'])

    def test_same_bound_recipient_does_not_acknowledge_or_rebind_again(self):
        """A valid matching binding bypasses BindRole, unbind and PassCardBindGameRoleV2 entirely."""
        role = self.install_role()
        message = self.role_client.bind(self.account, role)
        self.assertIn('未重复提交', message)
        self.assertFalse(any(c[0] in ('BindRole', 'PassCardUnbindGameRole', 'PassCardBindGameRoleV2') for c in self.session.calls))

    def test_explicit_picker_platform_overrides_saved_platform_for_that_read_only(self):
        """Selecting Android cannot send an iOS header or mutate the saved iOS account snapshot."""
        self.account['headers']['T-DEVICE-TYPE'] = 'ios'
        self.role_client.partitions(self.account, LoginChoice('android', 'wx'))
        self.assertEqual(self.session.seen_headers[-1]['T-DEVICE-TYPE'], 'android')
        self.assertEqual(self.account['game_device'], 'ios')
        self.assertEqual(self.account['headers']['T-DEVICE-TYPE'], 'ios')

    def test_valid_binding_check_never_opens_unbind_confirmation(self):
        """Exercise the actual dialog decision without creating a window or invoking any mutation."""
        self.install_role()
        snapshot = self.role_client.prepare_repair(self.account)
        from .role_dialog import RoleDialog
        dialog = Mock()
        dialog.account = {'profile_id': 'a' * 64}
        with patch('xinyue_helper.role_dialog.messagebox.askokcancel') as confirm:
            RoleDialog.confirm_repair(dialog, snapshot)
        self.assertFalse(snapshot.restricted)
        confirm.assert_not_called()
        dialog.run.assert_not_called()
        self.assertIn('可直接使用', dialog.status.set.call_args.args[0])

    def test_display_name_difference_does_not_turn_same_identity_into_another_binding(self):
        """A stale name/label on the bound snapshot must not cause another BindRole request."""
        role = self.install_role()
        self.session.bound = replace(role, raw={**role.raw, 'role_name': encoded('旧名称')}).wire()
        self.assertIn('未重复提交', self.role_client.bind(self.account, role))
        other = replace(role, raw={**role.raw, 'role_id': 'different-role'})
        self.assertFalse(RoleClient.matches(self.session.bound, other))


class RequestHeaderContextTests(unittest.TestCase):
    """All four user choices change only the platform header, never the OAuth identity or source record."""

    def test_qq_and_wechat_both_honor_android_and_ios_without_changing_credentials(self):
        """Retain exact Token/OpenID/AppID/Cookie values and collapse case-insensitive platform duplicates."""
        for provider in ('qq', 'wx'):
            for device in ('android', 'ios'):
                with self.subTest(provider=provider, device=device):
                    headers = Credentials(provider, 'fake-token', 'fake-openid').headers()
                    headers['t-device-type'] = 'stale-platform'
                    account = {'game_device': device, 'headers': headers}
                    before = dict(headers)
                    scoped = request_headers(account)
                    self.assertEqual(scoped['T-DEVICE-TYPE'], device)
                    self.assertEqual(sum(k.lower() == 't-device-type' for k in scoped), 1)
                    for key in ('T-ACCESS-TOKEN', 'T-OPENID', 'T-APPID', 'T-ACCOUNT-TYPE', 'Cookie'):
                        self.assertEqual(scoped[key], before[key])
                    self.assertEqual(headers, before)

    def test_unknown_selection_is_rejected_and_legacy_context_is_not_guessed(self):
        """Invalid choices cannot reach a request; records without a choice keep their previous context."""
        account = {'headers': {'T-DEVICE-TYPE': 'android'}, 'game_device': 'unknown'}
        with self.assertRaises(ServiceError):
            request_headers(account)
        del account['game_device']
        self.assertEqual(request_headers(account), account['headers'])


if __name__ == '__main__':
    unittest.main()
