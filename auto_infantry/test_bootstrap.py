"""Verify version-pinned emulator service migration without touching a real emulator."""
import subprocess
import unittest
from unittest.mock import Mock, patch

import bootstrap


class BootstrapVersionTests(unittest.TestCase):
    """Keep new and old emulator paths deterministic and reject mixed Frida environments early."""

    def result(self, text='', code=0):
        return subprocess.CompletedProcess([], code, text, '')

    def online_adb(self, command, *args, **kwargs):
        """Return the selected emulator state before the root check."""
        return self.result('device' if command == 'get-state' else 'uid=0(root)')

    def test_offline_device_stops_before_starting_service(self):
        with (patch('bootstrap.ensure_client_version'), patch('bootstrap.adb', return_value=self.result('', 1)) as adb,
              patch('bootstrap.root_command') as root):
            with self.assertRaisesRegex(RuntimeError, '未在线'):
                bootstrap.ensure_server()
            adb.assert_called_once_with('get-state', check=False)
            root.assert_not_called()

    def test_adb_override_and_new_emulator_preference(self):
        with patch('bootstrap.Path.is_file', return_value=True):
            self.assertEqual(bootstrap.find_adb('D:/custom/adb.exe'), 'D:/custom/adb.exe')
            self.assertIn('LDPlayer14', bootstrap.find_adb())
        with patch('bootstrap.Path.is_file', autospec=True, side_effect=lambda p: 'LDPlayer9' in str(p)):
            self.assertIn('LDPlayer9', bootstrap.find_adb())

    def test_client_mismatch_stops_before_any_emulator_command(self):
        with patch('bootstrap.frida.__version__', '17.25.2'), patch('bootstrap.adb') as adb:
            with self.assertRaisesRegex(RuntimeError, '17.26.2'):bootstrap.ensure_server()
            adb.assert_not_called()

    def test_existing_service_requires_exact_running_image_version_and_port(self):
        with (patch('bootstrap.ensure_client_version'), patch('bootstrap.adb', side_effect=self.online_adb),
             patch('bootstrap.server_pids', return_value=['100']), patch('bootstrap.root_command') as root):
            root.side_effect = [self.result(bootstrap.SERVER), self.result('17.26.2'),
                                self.result('\0'.join(['rea-frida-server-17.26.2','-l','127.0.0.1:27042','-D','']))]
            bootstrap.ensure_server()
            self.assertFalse(any('kill' in c.args[0] or ' -D' in c.args[0] for c in root.call_args_list))

    def test_known_old_service_is_verified_before_termination(self):
        with (patch('bootstrap.ensure_client_version'), patch('bootstrap.adb', side_effect=self.online_adb),
             patch('bootstrap.server_pids', side_effect=[[], ['77'], [], ['88']]), patch('bootstrap.root_command') as root):
            root.side_effect = [self.result(''), self.result(''), self.result('17.26.2'),
                self.result(bootstrap.OLD_SERVER), self.result(''), self.result(''),
                self.result(bootstrap.SERVER), self.result('17.26.2'),
                self.result('\0'.join(['rea-frida-server-17.26.2','-l','127.0.0.1:27042','-D','']))]
            bootstrap.ensure_server()
            commands = [c.args[0] for c in root.call_args_list]
            self.assertLess(commands.index('readlink /proc/77/exe'), commands.index('kill -TERM 77'))

    def test_unknown_old_process_image_is_never_terminated(self):
        with (patch('bootstrap.ensure_client_version'), patch('bootstrap.adb', side_effect=self.online_adb),
             patch('bootstrap.server_pids', side_effect=[[], ['77']]), patch('bootstrap.root_command') as root):
            root.side_effect = [self.result(''), self.result(''), self.result('17.26.2'), self.result('/unknown/server')]
            with self.assertRaisesRegex(RuntimeError, '路径'):bootstrap.ensure_server()
            self.assertFalse(any('kill' in c.args[0] for c in root.call_args_list))

    def test_mismatched_remote_binary_never_stops_old_service(self):
        with (patch('bootstrap.ensure_client_version'), patch('bootstrap.adb', side_effect=self.online_adb),
             patch('bootstrap.server_pids', return_value=[]), patch('bootstrap.root_command') as root):
            root.side_effect = [self.result(''), self.result(''), self.result('17.25.2')]
            with self.assertRaisesRegex(RuntimeError, '版本'):bootstrap.ensure_server()
            self.assertFalse(any('kill' in c.args[0] for c in root.call_args_list))


if __name__ == '__main__':unittest.main()
