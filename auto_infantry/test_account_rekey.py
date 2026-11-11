"""Exercise cross-device cipher replacement without logging in or touching an account store."""
import base64
import copy
import hashlib
import sqlite3
import unittest

from account_rekey import FIELDS, credential_columns, seal_source, rekey_destination
from account_store import AccountError, validate_profile
from test_account_profiles import profile


class RekeyTests(unittest.TestCase):
    """Keep source data immutable and reject a mismatched token or destination cipher."""

    def setUp(self):
        """Add the real four-column cipher shape to a synthetic SDK snapshot."""
        self.source = profile()
        with sqlite3.connect(':memory:') as db:
            db.deserialize(validate_profile(self.source))
            db.execute('alter table wx_login_info add column pf text')
            db.execute('alter table wx_login_info add column pf_key text')
            db.execute("update wx_login_info set pf='fake-pf',pf_key='fake-key'")
            db.commit()
            data = db.serialize()
        self.source['database'] = base64.b64encode(data).decode()
        self.source['db_sha256'] = hashlib.sha256(data).hexdigest()
        self.plain = {field: base64.b64encode(b'fake-access' if field == 'access_token'
                                            else ('fake-' + field).encode()).decode() for field in FIELDS}

    def test_rekey_preserves_source_and_validates_destination(self):
        """Old ciphertext survives while all four new columns round-trip and startup auto-login stays off."""
        original = copy.deepcopy(self.source)
        capsule = seal_source(self.source, lambda mode, values: self.plain)
        self.assertNotIn(b'fake-access', capsule)
        encrypted = {field: 'new-sdk-' + field for field in FIELDS}
        def destination(mode, values):
            """Simulate a different device key with exact input assertions in both directions."""
            self.assertEqual(values, self.plain if mode == 'encode' else encrypted)
            return encrypted if mode == 'encode' else self.plain
        result = rekey_destination(capsule, destination)
        self.assertEqual(self.source, original)
        self.assertEqual(credential_columns(result), encrypted)
        self.assertEqual(result['no_auto_login'], 1)
        self.assertEqual(result['sdk_access_token_sha256'], original['sdk_access_token_sha256'])

    def test_source_hash_mismatch_is_rejected(self):
        """No usable capsule is returned if source SDK decoding yields another account's token."""
        with self.assertRaises(AccountError):
            seal_source(self.source, lambda mode, values: {**self.plain, 'access_token': 'd3Jvbmc='})

    def test_destination_readback_mismatch_is_rejected(self):
        """A failed destination round-trip cannot produce a profile ready for authentication."""
        capsule = seal_source(self.source, lambda mode, values: self.plain)
        with self.assertRaises(AccountError):
            rekey_destination(capsule, lambda mode, values: {field: 'wrong' for field in FIELDS})
