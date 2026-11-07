"""Prevent console flashes when pythonw launches ADB for connection and collection log reads."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from connection import Connection
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
        script.exports_sync.query.side_effect = ['{"ready":true,"stage":"World"}', 'session_bound', 'cleared', 'troop_api_installed', 'hero', 'collection', 'hunt', 'league', 'beacon','beacon_actions']
        connection.initialize_barracks = Mock(return_value={})
        device = Mock()
        device.attach.return_value.create_script.return_value = script
        with patch('connection.subprocess.check_output', side_effect=['versionCode=431000017 ', '123']) as output, \
                patch('connection.subprocess.run') as run, \
                patch('connection.frida.get_device_manager') as manager:
            manager.return_value.add_remote_device.return_value = device
            self.assertEqual(connection.open(), {})
        for call in output.call_args_list + run.call_args_list:
            self.assertEqual(call.kwargs.get('creationflags'), subprocess.CREATE_NO_WINDOW)
