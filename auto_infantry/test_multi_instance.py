"""Regression coverage for device binding, account isolation and single-window tab ownership."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from account_lock import acquire_role, release_role
from instance_config import role_preferences
from instance_worker import run_action
from resource_preferences import save_coordinates


class MultiInstanceTests(unittest.TestCase):
    def test_second_tab_switch_and_close_keep_main_state(self):
        """Use actual Tk tabs with a simulated secondary transport, including a late old-role event."""
        source = Path(__file__).with_name('app.pyw')
        spec = spec_from_loader('multi_instance_app', SourceFileLoader('multi_instance_app', str(source)))
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.App, 'connect'), patch.object(module, 'discover_devices', return_value=['emulator-5556']), \
                patch('secondary_page.InstanceProcess') as transport, tempfile.TemporaryDirectory() as data:
            app = module.App()
            self.addCleanup(app.root.destroy)
            app.root.withdraw()
            transport.return_value.thread.is_alive.return_value = True
            app.enabled.set(True)
            app.league_enabled.set(True)
            app.workspace.select(app.add_device_page)
            deadline = time.monotonic() + 3
            while not any(w.winfo_class() == 'Toplevel' for w in app.root.winfo_children()):
                app.root.update()
                if time.monotonic() >= deadline:
                    self.fail('second-device picker did not open')
                time.sleep(.01)
            picker = next(w for w in app.root.winfo_children() if w.winfo_class() == 'Toplevel')
            body = picker.winfo_children()[0]
            next(w for w in body.winfo_children() if w.winfo_class() == 'TButton').invoke()
            page = app.secondary
            self.assertEqual(page.device, 'emulator-5556')
            self.assertEqual(len(app.workspace.tabs()), 2)
            self.assertEqual(len(page.switches), 7)
            self.assertTrue(app.enabled.get())
            directory = Path(data)
            first = {'role': 'a' * 64, 'zone': 1, 'map_id': 19}
            second = {**first, 'role': 'b' * 64}
            for scope, coordinates in ((first, [(3, 4)]), (second, [(8, 9)])):
                path = role_preferences(directory, **scope)['resources']
                path.parent.mkdir(parents=True)
                save_coordinates(coordinates, path)
            page.apply_event({'device_directory': directory})
            page.apply_event({'session_epoch': 1, 'session_reset': True, 'instance_scope': first,
                              'ready': True, 'login_busy': False})
            self.assertEqual(page.collection.coordinates, ((3, 4),))
            page.update_controls()
            self.assertFalse(page.switches['league_enabled'].get())
            page.league.toggle.invoke()
            transport.return_value.send.assert_called_with(operation='action', action='league_enabled', epoch=1, enabled=True)
            page.league.check.invoke()
            transport.return_value.send.assert_called_with(operation='action', action='league_check', epoch=1)
            page.switches['collect_enabled'].set(True)
            page.switch('collect_enabled')
            sent = transport.return_value.send.call_args.kwargs
            self.assertEqual((sent['action'], sent['epoch']), ('collect_enabled', 1))
            app.workspace.select(app.primary_page)
            app.workspace.select(page)
            self.assertTrue(page.switches['collect_enabled'].get())
            page.session('account_switch', second['role'])
            page.apply_event({'session_epoch': 1, 'collect_enabled': True, 'resource_coordinates': [[50, 50]]})
            self.assertFalse(page.switches['collect_enabled'].get())
            page.apply_event({'session_epoch': 2, 'session_reset': True, 'instance_scope': second,
                              'ready': True, 'login_busy': False})
            self.assertEqual(page.collection.coordinates, ((8, 9),))
            self.assertFalse(any(v.get() for v in page.switches.values()))
            self.assertTrue(app.enabled.get())
            self.assertTrue(app.league_enabled.get())
            transport.return_value.thread.is_alive.return_value = False
            app.close_secondary()
            self.assertEqual(app.workspace.select(), str(app.primary_page))
            transport.return_value.close.assert_called_once()

    def test_same_saved_role_cannot_be_acquired_by_another_process(self):
        """Reject the primary tab's active role across independent Windows processes."""
        role = uuid.uuid4().hex * 2
        handle = acquire_role(role)
        command = ('from account_lock import acquire_role; ' + f'acquire_role({role!r})')
        try:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-c', command], cwd=Path(__file__).parent,
                                    capture_output=True, text=True, encoding='utf-8', timeout=8,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('该账号正在另一台雷电使用', result.stderr)
        finally:
            release_role(handle)

    def test_uncertain_collection_requires_review_before_rearming(self):
        """An explicit review clears the pause without starting a new collection run."""
        worker = Mock(collection_review_pending=True, guard=threading.RLock())
        with self.assertRaisesRegex(ValueError, '先在雷电 1 核对'):
            run_action(worker, {'action': 'collect_enabled', 'enabled': True})
        worker.switch_collection.assert_not_called()
        run_action(worker, {'action': 'collect_reviewed'})
        self.assertFalse(worker.collection_review_pending)
        worker.switch_collection.assert_not_called()
