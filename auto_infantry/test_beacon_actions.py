"""Exercise production per-type Lua policies using protocol-only fakes, without game traffic."""
import json
import unittest
from pathlib import Path

from lupa import LuaRuntime
from test_hero_runtime import MOCK_GAME
from test_collection_runtime import COLLECTION_GAME
from test_monster_runtime import HUNT_GAME
from test_beacon_runtime import BEACON_GAME

EXTRA=r'''
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel('main');local building=manager:getModel('building')
building.addObserver=function(self,o) Game.stockObserver=o end
building.removeObserver=function(self,o) if Game.stockObserver==o then Game.stockObserver=nil end end
local ctrl=package.loaded.SLGBuildingsController.__instanceDict._instance
ctrl.sendTSLGGetSoldierNumReq=function(self,id)
 assert(id==803);Game.stockObserver:updateSelf({id=11116,addData={803,Game.scouts or 3,3,20}})
end
local saved=CSLTypes.DBSearcher.sharedInstance
CSLTypes.DBSearcher.sharedInstance=function()
 local s=saved();s.searchTTMapIntelStation_Resource_Map=function() return {} end
 s.searchGlobalVariable=function() return {103010,'10'} end;return s
end
package.loaded.SLGFengHuoTaiResourceCommonDialog={__instanceDict={canCollect=function(self)
 assert(self.resourceConfig and self.mTSLGResourceInfoRsp);return Game.canCollect end}}
local save=package.loaded.SLGChooseHeroLogicFengHuoTaiSave.__instanceDict
local monster={};for k,v in pairs(save) do monster[k]=v end
monster.getEnemyCombatValue=function(self) assert(self._scene:getContent()[6]==100101);return Game.enemy end
package.loaded.SLGChooseHeroLogicMonster={__instanceDict=monster}
local resource={};for k,v in pairs(save) do resource[k]=v end
resource.startTrip2=save.startTrip
package.loaded.SLGChooseHeroLogicCollectResource={__instanceDict=resource}
local notifier=CSLTypes.SceneNotifier.getInstance()
local c=package.loaded.SLGMainController.__instanceDict
c.sendTSLGGetMonsterDetailReq=function(id)
 notifier:notifyUpdateData(1223,{0,id,20101,0,100101,{101,59,0}})
 main:notifyUpdateData(-9956,{0,id})
end
c.sendTSLGGetAvailHeroListReq=function(id,aim,quest)
 Game.lastQuest=quest
 local h={[1]={[1]={[3]=303},[2]=Game.state,[3]=Game.finish},[2]=list({{411,Game.followerStock}}),
  [3]=6,[4]=Game.base,[5]=40000,[6]=300,[7]=Game.per,[8]=100}
 notifier:notifyUpdateData(1060,{[1]=0,[2]=id,[3]=aim,[4]=list({h}),[5]={101,59,0},[6]=quest,[11]=0})
 main:notifyStateChange(-9991)
end
main._myScoutInfoList=list({})
local awake=function() end;local scout=function(context)
 Game.scoutCalls=(Game.scoutCalls or 0)+1;Game.scoutPosition=context.mScoutGoalPos
end
package.loaded.SLGScoutDialog={__instanceDict={Awake=awake}}
local old=debug.getupvalue
debug.getupvalue=function(fn,i) if fn==awake then return 'confirm',scout end;return old(fn,i) end
'''


