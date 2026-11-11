"""Exercise the shared receipt reader against large history and a partial live frame."""
import subprocess
import unittest
from unittest.mock import patch

from game_log import GameResponseLog


class GameLogCursorTests(unittest.TestCase):
    """Opening a receipt cursor must not transfer an entire long-running game's log."""

    def test_large_history_does_not_timeout_and_new_receipts_are_preserved(self):
        """Read only the tail and retain a split frame for the next receipt drain."""
        tag=b'r_11010_Rsp';stamp=b'01:00:00';body=b'\x0c'
        frame=bytes([len(tag)])+tag+bytes([len(stamp)])+stamp+len(body).to_bytes(4,'little')+body
        size=111160906;offset=max(0,(size-524288)//4096)*4096
        calls=[]

        def read(log,*args):
            """Reproduce the reported five-second timeout only for whole-file reads."""
            calls.append(args)
            if args[:2]==('exec-out','cat'):
                raise subprocess.TimeoutExpired(['adb',*args],5)
            if args[:3]==('shell','ls','-t'):
                return b'2026_11_07' if args[3].endswith('/net') else b'20_50_42'
            if args[:2]==('shell','stat'):return str(size).encode()
            if args[:2]==('exec-out','dd'):return b'dd: no such tool\n'
            if args[:3]==('exec-out','toybox','dd'):return b'junk'+frame+frame[:8]
            if args[:2]==('exec-out','tail'):return frame
            raise AssertionError(args)

        with patch.object(GameResponseLog,'read',read):
            log=GameResponseLog('adb')
            self.assertEqual(log.cursor,offset+4+len(frame))
            rows=log.drain()
        self.assertEqual([r['tag'] for r in rows],['r_11010_Rsp'])
        self.assertEqual(log.cursor,offset+4+2*len(frame))
        self.assertTrue(any('count=129' in args for args in calls))

    def test_header_only_log_can_start_before_first_response(self):
        """A new log has no complete frames yet and starts immediately after its header."""
        with patch.object(GameResponseLog,'read',side_effect=[b'2026_11_08',b'00_00_00',b'4']):
            log=GameResponseLog('adb')
        self.assertEqual(log.cursor,4)
