"""Validate recovery spending boundaries with fake responses, never a game account."""
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from connection import Connection
from controller import Worker
from hero_recovery import recovery_decision, verify_recovery
from test_controller import FakeGame, run_worker


def hero_state(**changes):
    """Build a fresh idle Xishi snapshot whose cooldown lasts eleven minutes."""
    state = dict(hero_id=303, found=True, fresh=True, army_known=True, busy=False,
                 hero_state=0, finish_ms=1000000, remaining_ms=660000, items=30,
                 hero_seq=1, army_seq=1, speed_seq=1)
    state.update(changes)
    return state


def hero_roster(*states):
    """Wrap independent hero snapshots in the authoritative roster response shape."""
    return dict(heroes=list(states), items=states[0]['items'] if states else 30,
                hero_seq=1, army_seq=1, fresh=True)


class RecoveryDecisionTests(unittest.TestCase):
    """Only a known, idle, recovering Xishi may consume an item."""

    def test_busy_and_unknown_states_never_spend(self):
        """An old cooldown must not authorize spending during any nonzero activity state."""
        cases = [dict(hero_state=n) for n in range(1, 54)]
        cases += [dict(busy=True), dict(found=False), dict(fresh=False),
                  dict(army_known=False), dict(hero_id=305)]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(recovery_decision(hero_state(**changes), 303)[0], 'wait')

    def test_recovered_hero_waits_without_needing_items(self):
        """No countdown means no spending even when the inventory is empty."""
        self.assertEqual(recovery_decision(hero_state(remaining_ms=0, items=0))[0], 'wait')

    def test_partial_five_minutes_is_allowed_but_empty_stock_stops(self):
        """The approved remainder policy uses one item, with no fallback to universal items."""
        self.assertEqual(recovery_decision(hero_state(remaining_ms=1000))[0], 'speed')
        with self.assertRaisesRegex(RuntimeError, '已用完'):
            recovery_decision(hero_state(items=0))

    def test_only_confirmed_one_item_and_finish_reduction_pass(self):
        """Clock ticking alone, mismatched inventory, and a new expedition cannot count as success."""
        before = hero_state()
        verify_recovery(before, hero_state(items=29, finish_ms=700000, remaining_ms=360000))
        for changes in (dict(items=30, finish_ms=700000), dict(items=28, finish_ms=700000),
                        dict(items=29, finish_ms=1000000, remaining_ms=650000),
                        dict(items=29, finish_ms=700000, busy=True),
                        dict(items=29, finish_ms=700000, fresh=False)):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                verify_recovery(before, hero_state(**changes))


class RecoveryTransportTests(unittest.TestCase):
    """Responses must belong to Xishi's recovery instead of concurrent training acceleration."""

    def test_wrong_response_and_error_stop_before_refresh(self):
        """Success for another target/type and rejected recovery responses are never accepted."""
        correct = dict(speed_seq=2, speed_ret=0, speed_kind=3, speed_type=500, speed_target=303)
        for changed in (dict(speed_target=305), dict(speed_type=400), dict(speed_ret=1), dict(speed_kind=2)):
            connection = Connection()
            connection.hero_call = Mock(side_effect=['sent', {**correct, **changed}])
            connection.refresh_hero = Mock()
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                connection.recover_hero(hero_state(), 7)
            connection.refresh_hero.assert_not_called()
            self.assertEqual(connection.hero_call.call_args_list[0].args, ('hero_speed', 7))

    def test_confirmed_response_refreshes_before_next_decision(self):
        """A matching response requires a fresh authoritative query before reporting progress."""
        connection = Connection()
        connection.hero_call = Mock(side_effect=['sent', dict(speed_seq=2, speed_ret=0,
                                    speed_kind=3, speed_type=500, speed_target=303)])
        connection.refresh_hero = Mock(return_value=hero_state(items=29))
        self.assertEqual(connection.recover_hero(hero_state(), 7)['items'], 29)
        connection.refresh_hero.assert_called_once()

    def test_uncertain_response_has_no_retry(self):
        """An elapsed deadline never resubmits a possibly accepted spending command."""
        connection = Connection()
        connection.hero_call = Mock(return_value='sent')
        with self.assertRaises(TimeoutError):
            connection.recover_hero(hero_state(), 7, timeout=0)
        connection.hero_call.assert_called_once_with('hero_speed', 7, hero_id=303)

    def test_both_query_generations_must_advance(self):
        """A hero response with an old army cache cannot authorize recovery."""
        connection = Connection()
        connection.hero_call = Mock(return_value=hero_state())
        with self.assertRaises(TimeoutError):
            connection.refresh_hero(timeout=0)
        self.assertEqual(connection.hero_call.call_count, 2)


