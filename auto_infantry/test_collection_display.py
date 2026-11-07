"""Verify the previously requested read-only team time table without game or network access."""
import unittest

from collection_display import display_time, team_snapshot
from collection_wakeup import CollectionWakeup


class CollectionDisplayTests(unittest.TestCase):
    """Present real scheduler times and explicit unknowns, never a second timing calculation."""

    def test_stage_names_and_planned_times_match_the_scheduler(self):
        """Each row retains the raw server time, and its displayed plan follows the actual timer."""
        snapshot = {'server_now_ms': 1793879346000, 'stages': [
            {'army_id': 1, 'hero_id': 242, 'state': 6, 'end_ms': 1793879406000},
            {'army_id': 2, 'hero_id': 305, 'state': 9, 'end_ms': 1793879436000}]}
        roster = {'heroes': [{'hero_id': 242, 'name': '霍光'}, {'hero_id': 305, 'name': '陈圆圆'}]}
        wakeup = CollectionWakeup()
        wakeup.schedule(snapshot, 100)
        view = team_snapshot(snapshot, roster, wakeup, 100)
        self.assertEqual([(row['hero'], row['state']) for row in view['rows']], [('霍光', '采集中'), ('陈圆圆', '返城中')])
        self.assertEqual(view['rows'][0]['end_ms'], 1793879406000)
        self.assertEqual(view['rows'][0]['check_ms'], 1793879407000)
        self.assertEqual(view['next_check_ms'], 1793879407000)
        self.assertEqual(display_time(1793879406039), '11-05 19:50:06')

    def test_cancelled_expired_or_unknown_times_are_not_invented(self):
        """A consumed timer or missing deadline stays unscheduled and a returned army disappears."""
        wakeup = CollectionWakeup()
        snapshot = {'server_now_ms': 1000000, 'stages': [{'army_id': 1, 'state': 99, 'end_ms': 0}]}
        wakeup.schedule(snapshot, 100)
        view = team_snapshot(snapshot, {'heroes': []}, wakeup, 100)
        self.assertEqual(view['rows'][0]['hero'], '未知英雄')
        self.assertEqual(view['rows'][0]['state'], '状态99')
        self.assertIsNone(view['rows'][0]['check_ms'])
        self.assertIsNone(view['next_check_ms'])
        self.assertEqual(display_time(0), '未知')
        snapshot['stages'] = []
        self.assertEqual(team_snapshot(snapshot, {'heroes': []}, wakeup, 100)['rows'], [])
