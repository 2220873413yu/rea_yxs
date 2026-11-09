"""Credential persistence, stopped-process transactions and account-login isolation with no real game actions."""
import base64
import copy
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import frida
from lupa import LuaRuntime

from account_store import AccountStore, AccountError, TicketExpired, crypt_profile, profile_key, validate_profile, AUTH_KEYS
from account_transport import AccountTransport, SDK_DB, SDK_PREF, GAME_SETTING, merge_wal
from account_service import AccountService
from login_session import LoginSession
from account_lock import account_operation, ensure_account_available


def sdk_db(qq=(), wx=('alice',)):
    """Build a real SQLite SDK-shaped database using explicitly fake opaque credentials."""
    db = sqlite3.connect(':memory:')
    for table, names in (('qq_login_info', qq), ('wx_login_info', wx)):
        db.execute('create table ' + table + '(open_id text unique,access_token text,refresh_token text)')
        for name in names:
            db.execute('insert into ' + table + ' values(?,?,?)', (name.encode().hex(), 'opaque-sdk-cipher-' + name, 'opaque-refresh'))
    db.commit()
    data = db.serialize()
    db.close()
    return data


def profile(mobile=1, platform=0, name='alice'):
    """Create a synthetic profile whose identity, role and selected database record are internally consistent."""
    data = sdk_db((name,) if platform else (), () if platform else (name,))
    return dict(format=2, role=dict(logged_in=True, ret=0, nickname_hex='旅行'.encode().hex(), level=17,
                mobile_platform=mobile, open_platform=platform), openid=name, zone=1, no_auto_login=0,
                database=base64.b64encode(data).decode(), db_sha256=hashlib.sha256(data).hexdigest(),
                sdk_access_token_sha256=hashlib.sha256(b'fake-access').hexdigest(),
                auth_preferences=[ET.tostring(ET.Element('string', name=k.encode().hex()), encoding='unicode') for k in sorted(AUTH_KEYS)])


def test_cipher(data, decrypt=False):
    """Use a deterministic fake envelope for fault injection only; DPAPI itself is tested separately."""
    return data[4:][::-1] if decrypt else b'TEST' + data[::-1]


