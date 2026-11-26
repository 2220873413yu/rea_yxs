"""Portable ticket export/import: plaintext only crosses PCs inside the migration file, never into the SDK."""
import base64
import copy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from account_migration import read_archive
from account_portable import (PLAIN_HASH, PLAIN_KEY, export_portable, needs_rekey,
                              portable_profile, rekey_profile, values_digest)
from account_rekey import FIELDS, QQ_FIELDS, cipher_fields, credential_columns
from account_service import AccountService
from account_store import AccountError, AccountStore, profile_key, validate_profile
from test_account_profiles import profile, test_cipher


def with_ticket_columns(value):
    """Give a synthetic snapshot the real encrypted-column shape of its own platform."""
    db = sqlite3.connect(':memory:')
    db.deserialize(validate_profile(value))
    table = 'qq_login_info' if value['role']['open_platform'] else 'wx_login_info'
    if value['role']['open_platform']:
        db.execute('alter table ' + table + ' add column pay_token text')
        db.execute("update " + table + " set pay_token='fake-pay-token'")
    db.execute('alter table ' + table + ' add column pf text')
    db.execute('alter table ' + table + ' add column pf_key text')
    db.execute('update ' + table + " set pf='fake-pf',pf_key='fake-key'")
    db.commit()
    data = db.serialize()
    db.close()
    return dict(value, database=base64.b64encode(data).decode(), db_sha256=hashlib.sha256(data).hexdigest())


def plain_block(fields):
    """Build the decoded base64 block one platform would carry, keyed by its own column names."""
    return {field: base64.b64encode(b'fake-access' if field == 'access_token'
                                    else ('fake-' + field).encode()).decode() for field in fields}


PLAIN = plain_block(FIELDS)
QQ_PLAIN = plain_block(QQ_FIELDS)
DESTINATION = {field: 'destination-sdk-' + field for field in FIELDS}
QQ_DESTINATION = {field: 'destination-sdk-' + field for field in QQ_FIELDS}


def source_transform(mode, values):
    """Emulate this PC's SDK cipher; both directions are exact so a wrong call cannot pass unnoticed."""
    return PLAIN if mode == 'decode' else DESTINATION


def qq_transform(mode, values):
    """Emulate the QQ variant, which carries a pay token instead of a refresh token."""
    return QQ_PLAIN if mode == 'decode' else QQ_DESTINATION


class PortableExportTests(unittest.TestCase):
    """Decoding must be bound to the saved token hash and must never mutate the stored profile."""

    def setUp(self):
        """Use one synthetic WeChat identity with opaque four-column ciphertext."""
        self.source = with_ticket_columns(profile())

    def test_export_carries_decoded_columns_and_keeps_source_intact(self):
        """The portable copy holds the plaintext ticket plus its digest, and the original stays untouched."""
        original = copy.deepcopy(self.source)
        result = portable_profile(self.source, source_transform)
        self.assertEqual(self.source, original)
        self.assertEqual(result[PLAIN_KEY], PLAIN)
        self.assertEqual(result[PLAIN_HASH], values_digest(PLAIN))
        self.assertEqual(result['sdk_access_token_sha256'], original['sdk_access_token_sha256'])
        self.assertTrue(needs_rekey(result))
        self.assertFalse(needs_rekey(self.source))

    def test_another_accounts_token_is_rejected(self):
        """A decode that yields a different access token never becomes a portable profile."""
        wrong = dict(PLAIN, access_token=base64.b64encode(b'other-access').decode())
        with self.assertRaisesRegex(AccountError, '不一致'):
            portable_profile(self.source, lambda mode, values: wrong)

    def test_empty_decoded_column_is_rejected(self):
        """An empty column would silently erase a credential on the destination, so export fails first."""
        empty = dict(PLAIN, refresh_token='')
        with self.assertRaisesRegex(AccountError, '不完整'):
            portable_profile(self.source, lambda mode, values: empty)


class PortableImportTests(unittest.TestCase):
    """The destination PC must re-encrypt with its own key, verify the round trip and drop the plaintext."""

    def setUp(self):
        """Start from the exact portable profile one PC would hand to another."""
        self.portable = portable_profile(with_ticket_columns(profile()), source_transform)

    def test_rekey_writes_destination_ciphertext_and_removes_plaintext(self):
        """All four columns become destination ciphertext and the plaintext block stops existing."""
        result = rekey_profile(self.portable, source_transform)
        self.assertNotIn(PLAIN_KEY, result)
        self.assertNotIn(PLAIN_HASH, result)
        self.assertEqual(credential_columns(result), DESTINATION)
        self.assertEqual(result['ticket_status'], '已保存，切换时验证')
        self.assertEqual(result['no_auto_login'], 1)
        self.assertEqual(result['sdk_access_token_sha256'], self.portable['sdk_access_token_sha256'])
        self.assertEqual(profile_key(result), profile_key(self.portable))
        validate_profile(result)

    def test_tampered_plaintext_block_is_rejected(self):
        """A hand-edited migration file cannot inject another token under a valid profile identity."""
        value = dict(self.portable)
        value[PLAIN_KEY] = dict(PLAIN, access_token=base64.b64encode(b'other-access').decode())
        with self.assertRaisesRegex(AccountError, '校验失败'):
            rekey_profile(value, source_transform)

    def test_destination_readback_mismatch_is_rejected(self):
        """An SDK that cannot decrypt what it just wrote must not produce a restorable profile."""
        def broken(mode, values):
            """Return unusable ciphertext for the encode direction only."""
            return DESTINATION if mode == 'encode' else dict(PLAIN, pf='other-pf')
        with self.assertRaisesRegex(AccountError, '回读不一致'):
            rekey_profile(self.portable, broken)


