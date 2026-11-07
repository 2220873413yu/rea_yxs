"""Check troop selection, bounded consumption, and shutdown without contacting a game."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from connection import Connection, BarrackUnavailable
from controller import RunBudget, SelectionRun, Worker
from units import UNIT_NAMES, checked_units
from game_log import TrainingRejected


def sample(unit=411, **changes):
    """Create a realistic authoritative snapshot, keeping each troop's capacity independent."""
    state = dict(soldier_id=unit, count=53, limit=54, pending=0, queue_capacity=6, remaining_ms=0,
                 duration_ms=675000, items=100, upgrade_known=True, upgrading=False)
    state.update(changes)
    return state


class FakeGame:
    """Model accepted per-type commands, shared inventory, and the selected-type spending gate."""

    def __init__(self, states=None, fail=False):
        self.states = {unit: sample(unit) for unit in UNIT_NAMES}
        self.states.update(states or {})
        self.items = 100
        self.allowed = set()
        self.calls = []
        self.gates = []
        self.fail = fail
        self.closed = False

    def open(self, **options):
        """Return initial state with all spending disabled."""
        return self.call('status', 411)

    def call(self, operation, unit=411):
        """Return one type's latest snapshot using the shared current inventory."""
        assert operation == 'status'
        return {**self.states[unit], 'items': self.items}

    def refresh(self, unit=411):
        """Simulate a new authoritative barrack query without a spending command."""
        return self.call('status', unit)

    def set_enabled(self, enabled, units=(411,), use_training_speed=False):
        """Record the master gate and permit only its explicit troop selection."""
        self.allowed = set(units) if enabled else set()
        self.use_training_speed = bool(enabled and use_training_speed)
        self.gates.append((enabled, tuple(units)))

    def set_hunt_enabled(self, enabled):
        """Record no hunting work in preexisting troop-only worker scenarios."""
        assert not enabled

    def hunt_call(self, operation):
        """Troop-only tests have no configured hunting schedule and never open a hunt gate."""
        assert operation=='hunt_refresh_clock'
        return {'server_now_ms':1000000,'refresh_times':''}

    def set_league_enabled(self, enabled):
        """Keep alliance spending disabled in preexisting troop/recovery-only transport scenarios."""
        assert not enabled

    def set_beacon_enabled(self, enabled):
        """Troop-only fixtures never authorize beacon actions; shutdown still revokes the new gate."""
        assert not enabled

    def action(self, action, unit=411):
        """Apply one accepted training or item, or simulate one uncertain spending result."""
        assert unit in self.allowed, 'Unselected troop received a spending command'
        assert action != 'speed' or self.use_training_speed, 'Training item use was not selected'
        self.calls.append((action, unit))
        if self.fail:
            raise TimeoutError('uncertain spending result')
        state = self.states[unit]
        if action == 'train':
            state.update(pending=1, remaining_ms=state['duration_ms'])
        else:
            self.items -= 1
            state['remaining_ms'] = max(0, state['remaining_ms'] - 300000)
            if state['remaining_ms'] == 0:
                state['pending'] = 0
                state['count'] += 1
        return self.call('status', unit)

    def hero_view(self):
        """Model a local unchanged view without adding server or spending calls to scheduler tests."""
        return {'changed': False}

    def close(self):
        """Mark cleanup and clear the simulated spending gate."""
        self.closed = True
        self.allowed.clear()


class NaturalTrainingGame(FakeGame):
    """Finish normal training only when the virtual server deadline is reached, without any item use."""

    def __init__(self, clock, states):
        super().__init__(states)
        self.clock = clock
        self.deadlines = {}
        self.queries = []

    def refresh(self, unit=411):
        """Record each real confirmation and update all troop species as one barrack response does."""
        self.queries.append(self.clock[0])
        for key, end in list(self.deadlines.items()):
            state = self.states[key]
            if self.clock[0] >= end:
                state.update(count=state['count'] + state['pending'], pending=0, remaining_ms=0)
                del self.deadlines[key]
            else:
                state['remaining_ms'] = int((end - self.clock[0]) * 1000)
        return self.call('status', unit)

    def action(self, action, unit=411):
        """Queue soldiers in free slots and return a fresh normal-training response."""
        assert action == 'train' and unit in self.allowed and not self.use_training_speed
        self.calls.append((action, unit))
        state = self.states[unit]
        assert state['pending'] < state['queue_capacity']
        assert state['count'] + state['pending'] < state['limit']
        state['pending'] += 1
        self.deadlines.setdefault(unit, self.clock[0] + state['duration_ms'] / 1000)
        return self.refresh(unit)


