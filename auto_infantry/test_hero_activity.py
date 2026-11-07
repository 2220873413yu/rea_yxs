"""Validate descriptive hero activity without weakening server-confirmed spending checks."""
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lupa import LuaRuntime

from controller import Worker
from hero_panel import hero_display
from test_hero_runtime import MOCK_GAME
from test_hero_recovery import hero_state


class HeroActivityLuaTests(unittest.TestCase):
    """Exercise the real Lua roster, push-only display path and unchanged recovery guard."""

    def setUp(self):
        """Create a private fake game and establish actual response generations before displaying states."""
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_GAME)
        self.lua.execute(Path(__file__).with_name('hero_runtime.lua').read_text(encoding='utf-8'))
        self.lua.execute('Game.finish=0;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')

    def state(self):
        """Read one display snapshot through the same API used by ordinary recovery confirmation."""
        return json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hero_status(303)'))

    def test_server_army_phases_and_native_business_types_are_distinct(self):
        """Every busy phase remains ineligible for recovery even though its descriptive label differs."""
        self.lua.execute('local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel);'
                         'main.isAttackAimType=function(aim) return aim==3 end;'
                         'main.isGarrisonAimType=function(aim) return aim==4 end;'
                         'main.IsGatherArmType=function(aim) return aim==5 end')
        for phase, aim, label in ((6, 1, '采集中'), (2, 1, '行军中'), (3, 1, '行军中'),
                                  (9, 1, '返城中'), (0, 3, '战斗中'), (3, 3, '进入战斗'),
                                  (11, 3, '等待战斗'), (6, 4, '驻守中'), (6, 5, '集结中')):
            with self.subTest(phase=phase, aim=aim):
                self.lua.execute('local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel);'
                                 f'main._myActionState={{[1]=0,[2]=list({{{{[1]=7,[4]={phase},[5]={aim},[15]={{[1]=303}}}}}}),[3]=list({{}})}}')
                state = self.state()
                self.assertEqual(state['activity_label'], label)
                self.assertTrue(state['busy'])
                self.assertEqual(state['confirmed_ms'], 1000000)
                self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hero_speed,303)')[0])

    def test_special_activity_and_old_data_never_fabricate_a_new_confirmation(self):
        """Activity20 remains occupied; merely re-reading cached data never advances the displayed time."""
        self.lua.execute('Game.state=20;REA_AUTO_INFANTRY.hero_refresh()')
        before = self.state()
        self.assertEqual(before['activity_label'], '活动占用')
        self.lua.execute('Game.time=Game.time+5000')
        after = self.state()
        self.assertFalse(after['fresh'])
        self.assertEqual(after['confirmed_ms'], before['confirmed_ms'])
        self.assertEqual(hero_display(after)[0], '活动占用')

    def test_passive_push_updates_view_without_granting_spending_freshness(self):
        """A late own-army return push changes the UI while the original stale recovery guard still rejects."""
        self.lua.execute('REA_AUTO_INFANTRY.hero_view()')
        self.assertFalse(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hero_view()'))['changed'])
        self.lua.execute('Game.time=Game.time+5000;REA_AUTO_INFANTRY.note_army_push({[1]=7,[4]=9,[5]=1,[15]={[1]=303}})')
        view = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hero_view()'))
        self.assertTrue(view['changed'])
        state = view['roster']['heroes'][0]
        self.assertEqual(state['activity_label'], '返城中')
        self.assertEqual(state['confirmed_ms'], 1005000)
        self.assertFalse(state['fresh'])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hero_speed,303)')[0])
        self.lua.execute('REA_AUTO_INFANTRY.hero_refresh()')
        self.assertEqual(self.state()['activity_label'], '空闲')
        self.assertEqual(len(self.lua.globals().Game.sends), 0)

    def test_cached_view_never_sends_a_server_query(self):
        """Forbid both refresh senders while polling the display, including a passive notification."""
        self.lua.execute('package.loaded.SLGBuildingsController.__instanceDict._instance.sendTSLGGetHeroPubReq=function() error("query forbidden") end;'
                         'package.loaded.SLGMainController.__instanceDict.sendTSLGGetAllArmyReq=function() error("query forbidden") end')
        self.lua.execute('REA_AUTO_INFANTRY.hero_view();REA_AUTO_INFANTRY.hero_view();'
                         'REA_AUTO_INFANTRY.note_army_push({[1]=7,[4]=7,[5]=1,[15]={[1]=303}})')
        view = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hero_view()'))
        self.assertEqual(view['roster']['heroes'][0]['activity_label'], '已返回（待确认）')


class HeroActivityViewTests(unittest.TestCase):
    """Forward local changes and preserve visible uncertainty without adding query scheduling."""

    def test_worker_reads_local_view_only_and_coalesces_local_polls(self):
        """Local250ms reads do not invoke hero/army refresh and unchanged data emits no UI event."""
        events = queue.Queue()
        worker = Worker(events)
        connection = Mock()
        connection.hero_view.return_value = {'changed': True, 'roster': {'heroes': []}}
        with patch('controller.time.monotonic', return_value=100) as clock:
            worker.poll_hero_view(connection)
            clock.return_value = 100.1
            worker.poll_hero_view(connection)
            self.assertEqual(connection.hero_view.call_count, 1)
            clock.return_value = 100.25
            connection.hero_view.return_value = {'changed': False}
            worker.poll_hero_view(connection)
        self.assertEqual(events.qsize(), 1)
        connection.refresh_heroes.assert_not_called()

    def test_unknown_army_or_missing_hero_does_not_display_cached_idle(self):
        """A label cannot override explicit uncertainty in the underlying server identity/activity cache."""
        for field in ('army_known', 'found'):
            state = hero_state(activity_label='空闲', confirmed_ms=1000000, **{field: False})
            self.assertEqual(hero_display(state)[0], '数据不明')

    def test_received_capacity_increase_wakes_one_confirmation_without_server_polling(self):
        """A new server limit wakes the collection scheduler once; unchanged snapshots cannot loop."""
        worker = Worker(queue.Queue())
        worker.collection.enabled = True
        connection = Mock()
        connection.hero_view.return_value = {'changed': True, 'roster': {
            'heroes': [], 'queue_used': 2, 'queue_limit': 2, 'queue_known': True}}
        with patch('controller.time.monotonic', return_value=100) as clock:
            worker.poll_hero_view(connection)
            self.assertFalse(worker.collection.wakeup.pending)
            clock.return_value = 101
            connection.hero_view.return_value['roster']['queue_limit'] = 4
            worker.poll_hero_view(connection)
            self.assertTrue(worker.collection.wakeup.pending)
            worker.collection.wakeup.pending = False
            clock.return_value = 102
            worker.poll_hero_view(connection)
            self.assertFalse(worker.collection.wakeup.pending)
        connection.refresh_heroes.assert_not_called()
