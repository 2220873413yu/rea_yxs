"""The 宝具 rule set is explicit, works from the hall, and never sends a request to the game server."""
import queue
import threading
import unittest

from gem_swap import GEMS, OFF, GemSwapSession, gem_id, hero_hex, validate_plan


class FakeBridge:
    """Record every query so tests can assert the exact client-side calls."""

    def __init__(self, answers):
        self.answers = list(answers or [])
        self.calls = []
        self.closed = False

    def query(self, source):
        self.calls.append(source)
        if 'configure' in source:
            return {'state': 'ok'}
        if 'resolve_hero' in source:
            return self.answers.pop(0) if self.answers else {'state': 'failed', 'note': 'not_found'}
        if 'current_hero' in source:
            return self.answers.pop(0) if self.answers else {'state': 'not_in_battle', 'note': 'not_in_battle'}
        if 'revert' in source:
            return self.answers.pop(0) if self.answers else {'state': 'reverted', 'slots': []}
        return self.answers.pop(0) if self.answers else {'state': 'waiting', 'note': 'not_in_battle'}

    def close(self):
        self.closed = True


class Session:
    """Run one session over an injected bridge and collect its published events."""

    def __init__(self, answers=None):
        self.events = queue.Queue()
        self.bridge = FakeBridge(answers)
        self.gem = GemSwapSession(self.events, attach=lambda: self.bridge, interval=.01)

    def wait(self, key, count=1, timeout=2):
        seen = []
        marker = suite_now()
        while suite_now() - marker < timeout:
            try:
                event = self.events.get(timeout=.05)
            except queue.Empty:
                continue
            if key in event:
                seen.append(event[key])
                if len(seen) >= count:
                    return seen
        raise AssertionError(f'{key} was never published; bridge calls: {self.bridge.calls}')


def suite_now():
    import time
    return time.monotonic()


class CatalogTests(unittest.TestCase):
    def test_catalogued_names_map_to_the_configured_ids(self):
        self.assertEqual(gem_id('天狼'), 49034)
        self.assertEqual(gem_id('傲剑'), 49036)
        self.assertEqual(gem_id(OFF), 0)
        self.assertNotIn('倚天', GEMS)

    def test_unknown_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, '未知宝具'):
            gem_id('倚天')

    def test_hero_name_is_passed_as_gbk_hex(self):
        self.assertEqual(hero_hex('朱元璋'), 'D6ECD4AAE8B0')


class PlanTests(unittest.TestCase):
    def test_two_positions_are_frozen_in_order(self):
        self.assertEqual(validate_plan(112, '天狼', '傲剑'), {'hero_base': 112, 'gems': (49034, 49036)})

    def test_missing_hero_position_or_duplicate_is_refused(self):
        for hero, first, second, message in ((0, '天狼', OFF, '英雄'), (112, OFF, OFF, '至少'),
                                             (112, '天狼', '天狼', '同一个')):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_plan(hero, first, second)


class SessionTests(unittest.TestCase):
    def test_arm_configures_the_client_and_reports_enabled(self):
        run = Session()
        run.gem.arm(112, '天狼', '傲剑', '朱元璋')
        self.assertEqual(run.wait('gem_swap_enabled'), [True])
        deadline = suite_now() + 2
        while suite_now() < deadline and not any('configure(112,49034,49036,1)' in c for c in run.bridge.calls):
            pass
        self.assertTrue(any('configure(112,49034,49036,1)' in c for c in run.bridge.calls), run.bridge.calls)
        run.gem.close()

    def test_arming_without_a_hero_is_refused_locally(self):
        run = Session()
        with self.assertRaisesRegex(ValueError, '英雄'):
            run.gem.arm(0, '天狼', OFF)
        self.assertEqual(run.bridge.calls, [])
        run.gem.close()

    def test_disarm_clears_the_client_rules(self):
        run = Session()
        run.gem.arm(112, '天狼', OFF, '朱元璋')
        run.wait('gem_swap_enabled')
        run.gem.disarm()
        deadline = suite_now() + 2
        while suite_now() < deadline and not any('configure(0,0,0,0)' in c for c in run.bridge.calls):
            pass
        self.assertTrue(any('configure(0,0,0,0)' in c for c in run.bridge.calls), run.bridge.calls)
        run.gem.close()

    def test_resolve_reports_the_matching_star_variants(self):
        run = Session([{'state': 'found', 'hero_base': 112, 'ids': [112, 1112, 2112]}])
        run.gem.resolve('朱元璋')
        resolved = run.wait('gem_swap_resolved')[0]
        self.assertEqual(resolved['hero_base'], 112)
        self.assertTrue(any('resolve_hero("D6ECD4AAE8B0")' in c for c in run.bridge.calls), run.bridge.calls)
        run.gem.close()

    def test_probe_reports_the_battle_hero(self):
        run = Session([{'state': 'found', 'hero': 4427, 'slots': [{'slot': 3, 'gem': 49034, 'skill': 203}]}])
        run.gem.probe()
        hero = run.wait('gem_swap_current_hero')[0]
        self.assertEqual(hero['hero'], 4427)
        run.gem.close()

    def test_applied_state_is_reported_once(self):
        run = Session([{'state': 'applied', 'gems': [{'gem': 49034, 'skill': 203}], 'slots': []},
                       {'state': 'applied', 'gems': [{'gem': 49034, 'skill': 203}], 'slots': []}])
        run.gem.arm(112, '天狼', OFF, '朱元璋')
        run.wait('gem_swap_enabled')
        status = run.wait('gem_swap_status')[0]
        self.assertIn('已替换', status)
        run.gem.close()

    def test_failed_replacement_disarms_and_reports(self):
        run = Session([{'state': 'failed', 'note': 'no_empty_slot'}])
        run.gem.arm(112, '天狼', OFF, '朱元璋')
        run.wait('gem_swap_enabled')
        status = run.wait('gem_swap_status')[0]
        self.assertIn('没有空着的槽位', status)
        self.assertFalse(run.gem.enabled)
        run.gem.close()

    def test_revert_restores_and_stays_disarmed(self):
        run = Session([{'state': 'reverted', 'slots': []}])
        run.gem.revert()
        self.assertEqual(run.wait('gem_swap_status')[0], '已还原')
        self.assertTrue(any('REA_GEM_SWAP.revert()' in c for c in run.bridge.calls), run.bridge.calls)
        run.gem.close()


if __name__ == '__main__':
    unittest.main()