class PortableQQTests(unittest.TestCase):
    """A QQ profile stores a pay token instead of a refresh token, so the column set follows the platform."""

    def setUp(self):
        """Use one synthetic QQ identity with that platform's encrypted columns."""
        self.source = with_ticket_columns(profile(platform=1))

    def test_qq_columns_are_pay_token_pf_and_pf_key(self):
        """Export and rekey both use the QQ column set and leave a decryptable qq_login_info row."""
        self.assertEqual(cipher_fields(self.source), QQ_FIELDS)
        result = portable_profile(self.source, qq_transform)
        self.assertEqual(set(result[PLAIN_KEY]), set(QQ_FIELDS))
        rekeyed = rekey_profile(result, qq_transform)
        self.assertNotIn(PLAIN_KEY, rekeyed)
        self.assertEqual(credential_columns(rekeyed), QQ_DESTINATION)

    def test_qq_profile_rejects_a_wechat_shaped_plaintext_block(self):
        """A refresh_token block cannot be applied to a QQ snapshot."""
        value = dict(portable_profile(self.source, qq_transform), sdk_plain=PLAIN)
        with self.assertRaisesRegex(AccountError, '不完整'):
            rekey_profile(value, source_transform)


class PortableFileTests(unittest.TestCase):
    """The written migration file is ordinary JSON that the existing importer already accepts."""

    def setUp(self):
        """Keep the account store in a temporary directory with a deterministic fake envelope."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AccountStore(Path(self.temp.name) / 'accounts', test_cipher)
        self.source = with_ticket_columns(profile())
        self.key = self.store.save(self.source)['profile_id']
        self.destination = Path(self.temp.name) / '便携凭据.yxsaccounts'

    def test_export_round_trips_through_the_plain_json_importer(self):
        """Exported profiles carry the decoded ticket and still pass the existing format-2 validation."""
        result = export_portable(self.store, [self.key], self.destination, transform=source_transform)
        self.assertEqual(result['exported'], 1)
        blob = self.destination.read_bytes()
        self.assertIn(PLAIN['access_token'].encode(), blob)
        imported = read_archive(blob)
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0][PLAIN_KEY], PLAIN)
        self.assertEqual(imported[0]['openid'], self.source['openid'])

    def test_export_refuses_foreign_suffix_and_store_directory(self):
        """A mislabelled or Git-visible destination is refused before any credential is written."""
        with self.assertRaisesRegex(AccountError, '后缀'):
            export_portable(self.store, [self.key], Path(self.temp.name) / '凭据.json', transform=source_transform)
        with self.assertRaisesRegex(AccountError, '账号库目录之外'):
            export_portable(self.store, [self.key], self.store.directory / 'x.yxsaccounts', transform=source_transform)

    def test_full_chain_reaches_a_destination_ciphertext_only_profile(self):
        """Export → plain JSON → second PC import → switch leaves only that PC's SDK ciphertext behind."""
        export_portable(self.store, [self.key], self.destination, transform=source_transform)
        home = Path(self.temp.name) / 'home'
        target = AccountStore(home, test_cipher)
        self.assertEqual(target.import_profiles(read_archive(self.destination.read_bytes())), {'imported': 1, 'skipped': 0})
        profile_id = next(path.stem for path in home.glob('*.dpapi'))
        self.assertTrue(needs_rekey(target.load(profile_id)))
        transport = Mock()
        transport.pid.return_value = '9001'
        service = AccountService(target, transport)
        with patch('account_service.transform_sdk', side_effect=lambda pid, mode, values: source_transform(mode, values)):
            service._rekey(target.load(profile_id), threading.Event(), lambda **event: None)
        stored = target.load(profile_id)
        self.assertNotIn(PLAIN_KEY, stored)
        self.assertEqual(credential_columns(stored), DESTINATION)


class PortableSwitchTests(unittest.TestCase):
    """Switching an imported profile re-encrypts on this PC and persists only that ciphertext."""

    def setUp(self):
        """Keep the store in a temporary directory and publish captured status lines."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AccountStore(Path(self.temp.name) / 'accounts', test_cipher)
        self.portable = portable_profile(with_ticket_columns(profile()), source_transform)
        self.key = self.store.save(self.portable)['profile_id']
        self.events = []

    def test_rekey_runs_before_restart_and_saves_destination_ciphertext(self):
        """The stored profile becomes destination ciphertext, so later switches need no plaintext at all."""
        transport = Mock()
        transport.pid.return_value = '4242'
        service = AccountService(self.store, transport)
        with patch('account_service.transform_sdk', side_effect=lambda pid, mode, values: source_transform(mode, values)):
            result = service._rekey(self.store.load(self.key), threading.Event(), lambda **event: self.events.append(event))
        self.assertNotIn(PLAIN_KEY, result)
        self.assertEqual(credential_columns(self.store.load(self.key)), DESTINATION)
        self.assertEqual(self.store.load(self.key)['ticket_status'], '已保存，切换时验证')
        transport.launch.assert_not_called()
        self.assertTrue(any('重新加密' in event.get('status', '') for event in self.events))

    def test_missing_game_process_launches_once_before_rekey(self):
        """A destination PC without a running client starts it, waits for modules and then rekeys."""
        transport = Mock()
        transport.pid.side_effect = [None, '5150']
        transport.wait_modules.return_value = None
        service = AccountService(self.store, transport)
        with patch('account_service.transform_sdk', side_effect=lambda pid, mode, values: source_transform(mode, values)):
            result = service._rekey(self.store.load(self.key), threading.Event(), lambda **event: None)
        self.assertNotIn(PLAIN_KEY, result)
        transport.launch.assert_called_once()
        transport.wait_modules.assert_called_once()


if __name__ == '__main__':
    unittest.main()