def run_worker(game, selected, stop_after_action=False, event_hook=None, use_training_speed=True, clock=None):
    """Run the real scheduler through completion or stop while substituting only its transport."""
    events = []

    class Sink:
        """Drive a simulated user start and observe completion without a real desktop window."""

        def put(self, event):
            """Start at ready, or shut down after completion, a failure, or a selected user stop."""
            events.append({**event, 'master_at_event': worker.enabled})
            if event_hook is not None:
                event_hook(event, worker, game)
            if event.get('ready'):
                worker.switch(True, selected, use_training_speed=use_training_speed)
            if stop_after_action and event.get('action'):
                worker.switch(False)
                worker.closing.set()
            if event.get('enabled') is False:
                worker.closing.set()

    worker = Worker(Sink())
    worker.league.tick = Mock()  # Alliance startup reads are covered with their own full transport fixture.
    worker.beacon.tick = Mock()  # Beacon reconciliation/actions have a dedicated transport fixture.
    worker.step_delay = 0
    if clock is not None:
        def advance(seconds):
            """Advance only the test clock instead of waiting through real training minutes."""
            clock[0] += seconds
        worker.closing.wait = advance
    with tempfile.TemporaryDirectory(prefix='troop-tests-') as directory:
        worker.log_path = Path(directory) / 'actions.jsonl'
        with patch('controller.Connection', return_value=game):
            worker.run()
    return worker, events


class BudgetTests(unittest.TestCase):
    """Verify capacity and bounded spending independently of the game's transport."""

    def test_deployed_soldiers_count_toward_training_limit(self):
        """Reproduce47 available +2 deployed +5 training: another infantry would exceed54."""
        state = sample(count=47, deployed=2, pending=5, remaining_ms=665000)
        budget = RunBudget(state)
        self.assertEqual(budget.choose(state), 'wait')
        self.assertEqual(budget.trains, 0)

    def test_full_troops_complete_without_items(self):
        """Already-full troops do not require another item or spending command."""
        self.assertEqual(RunBudget(sample()).choose(sample(count=54, items=0)), 'complete')

    def test_pending_troops_count_toward_the_gap(self):
        """Existing training is accelerated before allocating another training attempt."""
        budget = RunBudget(sample(count=52, pending=1, remaining_ms=75000))
        self.assertEqual(budget.trains, 1)
        self.assertEqual(budget.choose(sample(pending=1, remaining_ms=75000), True), 'speed')

    def test_losses_do_not_extend_budget(self):
        """Repeated losses cannot grant unlimited new training attempts."""
        budget = RunBudget(sample())
        budget.consume('train')
        with self.assertRaises(RuntimeError):
            budget.choose(sample(count=40))

    def test_missing_items_and_changed_capacity_stop(self):
        """Inventory exhaustion and changed limits fail before another spending attempt."""
        budget = RunBudget(sample())
        for state in (sample(items=0), sample(limit=60)):
            with self.assertRaises(RuntimeError):
                budget.choose(state, True)

    def test_default_mode_fills_available_slots_and_waits_without_items(self):
        """Normal training ignores empty item inventory and counts pending soldiers toward capacity."""
        budget = RunBudget(sample(count=48, pending=1, remaining_ms=10000))
        self.assertEqual(budget.choose(sample(count=48, pending=1, remaining_ms=10000, items=0)), 'train')
        self.assertEqual(budget.choose(sample(count=48, pending=6, remaining_ms=10000, items=0)), 'wait')
        self.assertEqual(budget.choose(sample(count=53, pending=1, remaining_ms=10000, items=0)), 'wait')
        with self.assertRaises(RuntimeError):
            budget.choose(sample(queue_capacity=0))

    def test_empty_or_unknown_selection_rejected(self):
        """An empty selection or unverified troop identifier must not enable the master gate."""
        for selected in ((), (414,), (411, True), (412, 999)):
            with self.assertRaises(ValueError):
                checked_units(selected)
        self.assertEqual(checked_units([413, 412, 413]), (412, 413))
        self.assertEqual(checked_units([803]), (803,))


