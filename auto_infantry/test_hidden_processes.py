"""Prevent console flashes when pythonw launches ADB for connection and collection log reads."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from connection import Connection, GameVersionError
from game_log import GameResponseLog


class HiddenProcessTests(unittest.TestCase):
    """Assert the actual GUI subprocess seams use Windows' no-console creation flag."""

    def test_collection_log_reads_never_create_a_console_and_preserve_binary_bytes(self):
        """ADB output used for binary protocol parsing must remain bytes while the console is hidden."""
        log = GameResponseLog.__new__(GameResponseLog)
        log.adb, log.device = 'adb.exe', 'emulator-5554'
        with patch('game_log.subprocess.check_output', return_value=b'\x01\x00\xff\xff') as command:
            self.assertEqual(log.read('exec-out', 'cat', '/test-log'), b'\x01\x00\xff\xff')
        self.assertEqual(command.call_args.kwargs.get('creationflags'), subprocess.CREATE_NO_WINDOW)

    def test_gui_connection_startup_hides_all_adb_children(self):
        """Version, port forwarding and PID reads all stay hidden, not only initial bootstrap commands."""
        connection = Connection()
        connection.acquire_owner = Mock()
        script = Mock()
        script.exports_sync.query.side_effect = ['{"ready":true,"stage":"World"}', 'session_bound', 'witness', 'cleared', 'troop_api_installed', 'hero', 'collection', 'hunt', 'league', 'beacon','beacon_actions','trial_api_installed','report_api_installed']
        connection.initialize_barracks = Mock(return_value={})
        device = Mock()
        device.attach.return_value.create_script.return_value = script
        stat = '123 (com.qqgame.mic) S ' + '0 ' * 18 + '456'
        process = subprocess.CompletedProcess([], 0, stdout='test-boot\n' + stat)
        with patch('connection.subprocess.check_output', return_value='    versionCode=501000073 minSdk=22') as output, \
                patch('connection.subprocess.run') as run, \
                patch('connection.frida.get_device_manager') as manager:
            run.side_effect = [process, subprocess.CompletedProcess([], 0)]
            manager.return_value.add_remote_device.return_value = device
            self.assertEqual(connection.open(), {})
        self.assertEqual(connection.process_identity, (123, 'test-boot', 456))
        for call in output.call_args_list + run.call_args_list:
            self.assertEqual(call.kwargs.get('creationflags'), subprocess.CREATE_NO_WINDOW)

    def test_unknown_build_cannot_acquire_or_attach_a_bridge(self):
        """Reject a future build even if its build number starts with a supported one."""
        connection = Connection()
        with patch('connection.subprocess.check_output', return_value='    versionCode=5010000730'), \
                patch.object(connection, 'acquire_owner') as acquire, \
                patch('connection.frida.get_device_manager') as manager:
            with self.assertRaisesRegex(GameVersionError, '5010000730'):
                connection.attach()
        acquire.assert_not_called()
        manager.assert_not_called()