class BeaconActionsTests(unittest.TestCase):
    """Keep native selection, formation and final sender guards real while replacing all external effects."""

    def setUp(self):
        """Load both production modules against a fresh visible event with an idle hero."""
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        for source in (MOCK_GAME,COLLECTION_GAME,HUNT_GAME,BEACON_GAME,EXTRA):self.lua.execute(source)
        for name in ('hero_runtime.lua','beacon_runtime.lua','beacon_actions.lua'):
            self.lua.execute(Path(__file__).with_name(name).read_text(encoding='utf-8'))
        self.lua.execute('Game.finish=0;Game.capacity=4;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();'
                         'REA_AUTO_INFANTRY.beacon_info_query();REA_AUTO_INFANTRY.beacon_snapshot();REA_AUTO_INFANTRY.beacon_configure(15)')

    def prepare(self,kind):
        """Deliver the exact target detail before the native availability query."""
        self.lua.execute(f'Game.events[1][2]={kind};REA_AUTO_INFANTRY.beacon_target_query(10);'
                         'REA_AUTO_INFANTRY.beacon_target_result();REA_AUTO_INFANTRY.beacon_candidates_query(10)')

    def result(self):
        """Decode the actual candidate output, retaining real native total-power calculations."""
        return json.loads(self.lua.execute('return REA_AUTO_INFANTRY.beacon_candidates_result()'))

    def test_monster_quest_argument_native_power_and_departure(self):
        """A beacon monster uses detail1223's quest ID, aim45 and the unchanged native default formation."""
        self.prepare(4)
        row=self.result()['heroes'][0]
        self.assertEqual((row['power'],row['ready'],row['overwhelming']),(190,True,True))
        self.assertEqual(self.lua.globals().Game.lastQuest,100101)
        self.lua.execute('REA_AUTO_INFANTRY.beacon_dispatch(10,303)')
        self.assertEqual(self.lua.globals().Game.trips[1]['aim'],45)

    def test_weak_monster_or_missing_skip_permission_never_departs(self):
        """Numeric superiority alone is insufficient; the native victory recommendation must qualify."""
        for change in ('Game.enemy=180','Game.skipAllowed=false'):
            self.setUp();self.lua.execute(change);self.prepare(4)
            self.assertFalse(self.result()['heroes'][0]['ready'])
            self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_dispatch,10,303)')[0])
            self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_shortage_is_unknown_strength_and_resource_uses_native_sender(self):
        """Lacking troops must not blacklist a monster as weak; resources keep their native formation."""
        self.lua.execute('Game.followerStock=1');self.prepare(4)
        row=self.result()['heroes'][0]
        self.assertFalse(row['ready']);self.assertFalse(row['strength_known'])
        self.setUp();self.prepare(3)
        self.lua.execute('REA_AUTO_INFANTRY.beacon_dispatch(10,303)')
        self.assertEqual(self.lua.globals().Game.trips[1]['soldiers'][1][2],2)

    def test_resource_native_permission_speed_load_and_no_early_recall(self):
        """Resource heroes use target metrics and native permission, never the rescue recall shortcut."""
        self.prepare(3);row=self.result()['heroes'][0]
        self.assertEqual((row['speed'],row['load'],row['ready']),(300,40000,True))
        self.lua.execute('Game.canCollect=false')
        self.assertFalse(self.result()['heroes'][0]['ready'])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_dispatch,10,303)')[0])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_recall,10,303,77)')[0])

    def test_treasure_cost_existing_stock_and_one_shot_no_purchase(self):
        """A distance21 treasure costs three scouts by native config; only one confirm call can be made."""
        self.lua.execute('Game.events[1][2]=2;Game.distance=21;REA_AUTO_INFANTRY.beacon_scout_query(10)')
        state=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.beacon_scout_result(10)'))
        self.assertEqual((state['cost'],state['stock'],state['eligible']),(3,3,True))
        self.lua.execute('REA_AUTO_INFANTRY.beacon_scout(10)')
        self.assertEqual(self.lua.globals().Game.scoutCalls,1)
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_scout,10)')[0])
        self.assertEqual(len(self.lua.globals().Game.sends),0)

    def test_scout_insufficient_stale_and_manual_inbound_are_blocked(self):
        """A pre-existing scout journey, stale stock or shortage cannot trigger another scout or purchase."""
        for change in ('Game.distance=40','Game.time=Game.time+3001',
                       'CSLTypes.ModelManager.sharedInstance():getModel("main")._myScoutInfoList:Add({0,2000,list({{101,59,0}})})'):
            self.setUp();self.lua.execute('Game.events[1][2]=2;REA_AUTO_INFANTRY.beacon_scout_query(10);'+change)
            self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_scout,10)')[0])
            self.assertIsNone(self.lua.globals().Game.scoutCalls)

    def test_selected_types_guard_claim_and_arrived_monster_skip(self):
        """Only an exact owned aim45 monster army may skip, and unselected rewards remain untouched."""
        self.lua.execute('Game.events[1][2]=4;Game.ownArmy={[1]=77,[4]=3,[5]=45,[6]=10,[11]=2000000,[15]={[1]=303}};'
                         'REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.beacon_skip(10,303,77)')
        self.assertEqual(self.lua.globals().Game.skipCalls,1)
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_skip,10,303,77)')[0])
        self.lua.execute('Game.events[1][3]=3;REA_AUTO_INFANTRY.beacon_configure(1)')
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.beacon_claim,10)')[0])
        self.lua.execute('REA_AUTO_INFANTRY.beacon_configure(8);REA_AUTO_INFANTRY.beacon_claim(10);REA_AUTO_INFANTRY.beacon_close()')
        self.assertEqual(len(self.lua.globals().Game.claims),1)
        self.assertIsNone(self.lua.globals().Game.stockObserver)

    def test_passive_watch_without_nonexistent_soldier_getter(self):
        """The real client lacks getSoldierInfoById; passive stock watching must use its barrack response."""
        self.lua.execute('CSLTypes.ModelManager.sharedInstance():getModel("building").getSoldierInfoById=nil')
        before=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.beacon_watch()'))['signature']
        self.lua.execute('Game.followerStock=Game.followerStock+1')
        after=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.beacon_watch()'))['signature']
        self.assertNotEqual(before,after)
        self.assertEqual(len(self.lua.globals().Game.trips),0)
        self.assertIsNone(self.lua.globals().Game.scoutCalls)


if __name__=='__main__':unittest.main()
