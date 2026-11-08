"""Hall-only profile access, cache reuse and hook ownership without sending real game requests."""
import importlib.util
import json
import queue
import tempfile
import threading
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import Mock,patch
from lupa import LuaRuntime
from connection import Connection
from controller import Worker
from hall_profile import HallProfileSession,query_hall_profile
from player_profile_cache import PlayerProfileCache
from test_player_profile_cache import cipher
from test_player_query import FIXTURE
from test_league_export import profile,member


class HallProfileRuntimeTests(unittest.TestCase):
    """Public IDs require login identity, while saved-map member bindings still require the correct map."""

    def setUp(self):
        """Build a logged-in hall with no loaded world and no map login response."""
        self.lua=LuaRuntime();self.lua.execute(FIXTURE)
        self.lua.execute('''Game.world.mIsMapLoaded=false;Game.world.mTSLGLoginMapRsp=nil
Game.account.myUserId=Game.uid
package.loaded.HeroPalaceItem={__instanceDict={getCurrentStageName=function()return 'MainHallSceneStage'end}}
CSLTypes.RefreshTimer={getServerTimeNow=function()return 1234 end}''')
        self.lua.execute(Path(__file__).with_name('player_query_runtime.lua').read_text(encoding='utf-8'))

    def test_public_query_works_without_world_and_uses_server_clock(self):
        """Hall metadata and loading send nothing; exactly one lookup/profile sequence is permitted on a click."""
        scope=json.loads(self.lua.execute('return REA_PLAYER_QUERY.login_context()'))
        self.assertEqual(scope,dict(zone_id=5,map_id=0));self.assertEqual(self.lua.execute('return #Game.sent'),0)
        self.lua.execute('REA_PLAYER_QUERY.resolve(7);REA_PLAYER_QUERY.lookup(7);REA_PLAYER_QUERY.profile(7);Game.profile=profile(Game.uid)')
        result=json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(7)'))
        self.assertTrue(result['ready']);self.assertEqual(result['confirmed_ms'],1234000)
        self.assertEqual(self.lua.execute('return #Game.sent'),2)
        with self.assertRaisesRegex(Exception,'地图'):self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid)')

    def test_login_and_identity_changes_block_even_with_no_world(self):
        """Account guards cannot be weakened merely because world readiness was removed."""
        for change in ('Game.account.mTLoginRsp={0}','Game.account.myUserId={999,"other",1,1}','Game.account.mTLoginRsp=nil'):
            with self.subTest(change=change):
                self.setUp();self.lua.execute(change)
                with self.assertRaises(Exception):self.lua.execute('REA_PLAYER_QUERY.resolve(7)')
                self.assertEqual(self.lua.execute('return #Game.sent'),0)


class HallProfileGatewayTests(unittest.TestCase):
    """Exercise the actual temporary gateway through mocked device boundaries and a real encrypted-cache interface."""

    def test_cache_miss_then_restart_hit_and_clear_never_initialize_world(self):
        """A fresh lookup runs once; cached/clear clicks open no network logs and preserve world adapters."""
        with tempfile.TemporaryDirectory()as folder:
            client=Connection();client.profile_cache=PlayerProfileCache(folder,cipher)
            session=Mock();script=session.create_script.return_value
            scope=dict(zone_id=1,map_id=0)
            def local_query(source):
                """Return only already local context and identity metadata to the cache layer."""
                if '.login_context()'in source:return json.dumps(scope)
                if '.identity('in source:return json.dumps(member(1)['identity'])
                return 'installed'
            script.exports_sync.query.side_effect=local_query
            with patch('hall_profile.ensure_account_available'),patch('hall_profile.subprocess.run'),\
                 patch('hall_profile.subprocess.check_output',return_value='123'),patch('hall_profile.frida.get_device_manager')as manager,\
                 patch('hall_profile.Connection',return_value=client),patch('hall_profile.GameResponseLog')as log,\
                 patch('hall_profile.query_player',return_value=profile())as network:
                manager.return_value.add_remote_device.return_value.attach.return_value=session
                first=query_hall_profile(profile()['display_id'],lambda:False)
                client.profile_cache=PlayerProfileCache(folder,cipher)
                cached=query_hall_profile(profile()['display_id'],lambda:False)
                cleared=query_hall_profile(None,lambda:False,clear_cache=True)
                network.assert_called_once();log.assert_called_once()
            self.assertEqual(first['display_id'],profile()['display_id']);self.assertTrue(cached['from_cache']);self.assertTrue(cleared['cleared'])
            sources=[c.args[0]for c in script.exports_sync.query.call_args_list]
            self.assertFalse(any('REA_PLAYER_QUERY=api'in s or 'bindsession'in s or 'barrack'in s.lower()for s in sources))
            self.assertTrue(any('REA_PLAYER_QUERY_UI.release()'in s for s in sources))
            self.assertIsNone(client.profile_cache.get(scope,user_id=profile()['display_id']))


class HallProfileSessionTests(unittest.TestCase):
    """A hall query owns the shared manual-query gate even while the map worker is waiting for a map."""

    def test_no_world_worker_idle_double_click_and_account_change(self):
        """Explicit clicks alone create work, and old-account events are marked stale."""
        events=queue.Queue();entered=threading.Event();release=threading.Event()
        def query(*args):
            """Hold one fake profile read without accessing a game connection."""
            entered.set();release.wait(2);return profile()
        fake=Mock(side_effect=query);actor=HallProfileSession(events,fake)
        worker=Worker(queue.Queue());self.assertIsNone(worker.connection)
        actor.submit(profile()['display_id'],worker);self.assertTrue(entered.wait(1));self.assertTrue(worker.player_busy)
        with self.assertRaises(RuntimeError):actor.submit(profile()['display_id'],worker)
        actor.cancel_pending();release.set();actor.job.join(2)
        self.assertFalse(worker.player_busy);fake.assert_called_once()
        self.assertNotEqual(events.get_nowait()['hall_profile_generation'],actor.generation)
        actor.close()

    def test_ui_no_longer_requires_ready_or_a_worker(self):
        """The direct public-ID page delegates to the hall actor even when the world worker does not exist."""
        loader=SourceFileLoader('hall_profile_app_test',str(Path(__file__).with_name('app.pyw')))
        spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
        app=module.App.__new__(module.App)
        app.login_busy=False;app.closing=False;app.ready=False;app.worker=None;app.hall_profile=Mock()
        app.player_panel=Mock();app.player_panel.player_id.get.return_value='7';app.league_members_panel=Mock()
        app.query_player();app.hall_profile.submit.assert_called_once_with('7',None)
        app.clear_player_cache();app.hall_profile.submit.assert_called_with(None,None,clear_cache=True)


if __name__=='__main__':unittest.main()
