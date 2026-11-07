"""Require one exact alliance request/reply and test the independent transport spending category."""
import unittest
from unittest.mock import Mock

from connection import Connection
from game_log import GameResponseLog
from test_collection_receipts import request, response


def league_request(hero=303, target=2792, secondary=0):
    """Encode aim12 and the native secondary target in the actual JCE request shape."""
    return request(hero, target).replace(bytes.fromhex('190c0b100131'), bytes.fromhex('190c0b100c31')) + bytes([0x40, secondary])


def league_response(hero=303, target=2792, ret=0):
    """Keep only the real success/refusal fields and change the accepted army aim to12."""
    return response(hero, target, ret).replace(bytes.fromhex('500161'), bytes.fromhex('500c61'))


class LeagueReceiptTests(unittest.TestCase):
    """Foreign traffic, server refusals and ambiguous results cannot authorize another departure."""

    def log(self, sent, received):
        """Substitute only the stream reader; production JCE parsing and matching still execute."""
        log = GameResponseLog.__new__(GameResponseLog)
        log.drain = Mock(return_value=[{'tag': 's_11010_1', 'body': sent}, {'tag': 'r_11010_2', 'body': received}])
        return log

    def test_exact_receipt_and_rejections(self):
        """Only aim12 with the same hero, mine and secondary target matches the accepted army."""
        receipt = self.log(league_request(secondary=19), league_response()).wait_league(303, 2792, 19)
        self.assertEqual(receipt['army_id'], 123)
        for sent, received in ((request(), league_response()), (league_request(), response()),
                               (league_request(hero=304), league_response()),
                               (league_request(secondary=19), league_response()),
                               (league_request(), league_response(ret=6012))):
            with self.subTest(sent=sent), self.assertRaises(RuntimeError):
                self.log(sent, received).wait_league(303, 2792, 0)

    def test_no_automatic_resubmit_on_timeout(self):
        """A missing response has no retry path in the matcher or transport."""
        log = GameResponseLog.__new__(GameResponseLog)
        log.drain = Mock()
        with self.assertRaises(TimeoutError):
            log.wait_league(303, 2792, 0, timeout=0)
        log.drain.assert_not_called()

    def test_transport_uses_independent_gate(self):
        """Read operations cannot smuggle strings and native departure uses its own gate generation."""
        c = Connection()
        c.script = Mock()
        c.script.exports_sync.query.return_value = '{}'
        c.league_call('league_dispatch', (151610, 303), 8, 303)
        self.assertEqual(c.script.exports_sync.query.call_args.args[1:], ('league', 303, 8))
        with self.assertRaises(ValueError):
            c.league_call('league_dispatch', ('1);evil()',))

    def test_schedule_recheck_is_bounded_and_refresh_failure_stops_immediately(self):
        """A persistent stale/unknown snapshot gets one refresh, never an indefinite query loop."""
        c=Connection();c.script=Mock();c.refresh_heroes=Mock()
        c.script.exports_sync.query.side_effect=RuntimeError('Fresh own armies required')
        with self.assertRaises(RuntimeError):c.league_call('league_schedule')
        self.assertEqual(c.script.exports_sync.query.call_count,2)
        c.refresh_heroes.assert_called_once_with()
        c.script.exports_sync.query.reset_mock()
        c.refresh_heroes.side_effect=TimeoutError('refresh failed')
        with self.assertRaises(TimeoutError):c.league_call('league_schedule')
        self.assertEqual(c.script.exports_sync.query.call_count,1)

    def test_only_exact_read_guard_can_recheck_and_departures_never_retry(self):
        """Transport errors, world replacement and every spending/ack failure preserve the single-attempt rule."""
        for operation,error in (
                ('league_schedule',TimeoutError('RPC timed out')),
                ('league_schedule',RuntimeError('World map changed')),
                ('league_dispatch',RuntimeError('Fresh own armies required')),
                ('league_ack',RuntimeError('Fresh own armies required'))):
            with self.subTest(operation=operation,error=str(error)):
                c=Connection();c.script=Mock();c.refresh_heroes=Mock()
                c.script.exports_sync.query.side_effect=error
                with self.assertRaises(type(error)):c.league_call(operation)
                c.script.exports_sync.query.assert_called_once()
                c.refresh_heroes.assert_not_called()