class ProfileStoreTests(unittest.TestCase):
    """Real file persistence may contain ciphertext only and must separate identities independently of display names."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AccountStore(self.temp.name, test_cipher)

    def test_real_dpapi_hides_credentials_and_rejects_corruption(self):
        """Windows encryption must round-trip private data without leaving its literal token in the file."""
        plain = b'{"token":"synthetic-test-secret","nickname":"public"}'
        encrypted = crypt_profile(plain)
        self.assertNotIn(b'synthetic-test-secret', encrypted)
        self.assertEqual(crypt_profile(encrypted, True), plain)
        with self.assertRaises(AccountError):
            crypt_profile(encrypted[:30], True)

    def test_save_updates_stable_identity_but_separates_mobile_platform_and_zone(self):
        """Renaming a role updates its record; same SDK account on iOS, Android or another zone stays separate."""
        value = profile()
        first = self.store.save(value)
        value['role']['nickname_hex'] = '新昵称'.encode().hex()
        renamed = self.store.save(value)
        self.assertEqual(first['profile_id'], renamed['profile_id'])
        self.assertEqual(self.store.list()[0]['name'], '新昵称')
        self.store.save(profile(mobile=0))
        value['zone'] = 2
        self.store.save(value)
        self.assertEqual(len(self.store.list()), 3)
        public = json.dumps(self.store.list(), ensure_ascii=False)
        self.assertNotIn('fake-access', public)
        self.assertNotIn('opaque-sdk-cipher', public)
        self.assertNotIn('openid', public)
        self.assertNotIn('sdk_access_token_sha256', public)
        for path in Path(self.temp.name).glob('*.dpapi'):
            self.assertNotIn(b'opaque-sdk-cipher', path.read_bytes())

    def test_bad_profile_or_cipher_failure_keeps_previous_profile_unchanged(self):
        """Validate before encryption and commit only after encrypted readback succeeds."""
        value = profile();row = self.store.save(value)
        path = Path(self.temp.name) / (row['profile_id'] + '.dpapi')
        original = path.read_bytes()
        broken = copy.deepcopy(value);broken['database'] = base64.b64encode(b'wrong').decode()
        with self.assertRaises(AccountError):self.store.save(broken)
        self.store.cipher = lambda data, decrypt=False: b'bad'
        with self.assertRaises((AccountError, ValueError)):self.store.save(value)
        self.assertEqual(path.read_bytes(), original)

    def test_bad_file_does_not_hide_healthy_records_and_paths_are_bounded(self):
        """A corrupted account is shown as unavailable without decrypting arbitrary paths selected by the UI."""
        self.store.save(profile())
        (Path(self.temp.name) / ('f' * 64 + '.dpapi')).write_bytes(b'bad')
        rows = self.store.list()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(bool(r.get('unreadable')) for r in rows), 1)
        with self.assertRaises(AccountError):self.store.load('../outside')
        bad = profile();bad['database'] = base64.b64encode(sdk_db(wx=('alice', 'other-account'))).decode()
        bad['db_sha256'] = hashlib.sha256(base64.b64decode(bad['database'])).hexdigest()
        with self.assertRaises(AccountError):validate_profile(bad)

    def test_import_is_once_per_identity_and_expired_mark_keeps_ciphertext(self):
        """Startup migration may not overwrite a newer saved token or erase a profile that requires scanning."""
        value = profile();legacy = Path(self.temp.name) / 'legacy.dpapi'
        legacy.write_bytes(test_cipher(json.dumps(value).encode()))
        self.store.import_legacy([legacy])
        key = profile_key(value)
        self.store.mark_scan_required(key)
        self.store.import_legacy([legacy])
        self.assertEqual(self.store.load(key)['ticket_status'], '需要重新扫码')

    def test_deleted_identity_stays_deleted_after_legacy_import_but_can_be_saved_again(self):
        """Deleting iOS must survive restart/migration without affecting Android or blocking a fresh authorized scan."""
        value=profile()
        deleted=self.store.save(value)
        kept=self.store.save(profile(mobile=0))
        kept_path=self.store._path(kept['profile_id'])
        kept_ciphertext=kept_path.read_bytes()
        legacy=Path(self.temp.name)/'legacy.dpapi'
        legacy.write_bytes(test_cipher(json.dumps(value).encode()))
        self.store.delete(deleted['profile_id'])
        restarted=AccountStore(self.temp.name,test_cipher)
        restarted.import_legacy([legacy])
        self.assertEqual([r['profile_id'] for r in restarted.list()],[kept['profile_id']])
        self.assertFalse(restarted._path(deleted['profile_id']).exists())
        self.assertEqual(kept_path.read_bytes(),kept_ciphertext)
        restored=restarted.save(value)
        self.assertEqual(restored['profile_id'],deleted['profile_id'])
        self.assertEqual(len(restarted.list()),2)

    def test_delete_rejects_paths_and_does_not_remove_ticket_if_marker_cannot_be_saved(self):
        """Durable suppression must succeed before unlinking ciphertext; caller-controlled paths are forbidden."""
        row=self.store.save(profile())
        before=self.store._path(row['profile_id']).read_bytes()
        with self.assertRaises(AccountError):self.store.delete('../outside')
        with patch.object(Path,'touch',side_effect=OSError('disk unavailable')):
            with self.assertRaises(AccountError):self.store.delete(row['profile_id'])
        self.assertEqual(self.store._path(row['profile_id']).read_bytes(),before)


class TransportTests(unittest.TestCase):
    """File writes are all-or-nothing and require the old process to be fully stopped."""

    def make_transport(self, fail_pref=False):
        """Use an in-memory Android filesystem and real restore orchestration; no ADB operations run."""
        transport = AccountTransport()
        old = {SDK_DB: b'old-database', SDK_DB + '-wal': b'old-wal', SDK_DB + '-shm': b'old-shm', SDK_PREF: b'<map><int name="device" value="1"/></map>'}
        files = dict(old)
        files[GAME_SETTING] = b'mNoAutoLogin\x10\x01'
        transport.read = Mock(side_effect=lambda path, optional=False: files.get(path, b''))
        transport.run = Mock(return_value=b'')
        transport.pid = Mock(return_value=None)
        failed = False

        def write(path, data):
            """Simulate a single preference write failure after the database has already been committed."""
            nonlocal failed
            if path == SDK_PREF and fail_pref and not failed:
                failed = True
                raise AccountError('synthetic write failure')
            files[path] = data
        transport._write = Mock(side_effect=write)
        transport._remove_journal = Mock(side_effect=lambda: [files.pop(p, None) for p in (SDK_DB + '-wal', SDK_DB + '-shm')])
        return transport, old, files

    def test_busy_process_never_permits_file_writes(self):
        """A delayed force-stop is a blocker, not permission to replace an open SQLite database."""
        transport, _, _ = self.make_transport()
        transport.pid.return_value = '123'
        with patch('account_transport.time.monotonic', side_effect=[0, 10]):
            with self.assertRaises(AccountError):transport.restart(threading.Event(), profile())
        transport._write.assert_not_called()

    def test_write_failure_restores_original_database_journals_and_preferences(self):
        """Failure between the two SDK file commits rolls all original account state back before reporting it."""
        transport, old, files = self.make_transport(True)
        with self.assertRaisesRegex(AccountError, '已回滚'):transport.restart(threading.Event(), profile())
        for key in old:self.assertEqual(files[key], old[key])
        self.assertFalse(any('am start' in c.args[0] for c in transport.run.call_args_list))

    def test_success_updates_only_authorized_sdk_keys_and_clears_stale_journals(self):
        """Restore keeps unrelated SDK device preferences and starts only after both files are complete."""
        transport, _, files = self.make_transport()
        transport.restart(threading.Event(), profile())
        self.assertEqual(files[SDK_DB], base64.b64decode(profile()['database']))
        self.assertNotIn(SDK_DB + '-wal', files)
        nodes = ET.fromstring(files[SDK_PREF])
        self.assertIsNotNone(next((node for node in nodes if node.attrib.get('name') == 'device'), None))
        self.assertTrue(any('am start' in c.args[0] for c in transport.run.call_args_list))

    def test_invalid_profile_and_cancellation_do_not_stop_or_write_game(self):
        """A corrupt profile or cancelled request must fail before force-stop or mutation."""
        transport, _, _ = self.make_transport()
        bad = profile();bad['db_sha256'] = '0' * 64
        with self.assertRaises(AccountError):transport.restart(threading.Event(), bad)
        cancel = threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):transport.restart(cancel, profile())
        transport.run.assert_not_called();transport._write.assert_not_called()

    def test_wal_applies_only_valid_committed_frames_and_rejects_bad_header(self):
        """A real SQLite WAL with a stale appended tail must reproduce the committed database only."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sdk.db'
            db = sqlite3.connect(path)
            db.execute('pragma journal_mode=wal')
            db.execute('create table example(value text)');db.commit()
            db.execute('insert into example values(?)', ('committed',));db.commit()
            base = path.read_bytes();wal = path.with_name('sdk.db-wal').read_bytes()
            merged = merge_wal(base, wal + b'partial')
            copy_db = sqlite3.connect(':memory:');copy_db.deserialize(merged)
            self.assertEqual(copy_db.execute('select value from example').fetchone()[0], 'committed')
            copy_db.close()
            broken = bytearray(wal);broken[24] ^= 1
            with self.assertRaises(AccountError):merge_wal(base, bytes(broken))
            db.close()