class SchedulerTests(unittest.TestCase):
    def test_scout_natural_training_fills_slots_then_sleeps_until_its_own_deadline(self):
        """Scout-only mode uses375s, makes no intermediate refreshes and never spends an item by default."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {803: sample(803, count=56, limit=58, queue_capacity=8,
                                                       duration_ms=375000)})
        game.items = 0
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            worker, events = run_worker(game, (803,), use_training_speed=False, clock=clock)
        self.assertEqual(game.calls, [('train', 803), ('train', 803)])
        self.assertEqual(game.states[803]['count'], 58)
        self.assertEqual(game.items, 0)
        self.assertFalse(worker.enabled)
        self.assertTrue(any('斥候正常训练中' in event.get('status', '') for event in events))
        self.assertFalse(any(0 < query < 378 for query in game.queries))
        self.assertLessEqual(len(game.queries), 5)

    def test_four_species_complete_independently_with_scouts_finishing_earlier(self):
        """A shorter scout training does not block or prematurely finish the other three species."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {803: sample(803, count=57, limit=58, duration_ms=375000)})
        game.items = 0
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            worker, events = run_worker(game, UNIT_NAMES, use_training_speed=False, clock=clock)
        self.assertEqual(game.calls, [('train', unit) for unit in UNIT_NAMES])
        self.assertEqual([game.states[u]['count'] for u in UNIT_NAMES], [54, 54, 54, 58])
        self.assertEqual(game.items, 0)
        self.assertFalse(worker.enabled)

    def test_scout_speed_uses_existing_opt_in_and_correct_duration(self):
        """An explicitly enabled training-speed checkbox uses two five-minute items for a375s scout."""
        game = FakeGame({803: sample(803, count=57, limit=58, duration_ms=375000)})
        run_worker(game, (803,), use_training_speed=True)
        self.assertEqual(game.calls, [('train', 803), ('speed', 803), ('speed', 803)])
        self.assertEqual(game.items, 98)
        self.assertEqual(game.states[803]['count'], 58)

    def test_upgrading_barrack_stops_only_training_without_sending(self):
        """An upgrading barrack cannot train/spend or disconnect an independently active feature."""
        game = FakeGame({unit: sample(unit, upgrading=True) for unit in UNIT_NAMES})
        def preserve_other_feature(event, worker, current):
            """Keep an independent recovery switch active without exercising its separate transport."""
            if event.get('ready'):
                worker.hero_enabled = True
                worker.hero_tick = Mock(return_value=False)
        worker, events = run_worker(game, (411, 412, 413), event_hook=preserve_other_feature)
        self.assertEqual(game.calls, [])
        self.assertFalse(worker.enabled)
        self.assertTrue(worker.hero_enabled)
        self.assertFalse(any(event.get('ready') is False for event in events))
        self.assertTrue(any('兵营正在升级' in event.get('status', '') for event in events))

    """Exercise the real serial worker across multiple independently selected troop types."""

    def test_assigned_infantry_reaches_cap_without_stopping_other_species(self):
        """Replay the real47+2 infantry case alongside archers and cavalry through natural completion."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {411: sample(411,count=47,deployed=2),
            412: sample(412,count=47),413: sample(413,count=39)})
        game.items = 0
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            worker, events = run_worker(game, (411,412,413), use_training_speed=False, clock=clock)
        self.assertEqual(game.calls.count(('train',411)), 5)
        self.assertEqual(game.calls.count(('train',412)), 7)
        self.assertEqual(game.calls.count(('train',413)), 15)
        self.assertEqual(game.states[411]['count'] + game.states[411]['deployed'], 54)
        self.assertFalse(any('error' in event for event in events))
        self.assertFalse(worker.enabled)

    def test_confirmed_cap_rejection_does_not_stop_other_species_or_retry(self):
        """A racing6015 response is confirmed once; the rejected type waits while archers continue."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {411:sample(411,count=52,pending=1,remaining_ms=675000),
            412:sample(412),413:sample(413,count=54)})
        original_action = game.action
        def reject_racing_infantry(action, unit=411):
            """Simulate one externally accepted training occupying the last place before our request."""
            if unit == 411:
                game.calls.append((action,unit))
                game.states[unit]['pending']=2
                game.deadlines[unit]=clock[0]+675
                raise TrainingRejected(unit,6015)
            return original_action(action,unit)
        game.action = reject_racing_infantry
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            worker, events = run_worker(game,(411,412),use_training_speed=False,clock=clock)
        self.assertEqual(game.calls,[('train',411),('train',412)])
        self.assertEqual(game.states[412]['count'],54)
        self.assertFalse(any('error' in event for event in events))

    def test_normal_training_waits_for_server_duration_without_repeating_queries(self):
        """Fill six slots, sleep until one due confirmation, then train the final missing soldier."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {unit: sample(unit, count=47 if unit == 411 else 54) for unit in UNIT_NAMES})
        game.items = 0
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            worker, events = run_worker(game, (411,), use_training_speed=False, clock=clock)
        self.assertFalse(worker.enabled)
        self.assertEqual(game.states[411]['count'], 54)
        self.assertEqual(game.calls, [('train', 411)] * 7)
        self.assertEqual(game.items, 0)
        positive_queries = [stamp for stamp in game.queries if stamp > 0]
        self.assertTrue(positive_queries)
        self.assertGreaterEqual(min(positive_queries), 678)
        self.assertLessEqual(len(game.queries), 11)
        self.assertTrue(any('下次检查' in event.get('status', '') for event in events))

    def test_stopping_natural_training_cancels_due_confirmation(self):
        """Master-off while waiting causes neither later queries nor item consumption."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {unit: sample(unit) for unit in UNIT_NAMES})
        def stop_on_wait(event, worker, current):
            """Simulate a user disabling training after the first sleeping deadline is displayed."""
            if '下次检查' in event.get('status', ''):
                worker.switch(False)
                worker.closing.set()
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            run_worker(game, (411,), event_hook=stop_on_wait, use_training_speed=False, clock=clock)
        self.assertEqual(game.calls, [('train', 411)])
        self.assertEqual(game.queries, [0, 0])
        self.assertEqual(game.items, 100)

    def test_waiting_species_do_not_block_other_normal_training(self):
        """All selected species receive their free slot before any server-deadline wait ends."""
        clock = [0.0]
        game = NaturalTrainingGame(clock, {unit: sample(unit) for unit in UNIT_NAMES})
        game.items = 0
        with patch('controller.time.monotonic', side_effect=lambda: clock[0]):
            run_worker(game, (411, 412, 413), use_training_speed=False, clock=clock)
        self.assertEqual(game.calls, [('train', 411), ('train', 412), ('train', 413)])
        self.assertEqual([game.states[unit]['count'] for unit in (411, 412, 413)], [54, 54, 54])
        self.assertEqual(game.items, 0)

    def test_single_type_still_reaches_capacity(self):
        """The original infantry behavior remains valid under the shared master switch."""
        game = FakeGame()
        game.states[411]['count'] = 52
        worker, events = run_worker(game, (411,))
        self.assertEqual(game.states[411]['count'], 54)
        self.assertEqual(game.calls.count(('train', 411)), 2)
        self.assertEqual(game.calls.count(('speed', 411)), 6)
        self.assertEqual(game.items, 94)
        self.assertFalse(worker.enabled)
        self.assertTrue(game.closed)

    def test_three_types_rotate_and_stop_together(self):
        """Every selected type gets a turn, and finishing one does not stop the remaining types."""
        game = FakeGame()
        worker, events = run_worker(game, (411, 412, 413))
        self.assertEqual(game.calls[:3], [('train', 411), ('train', 412), ('train', 413)])
        for unit in (411, 412, 413):
            self.assertEqual(game.states[unit]['count'], 54)
            self.assertEqual(game.calls.count(('train', unit)), 1)
            self.assertEqual(game.calls.count(('speed', unit)), 3)
        done = [event for event in events if 'unit_done' in event]
        self.assertEqual(len(done), 3)
        self.assertTrue(all(event['master_at_event'] for event in done))
        self.assertFalse(worker.enabled)
        self.assertEqual(game.items, 91)

    def test_unchecked_and_already_full_types_are_skipped(self):
        """Selecting archers and cavalry must never train unchecked infantry or already-full cavalry."""
        game = FakeGame()
        game.states[413]['count'] = 54
        worker, events = run_worker(game, (412, 413))
        self.assertEqual({unit for action, unit in game.calls}, {412})
        self.assertEqual(game.states[411]['count'], 53)
        self.assertEqual(worker.selected, (412, 413))
        self.assertFalse(worker.enabled)

    def test_each_type_uses_its_own_capacity(self):
        """Different building limits cannot leak between per-type budgets."""
        states = {411: sample(411, count=53, limit=54),
                  412: sample(412, count=59, limit=60),
                  413: sample(413, count=49, limit=50),
                  803: sample(803, count=57, limit=58, duration_ms=375000)}
        game = FakeGame(states)
        run_worker(game, UNIT_NAMES)
        self.assertEqual([game.states[unit]['count'] for unit in UNIT_NAMES], [54, 60, 50, 58])

    def test_master_off_stops_all_types(self):
        """After the first accepted command, master-off prevents another type receiving any command."""
        game = FakeGame()
        worker, events = run_worker(game, (411, 412, 413), stop_after_action=True)
        self.assertEqual(game.calls, [('train', 411)])
        self.assertFalse(worker.enabled)
        self.assertFalse(game.allowed)

    def test_uncertain_response_is_not_retried_or_moved_to_another_type(self):
        """An uncertain request closes the entire selection instead of retrying or spending elsewhere."""
        game = FakeGame(fail=True)
        worker, events = run_worker(game, (411, 412))
        self.assertEqual(game.calls, [('train', 411)])
        self.assertFalse(worker.enabled)
        self.assertTrue(game.closed)
        self.assertTrue(any('uncertain' in event.get('error', '') for event in events))

    def test_loss_after_one_type_finishes_is_not_reported_as_all_full(self):
        """Recheck every selected troop before announcing full capacity during ongoing combat."""
        game = FakeGame()

        def casualty(event, worker, current):
            """Simulate one infantry loss after that type first reaches capacity."""
            if event.get('unit_done') == 411:
                current.states[411]['count'] = 53

        worker, events = run_worker(game, (411, 412, 413), event_hook=casualty)
        self.assertFalse(any(event.get('status') == '所选兵种已补满，已自动关闭' for event in events))
        self.assertTrue(any('本轮训练次数' in event.get('error', '') for event in events))
        self.assertEqual(game.calls.count(('train', 411)), 1)
        self.assertFalse(worker.enabled)


