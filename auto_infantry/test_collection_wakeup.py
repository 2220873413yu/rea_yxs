"""Verify notification coalescing with a deterministic clock and no game connection."""
import unittest
import math
from unittest.mock import Mock

from collection_wakeup import CollectionWakeup


class CollectionWakeupTests(unittest.TestCase):
    """A local marker may be sampled frequently without increasing server request frequency."""

    def test_local_poll_frequency_and_one_pending_check_per_burst(self):
        """Two hundred status changes become one check, with a1s minimum and a250ms local poll."""
        wakeup = CollectionWakeup()
        connection = Mock()
        connection.collection_push_sequence.return_value = 0
        wakeup.poll(connection, 100)
        self.assertTrue(wakeup.begin(100, 0))
        connection.collection_push_sequence.return_value = 200
        wakeup.poll(connection, 100.1)
        self.assertEqual(connection.collection_push_sequence.call_count, 1)
        wakeup.poll(connection, 100.25)
        self.assertTrue(wakeup.pending)
        self.assertFalse(wakeup.begin(100.25, 103))
        self.assertTrue(wakeup.begin(101, 103))
        self.assertFalse(wakeup.begin(102, 104))

    def test_push_during_a_check_is_preserved_for_the_next_bounded_check(self):
        """Only the marker seen before beginning is consumed; a later push triggers one follow-up."""
        wakeup = CollectionWakeup()
        connection = Mock()
        connection.collection_push_sequence.return_value = 0
        wakeup.poll(connection, 100)
        self.assertTrue(wakeup.begin(100, 0))
        connection.collection_push_sequence.return_value = 1
        wakeup.poll(connection, 100.5)
        self.assertFalse(wakeup.begin(100.5, 103))
        self.assertTrue(wakeup.begin(101, 103))
        self.assertFalse(wakeup.begin(102, 104))
        self.assertTrue(wakeup.begin(104, 104))

    def test_server_deadline_uses_server_clock_and_consumes_each_stage_once(self):
        """PC epoch, resource amount and level bonuses are irrelevant to server-stage scheduling."""
        wakeup = CollectionWakeup()
        snapshot = {'server_now_ms': 1793880000000,
                    'stages': [{'army_id': 1, 'state': 6, 'end_ms': 1793880060000},
                               {'army_id': 2, 'state': 9, 'end_ms': 1793880120000}]}
        due = wakeup.schedule(snapshot, 10)
        self.assertEqual(due, 71)
        self.assertFalse(wakeup.begin(70.99, due))
        self.assertTrue(wakeup.begin(71, due))
        snapshot['server_now_ms'] += 61000
        self.assertEqual(wakeup.schedule(snapshot, 71), 131)
        snapshot['stages'][0] = {'army_id': 1, 'state': 9, 'end_ms': 1793880090000}
        self.assertEqual(wakeup.schedule(snapshot, 71), 101)

    def test_no_deadlines_or_unchanged_expired_deadlines_do_not_poll(self):
        """No timer means no scheduled query, and a lagging expired timestamp never loops forever."""
        wakeup = CollectionWakeup()
        snapshot = {'server_now_ms': 1000000, 'stages': []}
        self.assertTrue(math.isinf(wakeup.schedule(snapshot, 100)))
        self.assertFalse(wakeup.begin(999999, float('inf')))
        snapshot['stages'] = [{'army_id': 1, 'state': 6, 'end_ms': 990000}]
        self.assertEqual(wakeup.schedule(snapshot, 100), 101)
        self.assertTrue(wakeup.begin(101, 101))
        snapshot['server_now_ms'] += 1000
        self.assertTrue(math.isinf(wakeup.schedule(snapshot, 101)))
        snapshot['stages'][0]['end_ms'] += 1
        self.assertTrue(math.isinf(wakeup.schedule(snapshot, 102)))
        snapshot['stages'][0]['end_ms'] = 1100000
        self.assertEqual(wakeup.schedule(snapshot, 102), 202)
