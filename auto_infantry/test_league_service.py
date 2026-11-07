"""Exercise startup, recall, deadline and no-poll behavior with a fully isolated alliance transport."""
import threading
import unittest
from unittest.mock import Mock, patch

from league_service import LeagueService, best_collector


def metrics(stock=100000):
    """Supply an owned free mine and a target-specific native collector candidate."""
    return {'mine': dict(target_id=10, stock=stock, occupied=2, capacity=30, own_present=False, visible=True),
            'heroes': [dict(hero_id=111, name='陈胜', ready=True, speed=338, load=47150,
                            travel_seconds=511, remaining_ms=0)]}


class LeagueServiceTests(unittest.TestCase):
    """No real game/network/spending is used by these state-machine tests."""

    def setUp(self):
        self.now = 100
        self.owner = Mock(guard=threading.RLock(), closing=threading.Event())
        self.game = Mock(league_generation=4)
        self.owner.connection = self.game
        self.roster = {'heroes': [dict(hero_id=111, busy=False, hero_state=0, finish_ms=0)]}
        self.game.refresh_heroes.return_value = self.roster
        self.mine = metrics()
        self.stages = []
        self.seq = 0
        self.game.query_league.side_effect = lambda: self.mine
        self.game.league_call.side_effect = self.read
        self.game.dispatch_league.side_effect = self.depart
        self.service = LeagueService(self.owner)
        self.clock = patch('league_service.time.monotonic', side_effect=lambda: self.now)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()

    def read(self, op):
        """Model local cached watch reads separately from fresh state/schedule reads."""
        if op == 'league_watch':
            return {'seq': self.seq, 'mine': '10', 'stock': 100000, 'occupied': 2}
        if op == 'league_schedule':
            return {'server_now_ms': self.now * 1000, 'stages': self.stages}
        if op == 'league_metrics':
            return self.mine
        raise AssertionError(op)

    def depart(self, target, hero, generation):
        """Accept exactly one send and expose its authoritative marching phase."""
        self.stages = [dict(army_id=30, hero_id=hero, name='陈胜', state=2, end_ms=110000, target_id=target)]
        return dict(army_id=30, hero_id=hero, target_id=target), self.roster

    def tick(self, at=None):
        """Advance monotonic/server clocks together without sleeping or sending real requests."""
        if at is not None:
            self.now = at
        self.service.tick(self.game)

    def test_startup_off_reads_existing_real_state_once(self):
        """Startup reads happen while disabled and do not become a periodic refresh."""
        self.tick()
        self.assertFalse(self.service.enabled)
        self.game.query_league.assert_called_once()
        self.game.dispatch_league.assert_not_called()
        for at in (101, 105, 3000):
            self.tick(at)
        self.game.query_league.assert_called_once()

    def test_manual_army_return_is_observed_then_replaced_only_after_confirmation(self):
        """A returning manual aim12 army blocks dispatch until an authoritative empty army response."""
        self.stages = [dict(army_id=20, hero_id=111, name='陈胜', state=9, end_ms=110000, target_id=10)]
        self.service.switch(True)
        self.tick()
        self.game.dispatch_league.assert_not_called()
        self.tick(110)
        self.game.query_league.assert_called_once()
        self.stages = []
        self.tick(111)
        self.game.dispatch_league.assert_called_once_with(10, 111, 4)
        self.assertTrue(self.service.enabled)

    def test_full_load_stage_to_return_to_home_uses_server_times(self):
        """Separate server collecting/returning deadlines lead to a single later refill."""
        self.service.switch(True)
        self.stages = [dict(army_id=20, hero_id=111, name='陈胜', state=6, end_ms=110000, target_id=10)]
        self.tick()
        self.stages = [dict(army_id=20, hero_id=111, name='陈胜', state=9, end_ms=130000, target_id=10)]
        self.tick(111)
        self.tick(120)
        self.assertEqual(self.game.query_league.call_count, 2)
        self.game.dispatch_league.assert_not_called()
        self.stages = []
        self.tick(131)
        self.assertEqual(self.game.dispatch_league.call_count, 1)

    def test_empty_mine_waits_for_passive_change_without_server_polling(self):
        """No timer is fabricated for an empty mine; a received meaningful push triggers one check."""
        self.mine = metrics(0)
        self.service.switch(True)
        self.tick()
        for at in (101, 110, 300, 10000):
            self.tick(at)
        self.game.query_league.assert_called_once()
        self.mine = metrics()
        self.seq = 1
        self.tick(10001)
        self.game.dispatch_league.assert_called_once()

    def test_unchanged_expired_stage_does_not_loop(self):
        """An old server deadline is confirmed once and then waits for a new push/manual request."""
        self.stages = [dict(army_id=20, hero_id=111, name='陈胜', state=6, end_ms=99000, target_id=10)]
        self.service.switch(True)
        self.tick()
        self.tick(101)
        for at in (102, 103, 150):
            self.tick(at)
        self.assertEqual(self.game.query_league.call_count, 2)

    def test_switch_off_during_read_prevents_departure(self):
        """Completing a server read after the UI closes the gate must not create a new army."""
        self.service.switch(True)
        def stop():
            self.service.switch(False)
            return self.mine
        self.game.query_league.side_effect = stop
        self.tick()
        self.game.dispatch_league.assert_not_called()

    def test_unknown_departure_closes_only_alliance_and_never_retries(self):
        """Uncertain native sends remain blocked across an attempted off/on restart."""
        self.service.switch(True)
        self.game.dispatch_league.side_effect = TimeoutError('unknown')
        self.tick()
        self.assertFalse(self.service.enabled)
        self.assertTrue(self.service.uncertain)
        with self.assertRaises(RuntimeError):
            self.service.switch(True)
        self.tick(500)
        self.game.dispatch_league.assert_called_once()

    def test_rank_uses_target_speed_load_and_travel(self):
        """Alliance speed bonuses are already in the native target metrics, with stable tie breaking."""
        m = metrics()
        row = m['heroes'][0]
        m['heroes'] += [{**row, 'hero_id': 2, 'travel_seconds': 100},
                        {**row, 'hero_id': 3, 'speed': 339, 'load': 1}]
        self.assertEqual(best_collector(m)['hero_id'], 3)
        m['heroes'][-1]['ready'] = False
        self.assertEqual(best_collector(m)['hero_id'], 2)