class StartupPauseTests(unittest.TestCase):
    """Only one unambiguous persisted startup-off flag may bypass the old client bridge."""
    def test_persisted_pause_requires_one_exact_enabled_marker(self):
        """Missing, duplicate, enabled-auto-login or truncated values cannot authorize the restart shortcut."""
        transport=AccountTransport()
        cases=[(b'prefixmNoAutoLogin\x10\x01suffix',True),(b'mNoAutoLogin\x10\x00',False),
               (b'mNoAutoLogin\x10',False),(b'other-setting',False),
               (b'mNoAutoLogin\x10\x01mNoAutoLogin\x10\x01',False)]
        for data,expected in cases:
            with self.subTest(data=data),patch.object(transport,'read',return_value=data):
                self.assertIs(transport.startup_auto_paused(),expected)


class AccountLoginTests(unittest.TestCase):
    """Authentication observation must respect agreement, identity and cancellation without resending."""

    def setUp(self):
        self.service = AccountService(Mock(), Mock())
        self.connection = Mock()
        self.cancel = threading.Event()

    def test_waiting_for_user_agreement_cannot_accept_or_authenticate(self):
        """Polling the local checkbox is allowed; no setter, QR or login call is submitted while unchecked."""
        self.connection.login_call.return_value = dict(stage='LoginStage', logged_in=False, agreement=False)
        with patch.object(self.cancel, 'wait', side_effect=lambda n: self.cancel.set()):
            with self.assertRaises(InterruptedError):self.service._agreement(self.connection, self.cancel, Mock())
        self.connection.script.exports_sync.query.assert_not_called()

    def test_persisted_pause_can_restart_without_attaching_to_broken_old_realm(self):
        """An already persisted no-auto-login setting permits restart before connecting to the new process only."""
        self.service.transport.startup_auto_paused.return_value=True
        self.service._finish_login=Mock(return_value=('logged','saved'))
        self.service.call=Mock(return_value='1')
        connections=[]
        @contextmanager
        def bridge(cancel):
            """Count bridge acquisition without touching a live client or SDK files."""
            connections.append(True);yield self.connection
        self.service.connection=bridge
        result=self.service._login(self.cancel,Mock(),None,(1,0))
        self.assertEqual(result,('logged','saved'))
        self.assertEqual(len(connections),1)
        self.service.transport.restart.assert_called_once_with(self.cancel,None)
        self.service.call.assert_not_called()
        self.assertEqual(self.service._finish_login.call_args.args[-1],1)

    def test_startup_bridge_can_be_recreated_before_any_authentication(self):
        """Libraries can appear before the emulated Lua bridge is ready; retry only this local initialization."""
        first,second=Mock(),Mock()
        first.attach.side_effect=frida.RPCException('unable to find method query')
        self.service.call=Mock(return_value='ready')
        with patch('account_service.Connection',side_effect=[first,second]),patch.object(self.cancel,'wait'):
            with self.service.connection(self.cancel) as actual:
                self.assertIs(actual,second)
        first.close.assert_called_once()
        second.close.assert_called_once()
        self.assertEqual([c.args[1] for c in self.service.call.call_args_list],['ready'])

    def test_expired_observation_stops_without_another_login_request(self):
        """A missing SDK ticket persists for five seconds and is then reported as scan-required."""
        self.connection.login_call.return_value = dict(logged_in=False)
        self.service.call = Mock(return_value=dict(has_token=False, sdk_platform=0))
        with patch('account_service.time.monotonic', side_effect=[0, 1, 1, 2, 7, 7]), patch.object(self.cancel, 'wait'):
            with self.assertRaises(TicketExpired):
                self.service._authenticated(self.connection, self.cancel, Mock(), profile(), 1, 0)
        self.assertTrue(all(c.args[1] == 'watch' for c in self.service.call.call_args_list))

    def test_same_nickname_is_not_sufficient_to_accept_another_account(self):
        """Successful server response with the wrong SDK identity must never start a new worker."""
        self.connection.login_call.return_value = profile()['role']
        self.service.identity = Mock(return_value=dict(server_matches=True, openid='other', zone=1))
        with self.assertRaisesRegex(AccountError, '账号或平台'):
            self.service._authenticated(self.connection, self.cancel, Mock(), profile(), 1, 0)

    def test_success_accepts_updated_level_and_name_for_same_stable_role(self):
        """Progress or renaming does not force unnecessary QR scans when stable server identity still matches."""
        role = dict(profile()['role'], level=18, nickname_hex='更名'.encode().hex())
        self.connection.login_call.return_value = role
        self.service.identity = Mock(return_value=dict(server_matches=True, openid='alice', zone=1))
        self.assertEqual(self.service._authenticated(self.connection, self.cancel, Mock(), profile(), 1, 0), role)

    def test_snapshot_prunes_other_accounts_without_modifying_live_sdk_database(self):
        """The stored profile must contain only the authenticated identity even when SDK history has several records."""
        live = sdk_db(qq=('qq-other',), wx=('alice', 'wx-other'))
        self.service.transport.snapshot_database.return_value = live
        self.service.transport.read.return_value = ('<map>' + ''.join(profile()['auth_preferences']) + '</map>').encode()
        self.connection.login_call.return_value = profile()['role']
        self.service.identity = Mock(return_value=dict(server_matches=True, openid='alice', token=b'fake-access',
                                                       sdk_platform=1, zone=1, auto_login=0))
        saved = self.service.capture(self.connection)
        validate_profile(saved)
        db = sqlite3.connect(':memory:');db.deserialize(live)
        self.assertEqual(db.execute('select count(*) from wx_login_info').fetchone()[0], 2)
        self.assertEqual(db.execute('select count(*) from qq_login_info').fetchone()[0], 1)
        db.close()

    def test_refusal_marks_profile_without_retrying_or_overwriting_ticket(self):
        """A rejected native authentication keeps the old saved profile and marks it for a deliberate scan."""
        self.service.store.load.return_value = profile()
        self.service.call = Mock(side_effect=['0', 'true'])
        self.service.identity = Mock(return_value=dict(openid='alice', sdk_platform=1, token=b'fake-access'))
        self.service._agreement = Mock()
        self.service._authenticated = Mock(side_effect=TicketExpired('请重新扫码'))

        @contextmanager
        def bridge(cancel):
            """Supply one isolated bridge for the pre-restart pause and the new process authentication."""
            yield self.connection
        self.service.connection = bridge
        with self.assertRaises(TicketExpired):
            self.service.login(self.cancel, Mock(), profile_id='a' * 64)
        self.service.store.mark_scan_required.assert_called_once_with('a' * 64)
        self.service.store.save.assert_not_called()
        self.assertEqual([c.args[1] for c in self.service.call.call_args_list], ['pause', 'restore', 'cancel_auth'])

    def test_known_expired_profile_does_not_repeat_restart_or_authentication(self):
        """Once scan-required is recorded, selecting that profile cannot silently retry its old credentials."""
        self.service.store.load.return_value = dict(profile(), ticket_status='需要重新扫码')
        self.service.connection = Mock()
        with self.assertRaises(TicketExpired):
            self.service.login(self.cancel, Mock(), profile_id='a' * 64)
        self.service.connection.assert_not_called()
        self.service.transport.restart.assert_not_called()

    def test_qr_restores_startup_preference_only_after_server_identity_confirmation(self):
        """Exercise the service boundary that must not resume native startup login while QR is pending."""
        order=[]
        self.service._agreement=Mock()
        self.service.call=Mock(side_effect=lambda c,op,*args:order.append(op))
        self.service._authenticated=Mock(side_effect=lambda *args:order.append('confirmed') or profile()['role'])
        self.service.capture=Mock(return_value=profile())
        self.service._finish_login(self.connection,self.cancel,Mock(),None,0,1,0)
        self.assertEqual(order,['qr','confirmed','resume'])
        self.service.store.save.assert_called_once()

    def test_failed_qr_stops_native_auth_without_erasing_or_marking_saved_profiles(self):
        """A scan failure cannot leave native reconnect active or invalidate a different saved ticket."""
        self.service.call=Mock(return_value='0')
        self.service._finish_login=Mock(side_effect=AccountError('扫码失败'))
        @contextmanager
        def bridge(cancel):
            """Yield the same mocked bridge across the restart boundary."""
            yield self.connection
        self.service.connection=bridge
        with self.assertRaises(AccountError):
            self.service.login(self.cancel,Mock(),qr_context=(0,1))
        self.assertEqual([c.args[1] for c in self.service.call.call_args_list],['pause','cancel_auth'])
        self.service.store.save.assert_not_called()
        self.service.store.mark_scan_required.assert_not_called()


