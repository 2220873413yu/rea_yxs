"""Verify explicit local account deletion without contacting any service or altering receipt history."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from .app import App
from .auth import Credentials
from .secure_store import AccountStore,StoreError


class AccountDeleteTests(unittest.TestCase):
    """Exercise deletion boundaries and the real UI handler using synthetic accounts only."""

    def test_delete_only_selected_encrypted_file(self):
        """Keep other accounts and historical records, including when deletion is repeated."""
        with tempfile.TemporaryDirectory() as folder:
            store=AccountStore(folder)
            first=Credentials('qq','test-token','first')
            second=Credentials('wx','test-token','second')
            key=store.save(first,first.headers())['profile_id']
            other=store.save(second,second.headers())['profile_id']
            history=Path(folder)/'history.db';history.write_bytes(b'receipts')
            store.delete(key);store.delete(key)
            self.assertEqual([row['profile_id'] for row in store.list()],[other])
            self.assertEqual(history.read_bytes(),b'receipts')
            for invalid in ('../history.db','',None,'x'*64):
                with self.assertRaises(StoreError):store.delete(invalid)

    def make_app(self):
        """Build an idle handler fixture with separate cached account states and no Tk window."""
        app=Mock(spec=App);app.busy=False;app.root=Mock();app.active='selected'
        app.store=Mock();app.accounts=Mock();app.status=Mock()
        app.accounts.selection.return_value=('selected',)
        app.accounts.item.return_value=('旅行','iOS / 微信')
        for name in ('states','bounty_states','weekly_states','gscore_states','exchange_states'):
            setattr(app,name,{'selected':object(),'other':object()})
        return app

    def test_cancel_or_busy_never_deletes(self):
        """An ongoing operation and a cancelled confirmation both leave the stored account untouched."""
        app=self.make_app()
        with patch('xinyue_helper.app.messagebox.askokcancel',return_value=False) as confirm:
            App.delete_account(app)
            app.store.delete.assert_not_called()
            app.busy=True;App.delete_account(app)
            self.assertEqual(confirm.call_count,1)

    def test_confirm_removes_only_selected_cached_states(self):
        """The UI reloads local rows after successful deletion without invoking account logout or binding."""
        app=self.make_app()
        with patch('xinyue_helper.app.messagebox.askokcancel',return_value=True):App.delete_account(app)
        app.store.delete.assert_called_once_with('selected')
        for name in ('states','bounty_states','weekly_states','gscore_states','exchange_states'):
            self.assertEqual(set(getattr(app,name)),{'other'})
        app.reload.assert_called_once();app.select.assert_called_once()

    def test_storage_failure_retains_display_and_caches(self):
        """Do not claim success or remove UI state if Windows refuses to delete the encrypted file."""
        app=self.make_app();app.store.delete.side_effect=StoreError('删除失败')
        with patch('xinyue_helper.app.messagebox.askokcancel',return_value=True):App.delete_account(app)
        self.assertIn('selected',app.states)
        app.reload.assert_not_called()
