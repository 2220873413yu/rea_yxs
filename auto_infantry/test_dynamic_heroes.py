"""Validate persisted selections, dynamic identities and multi-hero fairness without a game."""
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from connection import Connection
from controller import Worker
from hero_preferences import checked_heroes, load_heroes, save_heroes
from hero_recovery import choose_recovery, verify_recovery
from hero_panel import hero_display
from test_hero_recovery import hero_state, hero_roster


class PreferenceTests(unittest.TestCase):
    """Only explicit selections survive restart; the spending master never does."""

    def test_roundtrip_empty_default_and_saved_ids(self):
        """First launch chooses nobody and saved choices remain independent of a default-off switch."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'choices.json'
            self.assertEqual(load_heroes(path), ())
            save_heroes([305, 303, 305], path)
            self.assertEqual(load_heroes(path), (303, 305))
            self.assertEqual(set(json.loads(path.read_text(encoding='utf-8'))), {'version', 'selected_heroes'})
            self.assertFalse(Worker(queue.Queue()).hero_enabled)

    def test_corrupt_and_invalid_preferences_do_not_enable_anything(self):
        """Malformed files and IDs fail validation instead of selecting all heroes or a fallback hero."""
        for value in ([True], [-1], [0], [10000001], ['303'], '303', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_heroes(value)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'choices.json'
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_heroes(path)

    def test_failed_replace_preserves_last_saved_selection(self):
        """A failed atomic replacement leaves the previous choices intact and removes its temporary file."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'choices.json'
            save_heroes([303], path)
            with patch('hero_preferences.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    save_heroes([305], path)
            self.assertEqual(load_heroes(path), (303,))
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])


class SelectionTests(unittest.TestCase):
    """Roster refresh never grants spending permission to unselected, missing or busy heroes."""

    def test_rotation_skips_busy_missing_and_unselected(self):
        """Long-cooldown heroes rotate fairly while unrelated/new heroes never enter the run."""
        roster = hero_roster(hero_state(hero_id=201), hero_state(hero_id=303),
                             hero_state(hero_id=305), hero_state(hero_id=315, busy=True))
        selected = (303, 305, 315, 999)
        cursor = 0
        actions = []
        for _ in range(4):
            state, cursor, message = choose_recovery(roster, selected, cursor)
            actions.append(state['hero_id'])
        self.assertEqual(actions, [303, 305, 303, 305])
        self.assertIsNone(choose_recovery(roster, (315, 999), 0)[0])
        self.assertIsNone(choose_recovery(roster, (), 0)[0])

    def test_foreign_individual_response_is_rejected(self):
        """A response for Xishi cannot confirm an item requested for Chen Yuanyuan."""
        with self.assertRaises(RuntimeError):
            verify_recovery(hero_state(hero_id=305), hero_state(hero_id=303, items=29, remaining_ms=0))

    def test_unknown_status_is_never_displayed_idle(self):
        """Unknown activity data remains visible as unknown rather than falsely inviting recovery."""
        self.assertEqual(hero_display(hero_state(army_known=False))[0], '数据不明')
        self.assertEqual(hero_display(hero_state(hero_state=20))[0], '活动占用')

    def test_dynamic_transport_matches_requested_target(self):
        """The sender and response checks use the selected ID rather than hardcoded303."""
        connection = Connection()
        connection.hero_call = Mock(side_effect=['sent', dict(speed_seq=2, speed_ret=0,
                                    speed_kind=3, speed_type=500, speed_target=305)])
        connection.refresh_hero = Mock(return_value=hero_state(hero_id=305, items=29))
        connection.recover_hero(hero_state(hero_id=305), 9)
        connection.hero_call.assert_any_call('hero_speed', 9, hero_id=305)
        connection.refresh_hero.assert_called_once_with(hero_id=305)
        connection.hero_call = Mock(side_effect=['sent', dict(speed_seq=2, speed_ret=0,
                                    speed_kind=3, speed_type=500, speed_target=303)])
        with self.assertRaises(RuntimeError):
            connection.recover_hero(hero_state(hero_id=305), 9)


class MultiHeroWorkerTests(unittest.TestCase):
    """Run real worker ticks through confirmed multi-hero recovery and selection changes."""

    def test_roundrobin_confirmation_and_rapid_selection_change(self):
        """Each selected eligible hero gets one item per round, then a changed run invalidates an old tick."""
        worker = Worker(queue.Queue())
        game = Mock(hero_generation=7)
        states = {hero_id: hero_state(hero_id=hero_id, remaining_ms=600000)
                  for hero_id in (201, 303, 305, 315)}
        states[315]['busy'] = True
        game.refresh_heroes.side_effect = lambda: hero_roster(*(dict(state) for state in states.values()))
        actions = []

        def recover(before, generation):
            """Apply one isolated accepted item to the requested hero and record its identity."""
            state = states[before['hero_id']]
            actions.append(before['hero_id'])
            state.update(items=state['items'] - 1, finish_ms=state['finish_ms'] - 300000,
                         remaining_ms=max(0, state['remaining_ms'] - 300000))
            return dict(state)

        game.recover_hero.side_effect = recover
        worker.connection = game
        with tempfile.TemporaryDirectory() as folder:
            worker.log_path = Path(folder) / 'actions.jsonl'
            worker.switch_hero(True, (303, 305, 315))
            with patch('controller.time.monotonic', return_value=100):
                for _ in range(4):
                    self.assertTrue(worker.hero_tick(game))
                self.assertFalse(worker.hero_tick(game))
            self.assertEqual(actions, [303, 305, 303, 305])
            self.assertEqual(states[201]['items'], 30)
            self.assertEqual(states[315]['items'], 30)
            worker.switch_hero(False)
            states[303]['remaining_ms'] = 600000
            worker.switch_hero(True, (303,))

            def change_selection():
                """Simulate off/on with another checked hero while a server query is outstanding."""
                worker.switch_hero(False)
                worker.switch_hero(True, (305,))
                return hero_roster(*(dict(state) for state in states.values()))

            game.refresh_heroes.side_effect = change_selection
            worker.hero_tick(game)
            self.assertEqual(actions, [303, 305, 303, 305])
            self.assertEqual(worker.hero_selected, (305,))

    def test_empty_selection_cannot_open_gate(self):
        """No implicit fallback hero is allowed when the user has selected nobody."""
        worker = Worker(queue.Queue())
        worker.connection = Mock()
        with self.assertRaises(ValueError):
            worker.switch_hero(True, ())
        self.assertFalse(worker.hero_enabled)
        worker.connection.set_hero_enabled.assert_not_called()


if __name__ == '__main__':
    unittest.main()
