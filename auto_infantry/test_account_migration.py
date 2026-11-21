"""Portable encryption, independent machine stores, atomic failure handling and default-off UI/session tests."""
from contextlib import nullcontext
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from account_migration import (encrypt_archive, decrypt_archive, export_accounts, import_accounts,
                               MAGIC, HEADER_SIZE, MAX_FILE, validate_batch, archive_requires_password)
from account_store import AccountStore, AccountError, profile_key, crypt_profile
from account_dialog import AccountDialog
from login_session import LoginSession
from test_account_profiles import profile

PASSWORD = 'synthetic-passphrase-2026'


def machine_cipher(machine):
    """Simulate mutually incompatible DPAPI machines using fake credentials, without real account files."""
    def cipher(data, decrypt=False):
        """Reject another machine's envelope so a transfer must re-encrypt rather than copy ciphertext."""
        if decrypt:
            if not data.startswith(machine):
                raise AccountError('不同机器无法解密')
            return data[len(machine):][::-1]
        return machine + data[::-1]
    return cipher


class AccountMigrationTests(unittest.TestCase):
    """Use real authenticated encryption around synthetic SQLite profiles and isolated account stores."""

    def setUp(self):
        """Give each case a separate source, destination and fake cross-process lock."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = AccountStore(self.root/'work', machine_cipher(b'WORK:'))
        self.target = AccountStore(self.root/'home', machine_cipher(b'HOME:'))
        self.path = self.root/'transfer.yxsaccounts'
        self.lock = patch('account_lock.account_operation', side_effect=lambda: nullcontext())
        self.lock.start()
        self.addCleanup(self.lock.stop)

    def test_round_trip_multiple_platforms_reencrypts_and_preserves_expired_status(self):
        """Move Android QQ and iOS WeChat to a different machine cipher with unverified or expired status."""
        ios = self.source.save(profile(name='ios-wechat'), '最近登录成功')
        android = self.source.save(profile(mobile=0, platform=1, name='android-qq'), '需要重新扫码')
        self.assertEqual(export_accounts(self.source, [ios['profile_id'], android['profile_id']], self.path, PASSWORD), {'exported': 2})
        blob = self.path.read_bytes()
        self.assertNotIn(b'ios-wechat', blob)
        self.assertNotIn('旅行'.encode(), blob)
        self.assertNotIn(b'opaque-sdk-cipher', blob)
        self.assertNotIn(PASSWORD.encode(), blob)
        result = import_accounts(self.target, self.path, PASSWORD)
        self.assertEqual(result, {'imported': 2, 'skipped': 0})
        for row in (ios, android):
            key = row['profile_id']
            original = self.source.load(key)
            moved = self.target.load(key)
            self.assertEqual(moved['database'], original['database'])
            self.assertEqual(moved['auth_preferences'], original['auth_preferences'])
            self.assertEqual(moved['role'], original['role'])
            self.assertTrue(self.target._path(key).read_bytes().startswith(b'HOME:'))
            self.assertNotEqual(self.source._path(key).read_bytes(), self.target._path(key).read_bytes())
            with self.assertRaises(AccountError):
                self.target.cipher(self.source._path(key).read_bytes(), True)
        self.assertEqual(self.target.load(ios['profile_id'])['ticket_status'], '已保存，切换时验证')
        self.assertEqual(self.target.load(android['profile_id'])['ticket_status'], '需要重新扫码')
        self.assertFalse(list(self.target.directory.glob('.import-*')))

    def test_plaintext_round_trip_needs_no_password_or_crypto(self):
        """The default exported JSON imports on a second machine without loading the legacy password cipher."""
        a = self.source.save(profile(name='plain-one'))
        b = self.source.save(profile(name='plain-two'), '需要重新扫码')
        original = self.source._path(a['profile_id']).read_bytes()
        with patch('account_migration.crypto') as crypto:
            export_accounts(self.source, [a['profile_id'], b['profile_id']], self.path)
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self.assertEqual(value['format'], 2)
            self.assertEqual(len(value['profiles']), 2)
            self.assertFalse(archive_requires_password(self.path))
            self.assertEqual(import_accounts(self.target, self.path), {'imported': 2, 'skipped': 0})
            before = self.target._path(a['profile_id']).read_bytes()
            self.assertEqual(import_accounts(self.target, self.path), {'imported': 0, 'skipped': 2})
            crypto.assert_not_called()
        self.assertEqual(self.source._path(a['profile_id']).read_bytes(), original)
        self.assertEqual(self.target._path(a['profile_id']).read_bytes(), before)
        self.assertEqual(self.target.load(a['profile_id'])['database'], self.source.load(a['profile_id'])['database'])
        self.assertEqual(self.target.load(b['profile_id'])['ticket_status'], '需要重新扫码')

    def test_plaintext_invalid_batch_never_partially_imports(self):
        """Reject malformed JSON, wrong format and an invalid second account before publishing any profile."""
        for blob in (b'{', b'\xff', b'[]', b'{"format":true,"profiles":[]}',
                     json.dumps({'format':2,'profiles':[profile(),{}]}).encode()):
            self.path.write_bytes(blob)
            with self.assertRaises(AccountError):
                import_accounts(self.target,self.path)
            self.assertFalse(self.target.directory.exists())

    def test_plaintext_export_failure_preserves_previous_archive(self):
        """An interrupted write cannot replace an older archive or leave its temporary export file."""
        key = self.source.save(profile())['profile_id']
        self.path.write_bytes(b'old archive')
        with patch('account_migration.os.fsync', side_effect=OSError('write failed')):
            with self.assertRaises(AccountError):
                export_accounts(self.source,[key],self.path)
        self.assertEqual(self.path.read_bytes(),b'old archive')
        self.assertFalse(list(self.root.glob('.yxs-export-*')))

    def test_export_selects_only_requested_accounts_and_is_randomized(self):
        """An archive contains only selected identities and repeated exports never reuse salt/nonce bytes."""
        a = self.source.save(profile(name='selected'))
        self.source.save(profile(name='not-selected'))
        export_accounts(self.source, [a['profile_id']], self.path, PASSWORD)
        first = self.path.read_bytes()
        self.assertEqual([p['openid'] for p in decrypt_archive(first, PASSWORD)], ['selected'])
        export_accounts(self.source, [a['profile_id']], self.path, PASSWORD)
        self.assertNotEqual(first[:HEADER_SIZE], self.path.read_bytes()[:HEADER_SIZE])

    def test_bad_password_and_tampering_cannot_write_profiles(self):
        """Wrong keys, salt, nonce and ciphertext edits fail authentication before the destination store is touched."""
        blob = encrypt_archive([profile()], PASSWORD)
        for bad in (PASSWORD+'wrong',):
            self.path.write_bytes(blob)
            with self.assertRaisesRegex(AccountError, '密码错误或迁移文件已损坏'):
                import_accounts(self.target, self.path, bad)
        for index in (len(MAGIC), HEADER_SIZE-1, HEADER_SIZE, len(blob)-1):
            altered = bytearray(blob)
            altered[index] ^= 1
            self.path.write_bytes(altered)
            with self.assertRaises(AccountError):
                import_accounts(self.target, self.path, PASSWORD)
        self.assertFalse(self.target.directory.exists())

    def test_format_and_batch_bounds_are_checked_before_key_derivation(self):
        """Reject unknown formats, short passwords and oversized files without invoking expensive cryptography."""
        with patch('account_migration.crypto') as crypto:
            for blob in (b'', b'wrong-format'+b'x'*80, MAGIC+b'x'*(MAX_FILE+1)):
                with self.assertRaises(AccountError):
                    decrypt_archive(blob, PASSWORD)
            with self.assertRaises(AccountError):
                encrypt_archive([profile()], 'short')
            crypto.assert_not_called()
        for values in ([], [profile()]*51, [profile(), profile()], [profile(), {}]):
            with self.assertRaises(AccountError):
                validate_batch(values)

    def test_duplicate_import_skips_without_overwriting_current_ticket(self):
        """A portable backup never silently replaces a newer local record, including its expired marker."""
        value = profile(name='already-here')
        key = self.target.save(value, '需要重新扫码')['profile_id']
        before = self.target._path(key).read_bytes()
        self.path.write_bytes(encrypt_archive([value], PASSWORD))
        self.assertEqual(import_accounts(self.target, self.path, PASSWORD), {'imported': 0, 'skipped': 1})
        self.assertEqual(self.target._path(key).read_bytes(), before)

    def test_invalid_second_profile_and_cipher_failure_leave_no_partial_import(self):
        """Validate and locally encrypt the entire batch before publishing any new account filename."""
        values = [profile(name='one'), profile(name='two')]
        with self.assertRaises(AccountError):
            self.target.import_profiles([values[0], {}])
        with patch('account_migration.validate_batch'):
            self.path.write_bytes(encrypt_archive([values[0], {}], PASSWORD))
        with self.assertRaises(AccountError):
            import_accounts(self.target, self.path, PASSWORD)
        self.assertFalse(self.target.directory.exists())
        good = self.target.cipher
        def fail_second(data, decrypt=False):
            """Fail local encryption on the second identity while allowing readback of the first staged file."""
            if not decrypt and json.loads(data)['openid'] == 'two':
                raise AccountError('synthetic encryption failure')
            return good(data, decrypt)
        self.target.cipher = fail_second
        with self.assertRaises(AccountError):
            self.target.import_profiles(values)
        self.assertEqual(self.target.list(), [])
        self.assertFalse(list(self.target.directory.glob('.import-*')))

    def test_second_commit_failure_rolls_back_only_new_accounts(self):
        """A filesystem failure during batch publication restores the pre-import account set byte for byte."""
        existing = self.target.save(profile(name='kept'))
        original = self.target._path(existing['profile_id']).read_bytes()
        import os
        real_link = os.link
        calls = []
        def fail_second(source, destination):
            """Publish the first new identity and simulate a denied second commit."""
            calls.append(destination)
            if len(calls) == 2:
                raise OSError('synthetic failure')
            return real_link(source, destination)
        with patch('account_store.os.link', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.target.import_profiles([profile(name='one'), profile(name='two')])
        self.assertEqual(len(self.target.list()), 1)
        self.assertEqual(self.target._path(existing['profile_id']).read_bytes(), original)

    def test_cancel_and_export_failure_keep_existing_files(self):
        """Cancelled or failed export cannot replace a previous archive or leave a plaintext temporary file."""
        key = self.source.save(profile())['profile_id']
        self.path.write_bytes(b'previous ciphertext')
        cancelled = threading.Event();cancelled.set()
        with self.assertRaises(InterruptedError):
            export_accounts(self.source, [key], self.path, PASSWORD, cancelled)
        with patch('account_migration.os.fsync', side_effect=OSError('synthetic failure')):
            with self.assertRaises(AccountError):
                export_accounts(self.source, [key], self.path, PASSWORD)
        self.assertEqual(self.path.read_bytes(), b'previous ciphertext')
        self.assertFalse(list(self.root.glob('.yxs-export-*')))
        with self.assertRaises(AccountError):
            export_accounts(self.source, [key], self.source._path(key), PASSWORD)
        with self.assertRaises(AccountError):
            export_accounts(self.source, [key], self.root/'credentials.txt', PASSWORD)
        self.assertFalse((self.root/'credentials.txt').exists())

    def test_import_uses_real_local_dpapi_without_plaintext_files(self):
        """Verify the actual Windows cipher on synthetic tickets; no genuine accounts are opened or migrated."""
        value = profile(name='synthetic-dpapi-migration')
        store = AccountStore(self.root/'dpapi', crypt_profile)
        store.import_profiles([value])
        blob = store._path(profile_key(value)).read_bytes()
        self.assertNotIn(value['openid'].encode(), blob)
        self.assertEqual(store.load(profile_key(value))['openid'], value['openid'])


class MigrationSessionTests(unittest.TestCase):
    """Migration is a local stopped-worker job with no native connection or automatic replacement worker."""

    def test_import_and_export_never_connect_or_login_and_return_only_public_counts(self):
        """Both flows stop the existing worker and publish no password, identity or ticket contents."""
        for mode, selection, result in (
            ('account_import', ('fake.yxsaccounts',), {'imported': 2, 'skipped': 1}),
            ('account_export', (('a'*64,), 'fake.yxsaccounts'), {'exported': 1}),
            ('account_import', ('fake.yxsaccounts', PASSWORD), {'imported': 2, 'skipped': 1}),
            ('account_export', (('a'*64,), 'fake.yxsaccounts', PASSWORD), {'exported': 1}),
        ):
            events = queue.Queue();session = LoginSession(events);session.epoch = 1
            session.store = Mock();session.store.list.return_value = []
            previous = Mock();previous.is_alive.return_value = False
            with patch('account_migration.import_accounts', return_value=result) as imp, \
                 patch('account_migration.export_accounts', return_value=result) as exp, \
                 patch('login_session.ensure_server') as server, patch('login_session.Worker') as worker, \
                 patch('login_session.Connection') as connection:
                session._replace(mode, 1, threading.Event(), previous, None, selection)
            previous.stop.assert_called_once();previous.join.assert_called_once()
            server.assert_not_called();worker.assert_not_called();connection.assert_not_called()
            self.assertIsNone(session.worker)
            captured = list(events.queue)
            self.assertIn({'login_busy': False, 'session_epoch': 1}, captured)
            self.assertNotIn(PASSWORD, str(captured))
            self.assertTrue(any('自动功能全部关闭' in event.get('account_status', '') for event in captured))
            (imp if mode=='account_import' else exp).assert_called_once()

    def test_migration_request_turns_off_every_live_master_before_starting_the_job(self):
        """Exercise the real App entrypoint with active switches; no game worker thread is started in this test."""
        loader = SourceFileLoader('migration_default_off_app_test', str(Path(__file__).with_name('app.pyw')))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec);loader.exec_module(module)
        with patch.object(module.threading, 'Thread'):
            app = module.App()
        try:
            app.root.withdraw()
            masters = (app.enabled, app.hero_enabled, app.collect_enabled, app.hunt_enabled,
                       app.league_enabled, app.beacon_enabled, app.training_speed, app.trial_enabled, app.report_enabled)
            for master in masters:
                master.set(True)
            def observe_request(*args):
                """Check the gates at the exact point the asynchronous import would be queued."""
                self.assertFalse(any(master.get() for master in masters))
            app.sessions.request = Mock(side_effect=observe_request)
            app.request_session('account_import', ('fake.yxsaccounts', PASSWORD))
            self.assertTrue(app.login_busy)
            app.sessions.request.assert_called_once_with('account_import', ('fake.yxsaccounts', PASSWORD))
            self.assertNotIn(PASSWORD, app.status.get())
        finally:
            app.close()


class MigrationDialogTests(unittest.TestCase):
    """Exercise real hidden Tk selection and masked password prompts with entirely fake public records."""

    def setUp(self):
        """Avoid App startup and its worker so GUI tests cannot access a live emulator."""
        self.root = tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.rows = [dict(profile_id=c*64, name='测试'+c, level=17, mobile='iOS', platform='微信',
            open_platform=0, mobile_platform=1, status='已保存，切换时验证', updated=0) for c in ('a','b')]
        self.app = SimpleNamespace(root=self.root, login_busy=False, closing=False, status=tk.StringVar(self.root),
            sessions=SimpleNamespace(store=Mock()), request_session=Mock())
        self.app.sessions.store.list.return_value=self.rows
        self.dialog=AccountDialog(self.app);self.dialog.withdraw()

    def test_multi_selection_exports_only_selected_keys_and_switch_is_single(self):
        """Selecting multiple accounts enables export but cannot switch or delete an arbitrary first account."""
        self.dialog.tree.selection_set(('a'*64,'b'*64));self.dialog.update_controls()
        self.assertNotIn('disabled', self.dialog.export_button.state())
        self.assertIn('disabled', self.dialog.switch_button.state())
        self.assertIn('disabled', self.dialog.delete_button.state())
        self.dialog.switch();self.app.request_session.assert_not_called()
        with patch('account_dialog.filedialog.asksaveasfilename', return_value='fake.yxsaccounts'), \
             patch('account_dialog.simpledialog.askstring', side_effect=[PASSWORD,PASSWORD]) as prompts:
            self.dialog.export_selected()
        self.app.request_session.assert_called_once_with('account_export', (('a'*64,'b'*64),'fake.yxsaccounts'))
        prompts.assert_not_called()
        self.dialog.refresh(self.rows)
        self.assertEqual(len(self.dialog.tree.selection()),2)

    def test_plaintext_import_has_no_password_prompt_and_respects_busy_state(self):
        """New JSON imports directly while cancellation and busy controls cannot queue work."""
        with patch('account_dialog.filedialog.askopenfilename',return_value='fake.yxsaccounts'), \
             patch('account_dialog.archive_requires_password',return_value=False), \
             patch('account_dialog.simpledialog.askstring') as prompts:
            self.dialog.import_archive()
        self.app.request_session.assert_called_once_with('account_import', ('fake.yxsaccounts',))
        prompts.assert_not_called()
        self.app.request_session.reset_mock()
        self.dialog.tree.selection_set('a'*64)
        with patch('account_dialog.filedialog.asksaveasfilename',return_value=''):
            self.dialog.export_selected()
        self.app.request_session.assert_not_called()

    def test_legacy_import_only_prompts_for_original_masked_password(self):
        """Existing encrypted files stay importable and password cancellation queues no import."""
        with patch('account_dialog.filedialog.askopenfilename',return_value='old.yxsaccounts'), \
             patch('account_dialog.archive_requires_password',return_value=True), \
             patch('account_dialog.simpledialog.askstring',return_value=PASSWORD) as prompts:
            self.dialog.import_archive()
        self.app.request_session.assert_called_once_with('account_import', ('old.yxsaccounts', PASSWORD))
        self.assertEqual(prompts.call_args.kwargs['show'],'*')
        self.app.request_session.reset_mock()
        with patch('account_dialog.filedialog.askopenfilename',return_value='old.yxsaccounts'), \
             patch('account_dialog.archive_requires_password',return_value=True), \
             patch('account_dialog.simpledialog.askstring',return_value=None):
            self.dialog.import_archive()
        self.app.request_session.assert_not_called()
        self.app.login_busy=True;self.dialog.update_controls()
        self.dialog.import_archive()
        self.assertIn('disabled',self.dialog.import_button.state())
        self.assertIn('disabled',self.dialog.export_button.state())
        self.app.request_session.assert_not_called()


if __name__=='__main__':
    unittest.main()
