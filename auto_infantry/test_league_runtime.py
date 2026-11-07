"""Run the actual alliance Lua guards in an isolated native-game model, without network requests."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from lupa import LuaRuntime
from test_hero_runtime import MOCK_GAME
from test_collection_runtime import COLLECTION_GAME
from test_monster_runtime import HUNT_GAME
from connection import Connection

LEAGUE_GAME = r'''
local old=CSLTypes.ModelManager.sharedInstance()
local main=old:getModel('main')
main.getMyLeagueId=function() return 7 end
CSLTypes.SLGLeagueModel='league'
local league={}
league.getTSLGLeagueGetAllBuildRsp=function(self) return self.build end
league.getTSLGLeagueGetResourceRsp=function(self) return self.detail end
CSLTypes.ModelManager.sharedInstance=function() return {getModel=function(self,name)
 if name=='league' then return league else return old:getModel(name) end
end} end
local search=CSLTypes.DBSearcher.sharedInstance
CSLTypes.DBSearcher.sharedInstance=function()
 local s=search();s.searchTLeagueResource=function() return {[2]=3,[3]='联盟铁矿',[11]=Game.mineCapacity or 30} end
 return s
end
Game.target=151610;Game.mineStock=100000
local function point()
 return {[1]={125,178,0},[2]=Game.target,[3]=10003,[5]=Game.mineStock,[6]=list({}),[9]=Game.foreign and 8 or 7}
end
local controller={}
controller.sendTSLGLeagueGetAllBuildReq=function()
 league.build={[1]=0,[5]=not Game.noMine and point() or nil}
end
controller.sendTSLGLeagueGetResourceReq=function(self,id)
 assert(id==Game.target)
 local rows={}
 for i=1,(Game.mineOccupied or 0) do rows[#rows+1]={[1]=i,own=Game.ownPresent} end
 league.detail={0,point(),list(rows)}
end
CSLTypes.SLGLeagueController={getInstance=function() return controller end}
local notifier=CSLTypes.SceneNotifier.getInstance()
package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq=function(target,aim)
 assert(aim==12)
 local h={[1]={[1]={[3]=303},[2]=Game.state,[3]=Game.finish},[2]=list({{411,Game.followerStock}}),
  [3]=511,[4]=Game.base,[5]=47150,[6]=338,[7]=Game.per}
 notifier:notifyUpdateData(1060,{0,target,aim,list({h}),{125,178,0},19})
 main:notifyStateChange(-9991)
end
package.loaded.SLGChooseHeroLogicLeagueCollect={__instanceDict={
 getEnemyCombatValue=function() return 0 end,
 getTargetID2=function(self) return self._scene:getContent()[6] end,
 startTrip2=function(self,unused,flag)
  assert(unused==nil and flag==false)
  local h=self._scene:getSelectedHero()
  Game.trips[#Game.trips+1]={hero=h[1][1][3],target=self._scene:getContent()[2],
   secondary=self:getTargetID2(),soldiers=self._scene:getSoldierInfoList()}
 end}}
'''


class LeagueRuntimeTests(unittest.TestCase):
    """Protect native formation, identity/freshness guards, existing armies and popup cleanup."""

    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        for source in (MOCK_GAME, COLLECTION_GAME, HUNT_GAME, LEAGUE_GAME):
            self.lua.execute(source)
        for name in ('hero_runtime.lua', 'league_runtime.lua'):
            self.lua.execute(Path(__file__).with_name(name).read_text(encoding='utf-8'))

    def prepare(self, change=''):
        """Deliver fresh building/detail/hero/army responses without invoking a sender."""
        self.lua.execute('Game.finish=0;' + change + ';REA_AUTO_INFANTRY.hero_refresh();'
                         'REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.league_build_query();'
                         'REA_AUTO_INFANTRY.league_build_result();'
                         'REA_AUTO_INFANTRY.league_mine_query(Game.target);REA_AUTO_INFANTRY.league_mine_result();'
                         'REA_AUTO_INFANTRY.league_heroes_query();REA_AUTO_INFANTRY.league_heroes_result()')

    def test_delayed_schedule_read_refreshes_existing_army_once_without_departure(self):
        """A slow UI-thread callback must not stop an existing alliance collector solely on an expired snapshot."""
        self.prepare('Game.ownArmy={[1]=77,[4]=6,[5]=12,[6]=151610,[11]=2000000,[15]={[1]=303}}')
        self.lua.execute('Game.time=Game.time+3001')
        c=Connection();c.script=Mock()
        c.script.exports_sync.query.side_effect=lambda source,*args:self.lua.execute(source)
        c.refresh_heroes=Mock(side_effect=lambda:self.lua.execute(
            'REA_AUTO_INFANTRY.hero_refresh();return REA_AUTO_INFANTRY.hero_list()'))
        schedule=c.league_call('league_schedule')
        self.assertEqual(schedule['stages'][0]['army_id'],77)
        c.refresh_heroes.assert_called_once_with()
        self.assertEqual(c.script.exports_sync.query.call_count,2)
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_native_default_and_at_most_once_reservation(self):
        """The native positions/counts and secondary target pass unchanged; uncertainty cannot resend."""
        self.prepare('Game.capacity=3;Game.nativeLeft=8;Game.nativeRight=7')
        result = self.lua.execute('return pcall(REA_AUTO_INFANTRY.league_dispatch,Game.target,303)')
        self.assertTrue(result[0], result)
        trip = self.lua.globals().Game.trips[1]
        self.assertEqual((trip['hero'], trip['target'], trip['secondary']), (303, 151610, 19))
        self.assertEqual([trip['soldiers'][i][2] for i in (1, 2)], [1, 2])
        self.assertEqual([trip['soldiers'][i][3] for i in (1, 2)], [8, 7])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.league_dispatch,Game.target,303)')[0])
        self.assertEqual(len(self.lua.globals().Game.trips), 1)

    def test_final_guards_do_not_reach_native_sender(self):
        """A late cooldown/army/stock/world/native eligibility change blocks all native spending."""
        for change in ('Game.finish=Game.time+1000;REA_AUTO_INFANTRY.hero_refresh()',
                       'Game.followerStock=0;REA_AUTO_INFANTRY.league_heroes_query()',
                       'Game.nativeBlockStart=true', 'Game.visible=false', 'Game.mineStock=0;'
                       'REA_AUTO_INFANTRY.league_mine_query(Game.target);REA_AUTO_INFANTRY.league_mine_result();'
                       'REA_AUTO_INFANTRY.league_heroes_query()',
                       'Game.time=Game.time+4000',
                       "CSLTypes.ModelManager.sharedInstance():getModel('main').mTSLGLoginMapRsp={}"):
            with self.subTest(change=change):
                self.setUp()
                self.prepare()
                self.lua.execute(change)
                result = self.lua.execute('return pcall(REA_AUTO_INFANTRY.league_dispatch,Game.target,303)')
                self.assertFalse(result[0], result)
                self.assertEqual(len(self.lua.globals().Game.trips), 0)

    def test_existing_returning_manual_army_blocks_another_departure(self):
        """Own aim12 armies stay visible and block duplicates even when returning from an old mine."""
        self.prepare('Game.ownArmy={[1]=99,[4]=9,[5]=12,[6]=123,[11]=Game.time+10000,[15]={[1]=303}}')
        schedule = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.league_schedule()'))
        self.assertEqual(schedule['stages'][0]['end_ms'], 1010000)
        self.assertEqual(schedule['stages'][0]['target_id'], 123)
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.league_dispatch,Game.target,303)')[0])

    def test_absent_mine_never_uses_old_cached_target_and_rebuild_discovers_new_id(self):
        """11114 is authoritative; a removed/rebuilt resource is not replaced by a stale map-cache fallback."""
        self.prepare()
        self.lua.execute('Game.noMine=true;REA_AUTO_INFANTRY.league_build_query()')
        self.assertFalse(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.league_build_result()'))['found'])
        self.lua.execute('Game.noMine=false;Game.target=151611;REA_AUTO_INFANTRY.league_build_query()')
        self.assertEqual(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.league_build_result()'))['target_id'], 151611)

    def test_exact_popup_capture_and_callback_cleanup(self):
        """Native unrelated UI events are forwarded and closing removes only our wrappers/observer."""
        self.prepare()
        self.assertIsNone(self.lua.globals().Game.forwardScene)
        self.lua.execute("CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{0,999,1})")
        self.assertEqual(self.lua.globals().Game.forwardScene, 1)
        self.lua.execute('REA_AUTO_INFANTRY.league_close()')
        self.assertIsNone(self.lua.globals().Game.tripObserver)
        self.lua.execute("CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{0,151610,12})")
        self.assertEqual(self.lua.globals().Game.forwardScene, 2)
