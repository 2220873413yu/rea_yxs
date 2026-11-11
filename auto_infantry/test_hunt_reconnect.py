"""Exercise actual passive Lua fencing and acknowledged-army reconciliation without game requests."""
import frida
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lupa import LuaRuntime
from hunt_reconnect import recovery_plan, reconcile, SessionUnsent, SessionAccepted
from collection import CollectionOptions
from monster import HuntOptions
from monster_service import MonsterService
from connection import Connection
from controller import Worker


class ReconnectWitnessTests(unittest.TestCase):
    """A login response replacement alone never authorizes restoring automation."""

    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
Game={uid={1,'private',0,1},scope={42,9},registered=0,unregistered=0}
Game.a={myUserId=Game.uid,mTLoginRsp={0}}
Game.m={mIsMapLoaded=true,mTSLGLoginMapRsp={0,nil,nil,nil,{Game.uid}},
 getTMapGameDataID=function() return Game.scope end}
local mm={getModel=function(_,n)return n=='a'and Game.a or Game.m end}
CSLTypes={MainModel='a',SLGMainModel='m',ModelManager={sharedInstance=function()return mm end},
 Reconnection={RegisterReconnection=function(o)Game.observer=o;Game.registered=Game.registered+1 end,
 unRegisterReconnection=function(o)Game.unregistered=Game.unregistered+1 end}}
