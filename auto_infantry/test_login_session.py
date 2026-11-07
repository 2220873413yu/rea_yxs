"""Verify login lifecycle and account boundaries without authenticating or sending game requests."""
import json
import queue
import threading
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import Mock, patch

from lupa import LuaRuntime
from login_session import LoginSession, SessionEvents, account_label

SOURCE = Path(__file__).with_name('login_runtime.lua').read_text(encoding='utf-8')
ROLE = dict(logged_in=True, stage='MainHallSceneStage', agreement=True, ret=0,
            nickname_hex='c2c3d0d0', level=17, open_platform=0, mobile_platform=1)


class LoginLifecycleTests(unittest.TestCase):
    """One native QR attempt must precede a wholly new, default-off game worker."""

    def setUp(self):
        """Keep all transport and worker seams isolated; use real cancellation and event queues."""
        self.events = queue.Queue()
        self.session = LoginSession(self.events)
        self.session.store = Mock()
        self.session.store.list.return_value = []
        self.cancel = threading.Event()
        self.bridge = Mock()
        self.worker = Mock()

    def replace(self, states, previous=None):
        """Run the actual replacement sequence with predetermined local login cache observations."""
        def call(op='status'):
            if op == 'status':
                return next(states)
            return op + '_requested'
        self.bridge.login_call.side_effect = call
        with patch('login_session.ensure_server'), patch('login_session.Connection', return_value=self.bridge), \
                patch('login_session.Worker', return_value=self.worker) as factory:
            self.session._replace('ios_wechat', 0, self.cancel, previous, None)
            return factory

    def test_missing_agreement_never_requests_qr_or_creates_worker(self):
        """The user, rather than the helper, must accept the native authentication agreement."""
        factory = self.replace(iter([dict(stage='LoginStage', agreement=False)]))
        self.assertEqual(self.bridge.login_call.call_count, 1)
        factory.assert_not_called()
        self.bridge.close.assert_called_once()

    def test_success_closes_old_owner_and_uses_one_qr_before_new_default_off_worker(self):
        """A successful scan cannot resume old automation, heroes, map caches or scheduled hunting."""
        previous = Mock()
        previous.is_alive.return_value = False
        factory = self.replace(iter([dict(stage='LoginStage', agreement=True), ROLE]), previous)
        previous.stop.assert_called_once()
        previous.join.assert_called_once()
        self.assertEqual([c.args for c in self.bridge.login_call.call_args_list], [(), ('qr',), ()])
        self.bridge.close.assert_called_once()
        factory.assert_called_once()
        self.assertIs(self.session.worker, self.worker)
        self.assertFalse(self.worker.allow_scheduled_hunt)
        self.worker.start.assert_called_once()
        self.assertIn('旅行 · 17级 · iOS 微信', account_label(ROLE))

    def test_old_owner_that_does_not_exit_blocks_login_entirely(self):
        """Never acquire a second bridge while a stopped worker may still own game operations."""
        previous = Mock()
        previous.is_alive.return_value = True
        factory = self.replace(iter([]), previous)
        self.bridge.attach.assert_not_called()
        factory.assert_not_called()

    def test_cancelled_or_timed_out_wait_never_retries_authentication(self):
        """Local status checking may stop; a timeout is never permission to resubmit the QR request."""
        self.bridge.login_call.return_value = {'logged_in': False}
        with patch('login_session.time.monotonic', side_effect=[0, 181]):
            with self.assertRaises(TimeoutError):
                self.session._wait(self.bridge, self.cancel, lambda s: s['logged_in'], 180)
        self.assertEqual(self.bridge.login_call.call_count, 1)
        self.cancel.set()
        with self.assertRaises(InterruptedError):
            self.session._wait(self.bridge, self.cancel, lambda s: True, 180)
        self.assertEqual(self.bridge.login_call.call_count, 1)

    def test_events_keep_their_original_account_epoch(self):
        """Even a late old-worker event retains its old epoch and cannot masquerade as a new account."""
        old, new = SessionEvents(self.events, 1), SessionEvents(self.events, 2)
        new.put({'ready': True})
        old.put({'ready': True, 'hunt_auto_start_epoch': 99})
        self.assertEqual(self.events.get()['session_epoch'], 2)
        self.assertEqual(self.events.get()['session_epoch'], 1)


class NativeLoginTests(unittest.TestCase):
    """Exercise the real Lua login checks and session fence against cached native-model doubles."""

    def setUp(self):
        """Build a logged-in world with distinct model objects and instrument only native login callbacks."""
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
Game={stage='LoginStage',agreement=true,qr=0,logout=0}
Game.main={myUserId={10,'private-openid',0,1},mTLoginRsp={0,17,0,0,'','name'}}
Game.world={mIsMapLoaded=true,mTSLGLoginMapRsp={0,nil,nil,nil,{{10,'private-openid',0,1}}}}
local settings={getLicenseAcceptance=function() return Game.agreement end,getLicensePrivacyAcceptance=function() return true end}
local manager={getModel=function(self,kind) return Game[kind] end}
CSLTypes={MainModel='main',SLGMainModel='world',ModelManager={sharedInstance=function() return manager end},
 Setting={sharedInstance=function() return settings end},LoginManager={sharedInstance=function() return {loginOut=function() Game.logout=Game.logout+1 end} end}}