class AccountNativeTests(unittest.TestCase):
    """Use the actual Lua account adapter to check native platform selection and one-shot authorization."""

    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
Game={agreement=true,auto=1,mobile=0,cloud=false,auth=0,qr=0,stage='LoginStage',logged=false}
Game.sdk={platform=1,flag=0,open_id='private-id',GetAccessToken=function()return 'private-token'end}
local setting={getGlobalSettingInt=function()return Game.auto end,setGlobalSettingInt=function(self,k,v)Game.auto=v end,
 getLicenseAcceptance=function()return Game.agreement end,getLicensePrivacyAcceptance=function()return true end}
local apollo={getAccountInfo=function()return Game.sdk end,canAutoLogin=function()Game.auth=Game.auth+1;return true end}
local tickets={setCloudMatrixIos=function(self,b)Game.cloud=b end,
 getLoginInfo=function()return {isLogined=function()return Game.logged end}end}
local T_TYPE={E_MOBILE_PLAT_TYPE_IOS=1}
local function setPlatformInfoForCloudMatrix(self,value)Game.mobile=value end
local d={onBtnIosWechatClicked=function()setPlatformInfoForCloudMatrix({},T_TYPE.E_MOBILE_PLAT_TYPE_IOS);Game.qr=Game.qr+1 end}
for _,k in ipairs({'onBtnAndroidWechatClicked','onBtnAndroidQQClicked','onBtnIosQQClicked'})do d[k]=function()Game.qr=Game.qr+1 end end
package.loaded.LoginCloudMatrix={__instanceDict=d}
package.loaded.LoginPanel={__instanceDict={getCurrentStageName=function()return Game.stage end}}
package.loaded.TicketsProtocol={__instanceDict={_instance=tickets}}
CSLTypes={Setting={sharedInstance=function()return setting end},ApolloLoginController={getInstance=function()return apollo end},
 LoginManager={sharedInstance=function()return {loginOut=function(self,toPage,sdkLogout)Game.stopped=true;Game.sdkLogout=sdkLogout end}end},
 TicketsProtocol={getInstance=function()return tickets end},MainModel='main',ModelManager={sharedInstance=function()return {getModel=function()return {myUserId={1,'private-id',0,1},mTLoginRsp=Game.response}end}end},
 QQGameSystem={getSystemInstance=function()return {getCurZoneID=function()return 1 end}end}}
