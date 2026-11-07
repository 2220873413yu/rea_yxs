"""Configured map times wake finite scans once, without adding any periodic server refresh."""
import unittest
from datetime import datetime, timezone, timedelta

from monster_refresh import MonsterRefresh


TIMES='00:00:00|03:00:00|06:00:00|09:00:00|12:00:00|15:00:00|18:00:00|21:00:00|24:00:00'


def stamp(hour, minute=0, second=0, day=7):
    """Use explicit Beijing epoch milliseconds so the test never depends on the host timezone."""
    return int(datetime(2026,11,day,hour,minute,second,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)


class MonsterRefreshTests(unittest.TestCase):
    """Treat configured slots as hints, coalescing missed slots rather than replaying network work."""

    def test_exact_boundary_fires_once_then_rearms_the_next_configured_slot(self):
        """Crossing03:00 creates one pending scan; observing the same time never creates a second hint."""
        timer=MonsterRefresh()
        self.assertFalse(timer.observe(stamp(2,59,50),TIMES))
        self.assertEqual(timer.next_ms,stamp(3))
        self.assertFalse(timer.observe(stamp(2,59,59),TIMES))
        self.assertTrue(timer.observe(stamp(3),TIMES))
        self.assertTrue(timer.pending)
        self.assertEqual(timer.next_ms,stamp(6))
        self.assertFalse(timer.observe(stamp(3),TIMES))
        self.assertTrue(timer.consume());self.assertFalse(timer.consume())
        self.assertFalse(timer.observe(stamp(5,59,59),TIMES))
        self.assertTrue(timer.observe(stamp(6),TIMES))

    def test_midnight24_and00_are_one_boundary_in_server_beijing_time(self):
        """Duplicated midnight notation must not cause two scans or an immediate looping deadline."""
        timer=MonsterRefresh();timer.observe(stamp(23,59,59),'24:00:00|00:00:00')
        self.assertEqual(timer.seconds,(0,))
        self.assertEqual(timer.next_ms,stamp(0,day=8))
        self.assertTrue(timer.observe(stamp(0,day=8),'24:00:00|00:00:00'))
        self.assertEqual(timer.next_ms,stamp(0,day=9))

    def test_full_queue_or_long_sleep_coalesces_multiple_missed_boundaries(self):
        """A pending scan remains one item even if several refresh slots pass while all teams are occupied."""
        timer=MonsterRefresh();timer.observe(stamp(0,1),TIMES)
        self.assertTrue(timer.observe(stamp(22),TIMES))
        self.assertEqual(timer.next_ms,stamp(0,day=8))
        self.assertFalse(timer.observe(stamp(7,day=8),TIMES))
        self.assertEqual(timer.next_ms,stamp(9,day=8))
        self.assertTrue(timer.consume())
        self.assertFalse(timer.observe(stamp(7,day=8),TIMES))

    def test_empty_schedule_invalid_data_and_clock_rollback_do_not_create_polling(self):
        """No schedule disables time hints; malformed metadata fails explicitly rather than inventing a period."""
        timer=MonsterRefresh();self.assertFalse(timer.observe(stamp(1),''))
        self.assertIsNone(timer.next_ms)
        timer.observe(stamp(2),TIMES)
        self.assertFalse(timer.observe(stamp(0),TIMES))
        self.assertEqual(timer.next_ms,stamp(3))
        for text in ('25:00:00','24:00:01','03:60:00','3:00:00','03:00:00|'):
            with self.subTest(text=text),self.assertRaises(ValueError):MonsterRefresh().observe(stamp(1),text)
        for now in (0,True,float('nan'),float('inf')):
            with self.subTest(now=now),self.assertRaises(ValueError):MonsterRefresh().observe(now,TIMES)


if __name__=='__main__':unittest.main()