class RecoveryWorkerTests(unittest.TestCase):
    """Exercise switching and uncertain outcomes through the actual serial worker tick."""

    def make_worker(self):
        """Create a worker with a temporary audit log and a mocked recovery-only transport."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        worker = Worker(queue.Queue())
        worker.log_path = Path(directory.name) / 'actions.jsonl'
        connection = Mock(hero_generation=7)
        connection.refresh_heroes.side_effect = lambda: hero_roster(connection.refresh_hero())
        worker.connection = connection
        return worker, connection

    def test_startup_is_off_and_troop_off_does_not_disable_recovery(self):
        """Training and recovery gates remain independent in both directions."""
        worker, connection = self.make_worker()
        worker.hero_tick(connection)
        connection.refresh_hero.assert_not_called()
        worker.switch_hero(True, (303,))
        worker.switch(False)
        self.assertTrue(worker.hero_enabled)
        worker.switch_hero(False)
        self.assertFalse(worker.enabled)

    def test_user_off_during_query_prevents_spending(self):
        """The switch is checked again after a slow authoritative query."""
        worker, connection = self.make_worker()
        worker.switch_hero(True, (303,))

        def switch_off():
            """Simulate the user's immediate stop while a refresh is in flight."""
            worker.switch_hero(False)
            return hero_state()

        connection.refresh_hero.side_effect = switch_off
        worker.hero_tick(connection)
        connection.recover_hero.assert_not_called()

    def test_busy_hero_waits_and_uncertain_recovery_stops_only_recovery(self):
        """Waiting does not disable monitoring; uncertain consumption closes only its own gate."""
        worker, connection = self.make_worker()
        worker.enabled = True
        worker.switch_hero(True, (303,))
        connection.refresh_hero.return_value = hero_state(hero_state=20)
        worker.hero_tick(connection)
        connection.recover_hero.assert_not_called()
        self.assertTrue(worker.hero_enabled)
        connection.refresh_hero.return_value = hero_state()
        connection.recover_hero.side_effect = TimeoutError('uncertain')
        worker.hero_due = 0
        worker.hero_tick(connection)
        self.assertFalse(worker.hero_enabled)
        self.assertTrue(worker.enabled)
        worker.hero_tick(connection)
        connection.recover_hero.assert_called_once()

    def test_success_keeps_monitoring_and_shutdown_disables_both(self):
        """Completion waits for another cooldown; closing revokes all future spending."""
        worker, connection = self.make_worker()
        worker.switch_hero(True, (303,))
        connection.refresh_hero.return_value = hero_state(remaining_ms=1000)
        connection.recover_hero.return_value = hero_state(items=29, remaining_ms=0, finish_ms=0)
        worker.hero_tick(connection)
        self.assertTrue(worker.hero_enabled)
        worker.stop()
        self.assertFalse(worker.hero_enabled)
        self.assertFalse(worker.enabled)
        connection.set_hero_enabled.assert_called_with(False, ())

    def test_confirmed_recovery_continues_without_advancing_clock(self):
        """Consecutive confirmed items are allowed at the same scheduler time, with no three-second gap."""
        worker, connection = self.make_worker()
        worker.switch_hero(True, (303,))
        first = hero_state(items=29, finish_ms=700000, remaining_ms=360000)
        second = hero_state(items=28, finish_ms=400000, remaining_ms=60000)
        connection.refresh_hero.side_effect = [hero_state(), first]
        connection.recover_hero.side_effect = [first, second]
        with patch('controller.time.monotonic', return_value=100):
            self.assertTrue(worker.hero_tick(connection))
            self.assertTrue(worker.hero_tick(connection))
        self.assertEqual(connection.recover_hero.call_count, 2)

    def test_busy_or_recovered_hero_keeps_low_frequency_polling(self):
        """Only active recovery runs fast; busy heroes and completed cooldowns retain a three-second pause."""
        for busy in (True, False):
            with self.subTest(busy=busy):
                worker, connection = self.make_worker()
                worker.switch_hero(True, (303,))
                connection.refresh_hero.return_value = hero_state(busy=busy, remaining_ms=1000)
                connection.recover_hero.return_value = hero_state(items=29, remaining_ms=0, finish_ms=0)
                with patch('controller.time.monotonic', return_value=100):
                    self.assertFalse(worker.hero_tick(connection))
                    self.assertFalse(worker.hero_tick(connection))
                self.assertEqual(connection.refresh_hero.call_count, 1)
                self.assertEqual(connection.recover_hero.call_count, 0 if busy else 1)

    def test_off_during_confirmed_response_prevents_immediate_continuation(self):
        """A completed in-flight request cannot schedule another item after the user switches off."""
        worker, connection = self.make_worker()
        worker.switch_hero(True, (303,))
        connection.refresh_hero.return_value = hero_state()

        def stop_after_response(before, generation):
            """Simulate a user stop while the server response is being confirmed."""
            worker.switch_hero(False)
            return hero_state(items=29, finish_ms=700000, remaining_ms=360000)

        connection.recover_hero.side_effect = stop_after_response
        self.assertFalse(worker.hero_tick(connection))
        self.assertFalse(worker.hero_tick(connection))
        connection.recover_hero.assert_called_once()


