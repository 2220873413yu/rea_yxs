"""Check that collection accepts only the requested server response and never retries uncertainty."""
import unittest
from unittest.mock import Mock, patch

from connection import Connection
from collection import CollectionReplan
from game_log import GameResponseLog
from test_hero_recovery import hero_state, hero_roster


def request(hero=303, target=2792):
    """Build only the JCE fields required to identify an ordinary collection request."""
    return bytes.fromhex('0a01') + hero.to_bytes(2, 'big') + bytes.fromhex('190c0b100131') + target.to_bytes(2, 'big')


def response(hero=303, target=2792, ret=0):
    """Build a minimal tagged army receipt retaining the actual hero tag15 and collection aim tag5."""
    if ret:
        return bytes([1]) + ret.to_bytes(2, 'big')
    return (bytes.fromhex('0c1a0a007b500161') + target.to_bytes(2, 'big') + bytes.fromhex('fa0f01') +
            hero.to_bytes(2, 'big') + bytes.fromhex('0b0b0b'))


class ReceiptTests(unittest.TestCase):
    """Validate matching, foreign traffic and known server refusal with no emulator access."""

    def make_log(self, sent, received):
        """Replace only the stream reader while exercising the production JCE/receipt parser."""
        log = GameResponseLog.__new__(GameResponseLog)
        log.drain = Mock(return_value=[{'tag': 's_11010_1', 'body': sent}, {'tag': 'r_11010_2', 'body': received}])
        return log

    def test_matching_receipt_and_foreign_target(self):
        """A matching hero/aim/target succeeds; foreign requests or responses stop instead of being accepted."""
        self.assertEqual(self.make_log(request(), response()).wait_collection(303, 2792)['army_id'], 123)
        for sent, received in ((request(hero=305), response()), (request(), response(hero=305)),
                               (request(), response(target=2791)), (request(), response(ret=6012))):
            with self.subTest(sent=sent, received=received), self.assertRaises(RuntimeError):
                self.make_log(sent, received).wait_collection(303, 2792)

    def test_uncertain_receipt_has_no_resubmit_path(self):
        """An elapsed receive deadline returns uncertainty rather than granting another departure."""
        log = GameResponseLog.__new__(GameResponseLog)
        log.drain = Mock()
        with self.assertRaises(TimeoutError):
            log.wait_collection(303, 2792, timeout=0)
        log.drain.assert_not_called()


class DispatchTransportTests(unittest.TestCase):
    """Confirm the connection issues one guarded call and then checks activity without another dispatch."""

    def test_one_send_requires_receipt_and_busy_activity(self):
        """Accepted departure receipts still require refreshed activity, avoiding a second idle-looking send."""
        connection = Connection()
        connection.response_log = Mock()
        connection.response_log.wait_collection.return_value = dict(hero_id=303, target_id=2792, army_id=123)
        connection.collection_call = Mock(side_effect=lambda op,*args: {'stages':[dict(
            army_id=123,hero_id=303,target_id=2792,aim=1,state=2)]} if op=='collect_schedule' else 'sent')
        connection.refresh_heroes = Mock(side_effect=lambda:hero_roster(hero_state(
            remaining_ms=0,busy=bool(connection.collection_call.call_count),hero_state=1 if connection.collection_call.call_count else 0)))
        target = dict(target_id=2792, kind=3, level=2, detail_seq=1, available_seq=1, scope_radius=20, x=101, y=191)
        receipt, roster = connection.dispatch_collection({'target': target}, 303, 9)
        self.assertEqual(receipt['army_id'], 123)
        self.assertEqual(connection.collection_call.call_args_list[0].args,
                         ('collect_dispatch', (2792, 303, 3, 2, 1, 1, 20, 101, 191), 9, 303))
        self.assertEqual(connection.collection_call.call_args_list[1].args,('collect_schedule',))
        connection.response_log.wait_collection.side_effect = TimeoutError('uncertain')
        connection.collection_call.reset_mock()
        with self.assertRaises(TimeoutError):
            connection.dispatch_collection({'target': target}, 303, 9)
        connection.collection_call.assert_called_once()

    def test_transient_freshness_waits_without_sending_a_second_query(self):
        """A clock/status transition is re-read locally, never retried as another server query."""
        connection = Connection()
        before = dict(detail_seq=0, available_seq=0)
        connection.response_log = Mock()
        stale = dict(ready=True, target_id=2792, detail_seq=1, available_seq=1, fresh=False)
        fresh = {**stale, 'fresh': True}
        connection.collection_call = Mock(side_effect=[before, 'queried', stale, fresh, {'target': fresh, 'heroes': []}])
        with patch('connection.time.sleep'):
            result = connection.query_collection(2792)
        self.assertTrue(result['target']['fresh'])
        self.assertEqual(sum(call.args[0] == 'collect_query' for call in connection.collection_call.call_args_list), 1)

    def test_busy_hero_without_exact_confirmed_army_target_cannot_allow_next_team(self):
        """A matching receipt plus unrelated busy state is insufficient to confirm this departure's target."""
        for changes in ({'target_id':2793},{'army_id':124},{'hero_id':305},{'aim':3},{'state':9}):
            with self.subTest(changes=changes):
                c=Connection();c.response_log=Mock()
                c.response_log.wait_collection.return_value=dict(hero_id=303,target_id=2792,army_id=123)
                c.refresh_heroes=Mock(side_effect=[hero_roster(hero_state(remaining_ms=0)),hero_roster(hero_state(busy=True,hero_state=1))])
                row={**dict(army_id=123,hero_id=303,target_id=2792,aim=1,state=2),**changes}
                c.collection_call=Mock(side_effect=lambda op,*args: {'stages':[row]} if op=='collect_schedule' else 'sent')
                target=dict(target_id=2792,kind=3,level=2,detail_seq=1,available_seq=1,scope_radius=20,x=101,y=191)
                with self.assertRaisesRegex(RuntimeError,'目标'):
                    c.dispatch_collection({'target':target},303,9)
                self.assertEqual(sum(call.args[0]=='collect_dispatch' for call in c.collection_call.call_args_list),1)

    def test_busy_preflight_and_native_unsent_guard_never_wait_for_receipt(self):
        """Only explicit unsent conditions can replan; no native send happens for a known occupied hero."""
        target=dict(target_id=2792,kind=3,level=2,detail_seq=1,available_seq=1,scope_radius=20,x=101,y=191)
        for busy in (True,False):
            with self.subTest(busy=busy):
                c=Connection();c.response_log=Mock()
                c.refresh_heroes=Mock(return_value=hero_roster(hero_state(busy=busy,remaining_ms=0)))
                c.collection_call=Mock(return_value='collection_replan:stale')
                with self.assertRaises(CollectionReplan):c.dispatch_collection({'target':target},303,9)
                self.assertEqual(c.collection_call.call_count,0 if busy else 1)
                c.response_log.wait_collection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
