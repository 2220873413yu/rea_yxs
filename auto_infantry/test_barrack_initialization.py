"""Reproduce empty post-switch barrack caches through the real Lua and Python startup paths."""
import json
import unittest
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from lupa import LuaRuntime

from connection import Connection
from test_hero_runtime import MOCK_GAME


class BarrackInitializationTests(unittest.TestCase):
    """Only a new successful read response may finish initialization; no spending is ever enabled."""

    def setUp(self):
        """Use an absent initial cache and the real installation chunk with isolated native constructors."""
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_GAME)
        self.lua.execute(r'''
Game.barrack=nil;Game.barrackQueries=0;Game.barrackMode='success'
local manager=CSLTypes.ModelManager.sharedInstance()
local model=manager:getModel(CSLTypes.SLGBuildingsModel)
local items=manager:getModel(CSLTypes.ItemsModel)
model.getTSLGGetBarrackRsp=function() return Game.barrack end
items.getItemCount=function() return Game.stock end
function Game.deliverBarrack(ret)
 Game.barrack={[1]=ret,[4]={get_Item=function(self,id)
  return {[1]=675,[2]=6,[3]={[1]=38,[2]=0,[3]=0,[4]=0},[6]=54}
 end}}
end
local ctrl=package.loaded.SLGBuildingsController.__instanceDict._instance
ctrl.sendTSLGTrainSoldierReq=function() error('spending forbidden') end
ctrl.sendTSLGBuildSpeedupReq=function() error('spending forbidden') end
ctrl.sendTSLGGetBarrackReq=function()
 Game.barrackQueries=Game.barrackQueries+1
 if Game.barrackMode=='success' then Game.deliverBarrack(0)
 elseif Game.barrackMode=='rejected' then Game.deliverBarrack(6012) end
end
package.loaded['jit.util']={funcinfo=function(fn)
 return {params=fn==ctrl.sendTSLGTrainSoldierReq and 2 or 5}
end}
debug.getupvalue=function() return 'T_TItemInfo',io.stdout end
''')
        self.result = self.lua.execute(Path(__file__).with_name('runtime.lua').read_text(encoding='utf-8'))
        self.connection = Connection()
        self.connection.script = Mock()

        def query(source, spending=False, *args):
            """Execute actual Lua against the fake world while rejecting any attempt to open a spending gate."""
            self.assertFalse(spending)
            return self.lua.execute(source)

        self.connection.script.exports_sync.query.side_effect = query

    def test_empty_cache_installs_then_queries_before_reading_status(self):
        """Account switching can leave nil cache; install must succeed until one fresh response arrives."""
        self.assertEqual(self.result, 'troop_api_installed')
        before = self.connection.call('barrack_probe')
        self.assertFalse(before['received'])
        with self.assertRaises(Exception):
            self.connection.call('status')
        state = self.connection.initialize_barracks()
        self.assertEqual((state['count'], state['limit']), (38, 54))
        self.assertEqual(self.lua.globals().Game.barrackQueries, 1)

    def test_old_successful_cache_cannot_substitute_for_a_new_response(self):
        """A stale successful old-account response is insufficient when this new query has no reply."""
        self.lua.execute("Game.deliverBarrack(0);Game.barrackMode='no_reply'")
        with patch('connection.time.monotonic', side_effect=[0, 0, 7]), patch('connection.time.sleep'):
            with self.assertRaises(TimeoutError):
                self.connection.initialize_barracks()
        self.assertEqual(self.lua.globals().Game.barrackQueries, 1)

    def test_new_failure_or_no_response_never_enters_normal_initialization(self):
        """An explicit response error fails promptly; no reply stops at timeout without retrying."""
        self.lua.execute("Game.barrackMode='rejected'")
        with self.assertRaisesRegex(RuntimeError, '6012'):
            self.connection.initialize_barracks()
        self.assertEqual(self.lua.globals().Game.barrackQueries, 1)

    def test_map_switch_between_install_and_request_stops_before_sending(self):
        """The read-only bootstrap still honors the existing map/session boundary guard."""
        self.lua.execute('CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel).mTSLGLoginMapRsp={}')
        with self.assertRaises(Exception):
            self.connection.initialize_barracks()
        self.assertEqual(self.lua.globals().Game.barrackQueries, 0)


class WorldReadinessTests(unittest.TestCase):
    """Starting in the lobby waits locally and never sends a request using old-account caches."""

    def test_lobby_waits_until_new_map_is_ready_without_querying_game_data(self):
        """Repeated local probes do not trigger initialization or duplicate waiting messages."""
        connection = Connection()
        connection.script = Mock()
        connection.script.exports_sync.query.side_effect = [
            '{"ready":false,"stage":"MainHallSceneStage"}',
            '{"ready":false,"stage":"MainHallSceneStage"}',
            '{"ready":false,"stage":"SLGMapStage"}',
            '{"ready":true,"stage":"SLGMapStage"}']
        messages = []
        with patch('connection.time.sleep'):
            connection.wait_world_ready(messages.append)
        self.assertEqual(len(messages), 3)
        self.assertIn('大厅', messages[0])
        self.assertIn('正在查询', messages[-1])
        for call in connection.script.exports_sync.query.call_args_list:
            self.assertNotIn('sendTSLG', call.args[0])
            self.assertNotIn('REA_AUTO_INFANTRY', call.args[0])

    def test_close_cancels_lobby_wait_without_initializing_or_enabling_any_switch(self):
        """Cancellation interrupts the readiness wait and lets the normal connection cleanup run."""
        connection = Connection()
        connection.script = Mock()
        connection.script.exports_sync.query.return_value = '{"ready":false,"stage":"MainHallSceneStage"}'
        cancel = threading.Event()
        with patch.object(cancel, 'wait', side_effect=lambda timeout: cancel.set()):
            with self.assertRaises(InterruptedError):
                connection.wait_world_ready(cancel=cancel)
        self.assertEqual(connection.script.exports_sync.query.call_count, 1)
        connection.script.exports_sync.setenabled.assert_not_called()
        connection.script.exports_sync.setheroenabled.assert_not_called()
        connection.script.exports_sync.setcollectenabled.assert_not_called()