''')
        self.source = Path(__file__).with_name('account_runtime.lua').read_text(encoding='utf-8')

    def operation(self, name, mobile=1, platform=0):
        """Run one fixed native operation in an isolated Lua environment; no real SDK or server is present."""
        prefix = f'local operation={json.dumps(name)};local mobile={mobile};local open_platform={platform};local resume_auto=0;'
        return self.lua.execute(prefix + self.source)

    def test_android_and_ios_choose_correct_native_context_and_authorize_once(self):
        """Restoring Android after iOS must explicitly clear the cloud-iOS flag, with no QR callback."""
        self.assertEqual(self.operation('restore'), 'true')
        self.assertEqual(self.lua.globals().Game.mobile, 1)
        self.assertTrue(self.lua.globals().Game.cloud)
        self.assertEqual(self.lua.globals().Game.qr, 0)
        with self.assertRaises(Exception):self.operation('restore')
        self.assertEqual(self.lua.globals().Game.auth, 1)
        self.lua.execute('REA_ACCOUNT_AUTH_ATTEMPT=nil;Game.sdk.platform=2')
        self.operation('restore', 0, 1)
        self.assertEqual(self.lua.globals().Game.mobile, 0)
        self.assertFalse(self.lua.globals().Game.cloud)
        self.assertEqual(self.lua.globals().Game.auto, 0)

    def test_agreement_and_sdk_platform_are_checked_before_native_login(self):
        """No stored ticket can authorize accepting an unchecked agreement or logging into the wrong SDK provider."""
        self.lua.execute('Game.agreement=false')
        with self.assertRaises(Exception):self.operation('restore')
        self.lua.execute('Game.agreement=true;Game.sdk.platform=2')
        with self.assertRaises(Exception):self.operation('restore')
        self.assertEqual(self.lua.globals().Game.auth, 0)

    def test_watch_has_no_credential_values_and_scan_uses_one_explicit_native_entry(self):
        """Public authentication observations must never include IDs/tokens; QR is a separately requested operation."""
        watch = self.operation('watch')
        self.assertNotIn('private-id', watch);self.assertNotIn('private-token', watch)
        self.assertEqual(self.operation('qr'), 'qr_requested')
        self.assertEqual(self.lua.globals().Game.qr, 1)
        with self.assertRaises(Exception):self.operation('qr')
        self.assertEqual(self.lua.globals().Game.qr, 1)

    def test_expired_cleanup_stops_native_reconnect_without_sdk_logout(self):
        """Ending a failed attempt must not revoke separately saved valid SDK authorizations."""
        self.assertEqual(self.operation('cancel_auth'), 'authentication_stopped')
        self.assertTrue(self.lua.globals().Game.stopped)
        self.assertFalse(self.lua.globals().Game.sdkLogout)
        self.assertEqual(self.lua.globals().Game.auto, 1)

    def test_qr_keeps_startup_login_paused_until_server_confirms_role(self):
        """Replay the failing QR ordering: native startup must stay paused throughout the authorization wait."""
        self.operation('qr', 0, 1)
        self.assertEqual(self.lua.globals().Game.auto, 1)
        with self.assertRaises(Exception):
            self.operation('resume')
        self.assertEqual(self.lua.globals().Game.auto, 1)
        self.lua.execute("Game.stage='MainHallSceneStage';Game.logged=true;Game.response={0}")
        self.assertEqual(self.operation('resume'), 'startup_preference_restored')
        self.assertEqual(self.lua.globals().Game.auto, 0)


class AccountSessionTests(unittest.TestCase):
    """Serialize account replacement, prevent old workers from surviving, and never resume automatic spending."""

    def test_restored_role_creates_a_new_worker_with_scheduled_hunting_disarmed(self):
        """A successful account switch reconstructs services rather than re-enabling an old account's feature state."""
        owner = LoginSession(Mock());owner.store = Mock();owner.store.list.return_value = []
        owner.accounts = Mock();owner.accounts.login.return_value = (profile()['role'], dict(name='旅行'))
        old = Mock();old.is_alive.return_value = False
        worker = Mock()
        with patch('login_session.ensure_server'), patch('login_session.Worker', return_value=worker):
            owner._replace('account_switch', 0, threading.Event(), old, None, 'a' * 64)
        old.stop.assert_called_once();old.join.assert_called_once()
        self.assertFalse(worker.allow_scheduled_hunt)
        worker.start.assert_called_once()
        owner.accounts.login.assert_called_once()

    def test_failed_authentication_does_not_create_a_worker_or_retry(self):
        """Expired credentials leave all controls closed and make the scan instruction visible."""
        owner = LoginSession(Mock());owner.store = Mock();owner.store.list.return_value = []
        owner.accounts = Mock();owner.accounts.login.side_effect = TicketExpired('请重新扫码')
        with patch('login_session.ensure_server'), patch('login_session.Worker') as factory:
            owner._replace('account_switch', 0, threading.Event(), None, None, 'a' * 64)
        factory.assert_not_called();owner.accounts.login.assert_called_once()
        events = [call.args[0] for call in owner.events.put.call_args_list]
        self.assertTrue(any('重新扫码' in event.get('status', '') for event in events))

    def test_cross_thread_owner_is_blocked_even_when_no_game_bridge_is_attached(self):
        """The SDK file-writing interval must remain exclusive after its temporary Frida bridge is detached."""
        outcomes = []
        def competitor():
            """Attempt a second helper connection while the first owns the full account transaction."""
            try:
                ensure_account_available()
                outcomes.append('allowed')
            except RuntimeError:
                outcomes.append('blocked')
        with account_operation():
            ensure_account_available()
            thread = threading.Thread(target=competitor)
            thread.start();thread.join(timeout=3)
            self.assertEqual(outcomes, ['blocked'])
        ensure_account_available()


class AccountDialogTests(unittest.TestCase):
    """Use real Tk widgets while all background work and game operations are mocked."""

    def test_rows_show_only_role_metadata_and_controls_use_selected_profile(self):
        """Saving/switching are explicit actions; merely opening the list never invokes native login."""
        loader = SourceFileLoader('account_dialog_app_test', str(Path(__file__).with_name('app.pyw')))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec);loader.exec_module(module)
        with patch.object(module.threading, 'Thread'):
            app = module.App()
        try:
            app.root.withdraw();app.login_busy = False
            app.sessions.store = Mock()
            row = dict(profile_id='a' * 64, name='旅行', level=17, mobile='iOS', platform='微信',
                       open_platform=0, mobile_platform=1, status='已保存，切换时验证', updated=0)
            app.sessions.store.list.return_value = [row]
            app.request_session = Mock()
            app.open_accounts();dialog = app.accounts_dialog;dialog.withdraw()
            self.assertEqual(dialog.tree.item('a' * 64)['values'][:4], ['旅行', 17, 'iOS', '微信'])
            app.request_session.assert_not_called()
            dialog.tree.selection_set('a' * 64);dialog.select()
            self.assertEqual(dialog.platform.get(), 'iOS 微信')
            dialog.switch();app.request_session.assert_called_with('account_switch', 'a' * 64)
            dialog.scan();app.request_session.assert_called_with('account_qr', (1, 0))
            with patch('account_dialog.messagebox.askyesno',return_value=False) as confirm:
                dialog.delete()
            app.sessions.store.delete.assert_not_called()
            self.assertEqual(confirm.call_args.kwargs['default'],'no')
            with patch('account_dialog.messagebox.askyesno',return_value=True):
                dialog.delete()
            app.sessions.store.delete.assert_called_once_with('a'*64)
            app.login_busy = True;dialog.update_controls()
            self.assertIn('disabled', dialog.switch_button.state())
            self.assertIn('disabled', dialog.save_button.state())
            self.assertIn('disabled', dialog.delete_button.state())
            dialog.delete()
            app.sessions.store.delete.assert_called_once()
            self.assertFalse(any(v.get() for v in (app.enabled, app.hero_enabled, app.collect_enabled,
                                                  app.hunt_enabled, app.league_enabled, app.beacon_enabled)))
        finally:
            app.close()

    def test_window_close_waits_for_file_transaction_before_destroying_tk(self):
        """Closing the window cannot kill its daemon thread midway through SDK preference/database replacement."""
        loader = SourceFileLoader('account_shutdown_app_test', str(Path(__file__).with_name('app.pyw')))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec);loader.exec_module(module)
        app = module.App.__new__(module.App)
        app.root = Mock();app.status = Mock();app.sessions = Mock()
        app.battle_chat = Mock();app.battle_chat.pending_shutdown.return_value=False
        app.hall_profile = Mock();app.hall_profile.pending_shutdown.return_value=False
        app.sessions.pending_shutdown.side_effect = [True, False]
        app.finish_close()
        app.root.destroy.assert_not_called()
        app.root.after.assert_called_once_with(100, app.finish_close)
        app.finish_close()
        app.root.destroy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
