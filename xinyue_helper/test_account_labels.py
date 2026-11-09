"""Keep control-only OAuth names from hiding an otherwise verified saved game account."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from .app import App
from .auth import Credentials
from .secure_store import AccountStore
from .labels import account_name


class AccountLabelTests(unittest.TestCase):
    """Check real row rendering and local name persistence with synthetic credentials only."""

    def test_account_row_uses_known_role_when_wechat_nickname_is_invisible(self):
        """Reproduce the blue empty row even though the same account has a known role name."""
        app = App.__new__(App)
        row = {'profile_id': 'a' * 64, 'nickname': '\x7f' * 27, 'role_name': '一条咸鱼',
               'provider': 'wx', 'game_device': 'ios', 'saved_at': '2026-11-09T11:05:35Z'}
        app.store = Mock()
        app.store.list.return_value = [row]
        app.accounts = Mock()
        app.accounts.get_children.return_value = []
        app.accounts.exists.return_value = True
        app.reload()
        self.assertEqual(app.accounts.insert.call_args.kwargs['values'][0], '一条咸鱼')

    def test_invisible_names_have_readable_fallback(self):
        """Reject control-only and combining-only labels while preserving a real OAuth nickname."""
        for name in ('\x7f' * 27, '\u200b', '   ', '\u0301'):
            self.assertEqual(account_name({'nickname': name, 'provider': 'wx'}), '已保存微信账号')
        self.assertEqual(account_name({'nickname': '昵称', 'role_name': '角色'}), '昵称')

    def test_role_hint_persists_without_changing_login_credentials(self):
        """Keep the display hint encrypted across restart and invalidate it on platform change."""
        with tempfile.TemporaryDirectory() as folder:
            store = AccountStore(Path(folder))
            credentials = Credentials('wx', 'synthetic-token', 'synthetic-openid', nickname='\x7f' * 27)
            row = store.save(credentials, credentials.headers())
            key = row['profile_id']
            store.set_game_device(key, 'ios')
            original = store.load(key)
            store.remember_role(key, '一条咸鱼')
            reloaded = AccountStore(Path(folder)).load(key)
            self.assertEqual({k:v for k,v in reloaded.items() if k != 'role_name'}, original)
            self.assertEqual(store.list()[0]['display_name'], '一条咸鱼')
            store.save(credentials, credentials.headers())
            self.assertEqual(store.list()[0]['display_name'], '一条咸鱼')
            store.set_game_device(key, 'android')
            self.assertNotIn('role_name', store.load(key))


if __name__ == '__main__':
    unittest.main()