''')
        source = Path(__file__).with_name('hunt_reconnect_runtime.lua').read_text(encoding='utf-8')
        self.lua.execute('local reconnectKey="owner";\n' + source)

    def status(self):
        return self.lua.eval('REA_HUNT_RECONNECT.recovery_status("owner")')

    def relogin(self):
        self.lua.execute('Game.observer:NotifyReplayStart();Game.a.mTLoginRsp={0};'
                         'Game.m.mTSLGLoginMapRsp={0,nil,nil,nil,{Game.uid}};'
                         'Game.observer:NotifyReplayLoginSuc()')

    def test_transport_only_reconnect_accepts_same_ready_world(self):
        self.lua.execute('Game.a.mTLoginRsp={0};Game.m.mTSLGLoginMapRsp={0,nil,nil,nil,{Game.uid}}')
        self.assertEqual(self.status(), 'ready')

    def test_native_reconnect_must_finish_and_world_must_be_loaded(self):
        self.lua.execute('Game.observer:NotifyReplayStart();Game.m.mIsMapLoaded=false')
        self.assertTrue(self.lua.eval('REA_HUNT_RECONNECT.paused()'))
        self.assertEqual(self.status(), 'pending')
        self.lua.execute('Game.observer:NotifyReplayLoginSuc()')
        self.assertEqual(self.status(), 'pending')
        self.lua.execute('Game.m.mIsMapLoaded=true')
        self.assertEqual(self.status(), 'ready')

    def test_different_role_zone_or_map_is_terminal(self):
        for mutation in ('Game.uid[1]=2', 'Game.scope[1]=43', 'Game.scope[2]=10'):
            with self.subTest(mutation=mutation):
                self.setUp();self.relogin();self.lua.execute(mutation)
                self.assertEqual(self.status(), 'account' if 'uid' in mutation else 'map')

    def test_world_uid_must_match_and_owner_must_match(self):
        self.relogin();self.lua.execute('Game.m.mTSLGLoginMapRsp[5]={ {2,"another",0,1} }')
        self.assertEqual(self.status(), 'pending')
        self.assertEqual(self.lua.eval('REA_HUNT_RECONNECT.recovery_status("other")'), 'unverified')

    def test_close_removes_only_passive_observer(self):
        self.lua.execute('REA_HUNT_RECONNECT.close();REA_HUNT_RECONNECT.close()')
        self.assertEqual(self.lua.globals().Game.unregistered, 1)
        self.assertEqual(self.status(), 'unverified')


class HuntReconnectTests(unittest.TestCase):
    """Preserve exact accepted teams and exclusions; never replay an uncertain action."""

    def setUp(self):
        self.owner = SimpleNamespace(guard=threading.RLock(), closing=threading.Event(),
                                     connection=None, publish=Mock())
        self.hunt = MonsterService(self.owner)
        self.hunt.enabled = True
        self.hunt.options = HuntOptions(60)
        self.hunt.ignored = {(11, 12)}
        self.hunt.completed = {77}
        self.hunt.home = (100, 100)
        self.hunt.active = {101: dict(army_id=101, hero_id=3, target_id=88, skipped=False,
                                     skip_attempted=False, name='英雄', x=10, y=20, followers=2)}
        self.connection = SimpleNamespace(reconnect_key='owner', process_identity=(10, 'boot', 20))
        self.owner.hunt = self.hunt
        self.owner.collection = SimpleNamespace(enabled=False, uncertain=False)
        self.owner.hero_uncertain = self.owner.allow_scheduled_hunt = False
        self.owner.recovery_mode = 'normal'
        self.roster = {'fresh': True, 'queue_known': True,
                       'heroes': [dict(hero_id=3, fresh=True, army_known=True, busy=True)]}
        self.schedule = {'queue_known': True, 'queue_used': 1, 'queue_limit': 4, 'server_now_ms': 100,
                         'stages': [dict(army_id=101, hero_id=3, target_id=88, aim=3, state=1)]}

    def plan(self):
        return recovery_plan(self.owner, self.connection, RuntimeError('Account session changed'))['hunt']

    def test_checkpoint_requires_enabled_and_confirmed_result(self):
        self.assertEqual(self.plan()['ignored'], {(11, 12)})
        self.hunt.uncertain = True
        self.assertIsNone(self.plan())
        self.hunt.uncertain = False;self.hunt.active[101]['skip_attempted'] = True
        self.assertIsNone(self.plan())
        self.hunt.active[101]['skipped'] = True
        self.assertIsNotNone(self.plan())
        self.hunt.enabled = False
        self.assertIsNone(self.plan())

    def test_reconcile_matches_existing_army_and_preserves_skipped_flag(self):
        self.hunt.active[101].update(skip_attempted=True, skipped=True)
        active, completed = reconcile(self.plan(), self.roster, self.schedule)
        self.assertTrue(active[101]['skipped'])
        self.assertEqual(completed, {77})

    def test_returned_army_is_completed_without_replaying_departure(self):
        self.schedule['stages'] = []
        self.roster['heroes'][0]['busy'] = False
        active, completed = reconcile(self.plan(), self.roster, self.schedule)
        self.assertEqual(active, {})
        self.assertEqual(completed, {77, 88})

    def test_changed_ownership_or_stale_state_stops(self):
        for field, value in (('hero_id', 4), ('target_id', 99), ('aim', 1)):
            with self.subTest(field=field):
                self.setUp();self.schedule['stages'][0][field] = value
                with self.assertRaises(RuntimeError):reconcile(self.plan(), self.roster, self.schedule)
        self.setUp();self.roster['fresh'] = False
        with self.assertRaises(RuntimeError):reconcile(self.plan(), self.roster, self.schedule)

    def test_restore_re_registers_only_accepted_armies_without_dispatch(self):
        plan = self.plan();connection = Mock();self.owner.connection = connection
        self.hunt.enabled = False;self.hunt.ignored.clear()
        self.hunt.restore_reconnect(connection, plan, self.roster, self.schedule)
        self.assertTrue(self.hunt.enabled)
        self.assertEqual(self.hunt.ignored, {(11, 12)})
        connection.hunt_call.assert_called_once_with('hunt_resume', (88, 3, 101, 0))
        connection.dispatch_hunt.assert_not_called();connection.skip_hunt.assert_not_called()


class ReconnectLifecycleTests(unittest.TestCase):
    """Exercise the actual worker shutdown and restore seams, not just isolated identity predicates."""

    def worker(self):
        worker = Worker(queue.Queue())
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        worker.log_path = Path(temp.name) / 'actions.jsonl'
        worker.allow_scheduled_hunt = False
        worker.map_index.load = Mock()
        worker.poll_hero_view = Mock()
        for name in ('trial', 'report', 'league', 'beacon', 'collection'):
            getattr(worker, name).tick = Mock(return_value=False)
        return worker

    def events(self, worker):
        rows = []
        while not worker.events.empty():rows.append(worker.events.get_nowait())
        return rows

    def test_session_fence_captures_confirmed_intent_before_shutdown(self):
        worker = self.worker();connection = Mock(reconnect_key='owner', process_identity=(10, 'boot', 20))
        worker.hunt.enabled = True;worker.hunt.ignored = {(4, 5)}
        worker.hunt.tick = Mock(side_effect=RuntimeError('Account session changed'))
        with patch('controller.Connection', return_value=connection):worker.run()
        rows = self.events(worker)
        plan = next(r['delayed_reconnect'] for r in rows if 'delayed_reconnect' in r)
        self.assertEqual(plan['hunt']['ignored'], {(4, 5)})
        self.assertTrue(connection.preserve_reconnect)
        connection.close.assert_called_once()
        self.assertFalse(any(r.get('account_changed') for r in rows))

    def test_unknown_departure_never_emits_resume_intent(self):
        worker = self.worker();connection = Mock(reconnect_key='owner')
        worker.hunt.enabled = True;worker.hunt.uncertain = True
        worker.hunt.tick = Mock(side_effect=RuntimeError('Account session changed'))
        with patch('controller.Connection', return_value=connection):worker.run()
        plan = next(r['delayed_reconnect'] for r in self.events(worker) if 'delayed_reconnect' in r)
        self.assertTrue(plan['hunt_blocked'])
        self.assertIsNone(plan['hunt'])
        connection.dispatch_hunt.assert_not_called()

    def test_disconnect_after_read_timeout_restores_collection_and_catches_up_once(self):
        """Reproduce the overnight failure: the hunt master is off but its next refresh is armed."""
        old = self.worker()
        old.allow_scheduled_hunt = True
        old.hunt.options = HuntOptions(60)
        old.hunt.auto_refresh.observe(1794340800000, '03:00:00|06:00:00')
        refresh_ms = old.hunt.auto_refresh.next_ms
        old.switch_collection(True, CollectionOptions(use_hero_recovery=True))
        connection = Mock(reconnect_key='owner', process_identity=(10, 'boot', 20))
        old.hunt.tick = Mock(side_effect=RuntimeError('Account session changed'))
        with patch('controller.Connection', return_value=connection):
            old.run()
        plan = next(r['delayed_reconnect'] for r in self.events(old) if 'delayed_reconnect' in r)
        self.assertFalse(plan['hunt']['enabled'])
        self.assertEqual(plan['hunt']['auto_refresh'].next_ms, refresh_ms)

        new = self.worker()
        new.connection = connection
        connection.refresh_heroes.return_value = {'fresh': True, 'queue_known': True, 'heroes': []}
        connection.collection_call.side_effect = [{'queue_known': True}, {'stages': []}]
        schedule = dict(queue_known=True, queue_used=0, queue_limit=4, server_now_ms=refresh_ms, stages=[])
        clock = dict(server_now_ms=refresh_ms + 1, refresh_times='03:00:00|06:00:00')
        connection.hunt_call.side_effect = [schedule, clock]
        new.restore_tasks(connection, plan)
        self.assertTrue(new.collection.enabled)
        self.assertTrue(new.collection.run.options.use_hero_recovery)
        self.assertTrue(any(r.get('collect_use_hero_recovery') for r in self.events(new)))
        self.assertFalse(new.hunt.enabled)
        new.hunt.scheduled_start_tick(connection, 100)
        new.hunt.scheduled_start_tick(connection, 100)
        starts = [r['hunt_auto_start_epoch'] for r in self.events(new) if 'hunt_auto_start_epoch' in r]
        self.assertEqual(len(starts), 1)
        self.assertTrue(new.hunt.start_on_refresh(starts[0], HuntOptions(20)))
        self.assertEqual(new.hunt.options.radius, 60)
        connection.dispatch_hunt.assert_not_called()
        connection.dispatch_collection.assert_not_called()

    def test_collection_unknown_does_not_block_safe_hunt(self):
        """A lost collection response must not erase a settled and independently recoverable hunt."""
        old = self.worker()
        old.switch_collection(True, CollectionOptions())
        old.collection.uncertain = True
        old.hunt.enabled = True
        connection = Mock(reconnect_key='owner', process_identity=(10, 'boot', 20))
        plan = recovery_plan(old, connection, frida.TransportError('connection lost'))
        self.assertTrue(plan['collection_blocked'])
        self.assertIsNone(plan['collection'])
        self.assertTrue(plan['hunt']['enabled'])

    def test_same_pid_with_different_process_start_never_attaches(self):
        """PID reuse must terminate the attempt before attaching to the restarted game."""
        connection = Connection()
        with patch.object(connection, 'acquire_owner'), patch('connection.ensure_client_version'), \
             patch('connection.subprocess.check_output', return_value='versionCode=431000017 '), \
             patch.object(connection, 'read_process_identity', return_value=(10, 'boot', 21)), \
             patch('connection.frida.get_device_manager') as frida_manager:
            with self.assertRaisesRegex(RuntimeError, '游戏已关闭或重启'):
                connection.attach(expected_process=(10, 'boot', 20))
        frida_manager.assert_not_called()

    def test_replacement_worker_queries_once_and_restores_only_hunting(self):
        fixture = HuntReconnectTests();fixture.setUp()
        worker = self.worker()
        plan = recovery_plan(fixture.owner, fixture.connection, RuntimeError('Account session changed'))
        worker.reconnect_plan = plan
        connection = Mock(reconnect_key='new-owner')
        connection.refresh_heroes.return_value = fixture.roster
        connection.hunt_call.return_value = fixture.schedule
        worker.hunt.tick = Mock(side_effect=lambda c: worker.closing.set())
        with patch('controller.Connection', return_value=connection):worker.run()
        self.assertIs(connection.open.call_args.kwargs['hunt_resume'], plan)
        connection.refresh_heroes.assert_called_once()
        self.assertEqual(worker.hunt.ignored, {(11, 12)})
        self.assertTrue(worker.hunt.enabled)
        self.assertFalse(worker.enabled or worker.hero_enabled or worker.collection.enabled)
        connection.dispatch_hunt.assert_not_called();connection.skip_hunt.assert_not_called()

    def test_cancelled_replacement_cannot_open_hunt_gate(self):
        fixture = HuntReconnectTests();fixture.setUp()
        worker = self.worker();connection = Mock()
        worker.reconnect_plan = recovery_plan(fixture.owner, fixture.connection, RuntimeError('Account session changed'))
        def cancel():
            worker.closing.set();return fixture.roster
        connection.refresh_heroes.side_effect = cancel
        connection.hunt_call.return_value = fixture.schedule
        with patch('controller.Connection', return_value=connection):worker.run()
        self.assertFalse(any(call.args == (True,) for call in connection.set_hunt_enabled.call_args_list))
        self.assertFalse(any('delayed_reconnect' in r for r in self.events(worker)))

    def test_scope_check_binds_once_without_server_queries_or_login(self):
        connection = Connection();connection.script = Mock()
        connection.script.exports_sync.query.return_value = 'session_bound'
        connection.verify_reconnect_scope('owner', threading.Event())
        connection.script.exports_sync.query.assert_called_once()
        self.assertIn('local operation="bind"', connection.script.exports_sync.query.call_args.args[0])

    def test_wait_refuses_scope_change_timeout_and_cancel_without_retry(self):
        connection = Connection();connection.script = Mock()
        connection.script.exports_sync.query.return_value = 'map'
        with self.assertRaises(RuntimeError):connection.verify_reconnect_scope('owner')
        connection.script.exports_sync.query.assert_called_once()
        connection.script.exports_sync.query.reset_mock()
        connection.script.exports_sync.query.return_value = 'pending'
        with self.assertRaises(RuntimeError):connection.verify_reconnect_scope('owner')
        connection.script.exports_sync.query.assert_called_once()
        connection.script.exports_sync.query.reset_mock();cancel=threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):connection.verify_reconnect_scope('owner', cancel)
        connection.script.exports_sync.query.assert_not_called()


class ReconnectActionBoundaryTests(unittest.TestCase):
    """Read failures after receipts and pre-body rejections must not turn into duplicate submissions."""

    def setUp(self):
        self.connection = Connection();self.connection.response_log = Mock()
        self.target = dict(target_id=88, detail_seq=1, available_seq=1, x=10, y=20)
        self.formation = dict(hero_id=3, soldier_id=411, followers=2)
        self.error = RuntimeError('Error: rea-auto-infantry:1: Account session changed; reconnect the helper')
        self.receipt = dict(ret=0, hero_id=3, target_id=88, army_id=101)

    def test_successful_departure_receipt_survives_roster_disconnect(self):
        self.connection.hunt_call = Mock(return_value='hunt_departure_submitted')
        self.connection.response_log.wait_hunt.return_value = self.receipt
        self.connection.refresh_heroes = Mock(side_effect=self.error)
        with self.assertRaises(SessionAccepted) as caught:
            self.connection.dispatch_hunt(self.target, self.formation, 60, 1)
        self.assertEqual(caught.exception.receipt, self.receipt)
        self.connection.hunt_call.assert_called_once()

    def test_exact_line_one_fence_is_unsent_but_other_failures_remain_unknown(self):
        self.connection.hunt_call = Mock(side_effect=self.error)
        with self.assertRaises(SessionUnsent):
            self.connection.dispatch_hunt(self.target, self.formation, 60, 1)
        self.connection.response_log.wait_hunt.assert_not_called()
        self.connection.hunt_call.side_effect = TimeoutError('RPC outcome unknown')
        with self.assertRaises(TimeoutError):
            self.connection.dispatch_hunt(self.target, self.formation, 60, 1)
        self.connection.response_log.wait_hunt.assert_not_called()

    def test_unconfirmed_skip_response_is_not_converted_to_unsent(self):
        self.connection.hunt_call = Mock(return_value='hunt_skip_submitted')
        self.connection.response_log.wait_hunt_skip.side_effect = self.error
        with self.assertRaises(RuntimeError) as caught:
            self.connection.skip_hunt(self.receipt, 1)
        self.assertNotIsInstance(caught.exception, SessionUnsent)

    def test_service_keeps_confirmed_departure_before_propagating_disconnect(self):
        from test_monster import target, plan
        owner = SimpleNamespace(guard=threading.RLock(), closing=threading.Event(), publish=Mock())
        service = MonsterService(owner);service.enabled = True
        connection = Mock();candidate = target()
        connection.query_monster.return_value = {'target':candidate,'formations':[plan()]}
        receipt = dict(ret=0, hero_id=303, target_id=1, army_id=101)
        connection.dispatch_hunt.side_effect = SessionAccepted(self.error, receipt)
        with self.assertRaises(SessionAccepted):
            service.attack_candidate(connection, candidate, {}, service.epoch, 1)
        self.assertFalse(service.uncertain)
        self.assertEqual(service.active[101]['target_id'], 1)
        self.assertFalse(service.automatic_start_blocked())
        connection.dispatch_hunt.assert_called_once()

    def test_pre_body_skip_rejection_clears_only_its_unsent_marker(self):
        fixture = HuntReconnectTests();fixture.setUp()
        fixture.schedule['stages'][0]['state'] = 3
        connection = Mock();connection.skip_hunt.side_effect = SessionUnsent(str(self.error))
        with self.assertRaises(SessionUnsent):
            fixture.hunt.advance_armies(connection, fixture.schedule, fixture.hunt.epoch, 1)
        self.assertFalse(fixture.hunt.active[101]['skip_attempted'])
        self.assertIsNotNone(fixture.plan())


if __name__ == '__main__':unittest.main()