class ResponseTests(unittest.TestCase):
    """Verify that the connection binds a success response to the requested troop identity."""

    def test_upgrade_preflight_and_late_native_guard_do_not_wait_for_a_sent_request(self):
        """Known upgrades and a last-moment native rejection both stop locally, without a send-result timeout."""
        connection = Connection()
        connection.response_log = Mock()
        connection.call = Mock(return_value={'train_seq': 0, 'upgrade_known': True, 'upgrading': True})
        with self.assertRaises(BarrackUnavailable):
            connection.action('train')
        self.assertEqual(connection.call.call_count, 1)
        connection.response_log.wait_training.assert_not_called()
        connection.call = Mock(side_effect=[{'train_seq': 0, 'upgrade_known': True, 'upgrading': False},
                                            RuntimeError('REA_BARRACK_TRAINING_UNAVAILABLE')])
        with self.assertRaises(BarrackUnavailable):
            connection.action('train')
        connection.response_log.wait_training.assert_not_called()

    def test_wrong_troop_response_cannot_be_accepted(self):
        """An archer request must not accept a cavalry response merely because it has iRet=0."""
        connection = Connection()
        connection.response_log = Mock()
        responses = iter(({'train_seq': 1, 'upgrade_known': True, 'upgrading': False},
                          {'train_seq': 2, 'train_ret': 0, 'train_unit': 413}))

        def fake_call(operation, unit=411):
            """Return a foreign successful response after recording the archer request."""
            self.assertEqual(unit, 412)
            return next(responses) if operation == 'status' else 'sent'

        connection.call = fake_call
        with self.assertRaisesRegex(RuntimeError, '响应兵种'):
            connection.action('train', 412)


if __name__ == '__main__':
    unittest.main()