package.loaded.LoginPanel={__instanceDict={getCurrentStageName=function() return Game.stage end}}
package.loaded.LoginCloudMatrix={__instanceDict={onBtnIosWechatClicked=function() Game.qr=Game.qr+1 end}}
package.loaded.TicketsProtocol={__instanceDict={_instance={getLoginInfo=function() return {isLogined=function() return true end} end}}}
''')

    def run_operation(self, operation):
        """Run one fixed production Lua operation; no real game or credentials are present."""
        return self.lua.execute('local operation=' + json.dumps(operation) + '\n' + SOURCE)

    def test_native_qr_requires_stage_and_user_agreement(self):
        """Do not invoke the native callback from a world page or an unchecked login agreement."""
        self.lua.execute('Game.agreement=false')
        with self.assertRaises(Exception):
            self.run_operation('qr')
        self.assertEqual(self.lua.globals().Game.qr, 0)
        self.lua.execute("Game.agreement=true;Game.stage='MainHallSceneStage'")
        with self.assertRaises(Exception):
            self.run_operation('qr')
        self.lua.execute("Game.stage='LoginStage'")
        self.assertEqual(self.run_operation('qr'), 'qr_requested')
        self.assertEqual(self.lua.globals().Game.qr, 1)

    def test_changed_live_model_is_rejected_even_when_old_model_is_unchanged(self):
        """Cached old world tables must never authorize operations after the model manager switches accounts."""
        self.run_operation('bind')
        self.assertTrue(self.lua.eval('REA_HELPER_SESSION_VALID()'))
        self.lua.execute('Game.main={myUserId={11,"new",0,1},mTLoginRsp={0}}')
        self.assertFalse(self.lua.eval('REA_HELPER_SESSION_VALID()'))

    def test_changed_identity_or_map_invalidates_bound_session(self):
        """Mutating the UID in place or replacing the world response invalidates the same fence."""
        self.run_operation('bind')
        self.lua.execute('Game.main.myUserId[4]=0')
        self.assertFalse(self.lua.eval('REA_HELPER_SESSION_VALID()'))
        self.lua.execute('Game.main.myUserId[4]=1')
        self.run_operation('bind')
        self.lua.execute('Game.world.mTSLGLoginMapRsp={0}')
        self.assertFalse(self.lua.eval('REA_HELPER_SESSION_VALID()'))

    def test_old_world_cache_cannot_initialize_a_newly_logged_in_account(self):
        """A loaded old map is insufficient when its player identity differs from the new login identity."""
        self.lua.execute('Game.main.myUserId[1]=11')
        with self.assertRaisesRegex(Exception, 'world cache'):
            self.run_operation('bind')

    def test_role_status_never_contains_private_identifier(self):
        """UI payload includes role metadata only, even though the native model owns account identifiers."""
        self.lua.execute("Game.stage='MainHallSceneStage'")
        value = self.run_operation('status')
        self.assertNotIn('private-openid', value)
        self.assertTrue(json.loads(value)['logged_in'])


class AccountViewTests(unittest.TestCase):
    """Check real Tk account replacement, including queued stale automatic-start messages."""

    def test_old_snapshots_and_events_cannot_survive_account_reload(self):
        """Keep saved choices but erase role data, team timers, item choices and old scheduled starts."""
        loader = SourceFileLoader('login_app_ui_test', str(Path(__file__).with_name('app.pyw')))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with patch.object(module.threading, 'Thread'):
            app = module.App()
        try:
            app.root.withdraw()
            choices = set(app.hero_panel.selection)
            for view in (app.hero_panel, app.collection_teams_panel, app.monster_panel, app.league_panel, app.beacon_panel):
                view.tree.insert('', 'end', values=('old-account',))
            app.hero_panel.roster[99] = {'name': 'old-account'}
            app.hero_panel.speeds[99] = {1: 10}
            app.training_speed.set(True)
            app.hunt_enabled.set(True)
            epoch = app.sessions.epoch
            with patch.object(module.threading, 'Thread'):
                app.request_session('connect')
            app.events.put({'session_epoch': epoch, 'hunt_enabled': True, 'account_status': 'old-account',
                            'hunt_auto_start_epoch': 99})
            app.poll()
            self.assertFalse(app.hunt_enabled.get())
            self.assertFalse(app.training_speed.get())
            self.assertNotEqual(app.account_status.get(), 'old-account')
            self.assertEqual(app.hero_panel.selection, choices)
            self.assertFalse(app.hero_panel.roster)
            self.assertFalse(app.hero_panel.speeds)
            for view in (app.hero_panel, app.collection_teams_panel, app.monster_panel, app.league_panel, app.beacon_panel):
                self.assertFalse(view.tree.get_children())
        finally:
            app.close()


if __name__ == '__main__':
    unittest.main()