class DualGame(FakeGame):
    """Add independent recovery stock and gate to the existing multi-troop simulator."""

    def __init__(self, fail_hero=False):
        super().__init__()
        self.hero_generation = 0
        self.hero_allowed = False
        self.hero = hero_state(remaining_ms=1000)
        self.hero_calls = 0
        self.fail_hero = fail_hero

    def set_hero_enabled(self, enabled, heroes=()):
        """Track recovery generation independently from the original troop spending gate."""
        self.hero_allowed = enabled
        self.hero_generation += 1

    def refresh_hero(self):
        """Return a fresh hero snapshot without changing troop inventory or queues."""
        return dict(self.hero)

    def refresh_heroes(self):
        """Return the authoritative roster used by the generic scheduler."""
        return hero_roster(self.refresh_hero())

    def recover_hero(self, before, generation):
        """Accept one gated recovery, or simulate an uncertain result without affecting troop transport."""
        assert self.hero_allowed and generation == self.hero_generation
        self.hero_calls += 1
        if self.fail_hero:
            raise TimeoutError('uncertain recovery')
        self.hero.update(items=self.hero['items'] - 1, remaining_ms=0, finish_ms=0)
        return dict(self.hero)


class DualSchedulerTests(unittest.TestCase):
    """Validate shared worker behavior when both feature switches are enabled."""

    def test_confirmed_chain_runs_without_idle_or_troop_delay(self):
        """With the clock frozen, three confirmed items still run before the next troop action."""
        game = DualGame()
        game.hero = hero_state()
        order = []
        original_action = game.action

        def recover(before, generation):
            """Confirm one item and leave a positive cooldown until the third response."""
            self.assertTrue(game.hero_allowed)
            self.assertEqual(generation, game.hero_generation)
            game.hero_calls += 1
            order.append('hero')
            game.hero.update(items=game.hero['items'] - 1,
                             finish_ms=max(0, game.hero['finish_ms'] - 300000),
                             remaining_ms=max(0, game.hero['remaining_ms'] - 300000))
            return dict(game.hero)

        def troop(action, unit=411):
            """Record when ordinary troop scheduling resumes after the confirmed recovery chain."""
            order.append('troop')
            return original_action(action, unit)

        def enable(event, worker, current):
            """Start recovery independently alongside the original troop test run."""
            if event.get('ready'):
                worker.switch_hero(True, (303,))

        game.recover_hero = recover
        game.action = troop
        with patch('controller.time.monotonic', return_value=100):
            run_worker(game, (411,), event_hook=enable)
        self.assertEqual(game.hero_calls, 3)
        self.assertEqual(order[:4], ['hero', 'hero', 'hero', 'troop'])

    def test_troop_completion_preserves_recovery_switch(self):
        """Finishing a troop run must not silently disable ongoing hero monitoring."""
        game = DualGame()
        recovery_at_completion = []

        def observe(event, worker, current):
            """Enable recovery alongside troops and observe the independent completion event."""
            if event.get('ready'):
                worker.switch_hero(True, (303,))
            if event.get('enabled') is False:
                recovery_at_completion.append(worker.hero_enabled)

        run_worker(game, (411,), event_hook=observe)
        self.assertEqual(game.hero_calls, 1)
        self.assertEqual(game.states[411]['count'], 54)
        self.assertEqual(recovery_at_completion, [True])

    def test_uncertain_recovery_does_not_abort_accepted_troop_run(self):
        """An uncertain hero command closes that gate without repeating it or halting troop work."""
        game = DualGame(fail_hero=True)

        def enable(event, worker, current):
            """Start both independent features after their shared connection becomes ready."""
            if event.get('ready'):
                worker.switch_hero(True, (303,))

        worker, events = run_worker(game, (411,), event_hook=enable)
        # The original test helper closes on any enabled=False troop event, not hero_enabled=False.
        self.assertEqual(game.hero_calls, 1)
        self.assertFalse(worker.hero_enabled)
        self.assertEqual(game.states[411]['count'], 54)


if __name__ == '__main__':
    unittest.main()
