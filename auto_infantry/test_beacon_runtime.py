"""Run the production beacon Lua against isolated native models; every game sender is a fake."""
import json
import unittest
from pathlib import Path

from lupa import LuaRuntime
from test_hero_runtime import MOCK_GAME
from test_collection_runtime import COLLECTION_GAME
from test_monster_runtime import HUNT_GAME

BEACON_GAME = r'''
local main=CSLTypes.ModelManager.sharedInstance():getModel('main')
Game.events={{[1]={{101,59,0},10,1010},[2]=1,[3]=0,[4]=0,[5]=0,[6]=0}}
Game.infoQueries=0;Game.candidateQueries=0;Game.recalls={};Game.claims={};Game.beaconLimit=4
main.getTSLGGetBeaconTowerInfoRsp=function() return Game.beacon end
main.getTSLGBeaconTowerEventByCommObjID=function(self,id)
 for _,e in ipairs(Game.events) do if e[1][2]==id then return e end end
end
main.getMaxFengHuoTaiArmyCount=function() return Game.beaconLimit end
main.checkMaxFengHuoTaiArmyCount=function()
 local n=0;for _,e in ipairs(Game.events) do if e[1][3]~=1011 and e[3]~=0 and e[3]~=3 then n=n+1 end end
 return n>=Game.beaconLimit
end
local oldSearch=CSLTypes.DBSearcher.sharedInstance
CSLTypes.DBSearcher.sharedInstance=function()
 local s=oldSearch();s.searchTMapIntelStation_Event_Map=function(self,id) return {[2]=id} end;return s
end
local ctrl=package.loaded.SLGMainController.__instanceDict
ctrl.sendTSLGGetBeaconTowerInfoReq=function()
 Game.infoQueries=Game.infoQueries+1
 Game.beacon={0,10,133,list(Game.events),Game.refreshRemaining or 60,Game.beaconLimit}
end
CSLTypes.SLGMainController={getInstance=function() return ctrl end}
local panel=function() end;local button=function() end
package.loaded.SLGFengHuoTaiSaveDialog={__instanceDict={onSaveClick=button}}
local saved=debug.getupvalue
debug.getupvalue=function(fn,i)
 if fn==button then return 'CollectPopupChooseHeroPanel',panel end
 if fn==panel then if i==1 then return 'T_TYPE',{E_SLG_ARMY_AIM_TYPE_BEACON_TOWER_EVENT=45} end;return nil end
 return saved(fn,i)
end
local notifier=CSLTypes.SceneNotifier.getInstance()
ctrl.sendTSLGGetAvailHeroListReq=function(id,aim)
 Game.candidateQueries=Game.candidateQueries+1;assert(aim==45)
 local e=main:getTSLGBeaconTowerEventByCommObjID(id)
 local h={[1]={[1]={[3]=303},[2]=Game.state,[3]=Game.finish},[2]=list({{411,Game.followerStock}}),
  [3]=6,[4]=Game.base,[7]=Game.per,[8]=100}
 notifier:notifyUpdateData(1060,{[1]=0,[2]=id,[3]=aim,[4]=list({h}),[5]=e[1][1],[6]=0,[11]=0})
 main:notifyStateChange(-9991)
end
local lm={getEnemyCombatValue=function() return 0 end,getTargetID2=function(self) return self._scene:getContent()[6] end}
lm.startTrip=function(self)
 local c=self._scene:getContent();local h=self._scene:getSelectedHero()
 Game.trips[#Game.trips+1]={aim=c[3],target=c[2],hero=h[1][1][3],soldiers=self._scene:getSoldierInfoList()}
end
package.loaded.SLGChooseHeroLogicFengHuoTaiSave={__instanceDict=lm}
package.loaded.SLGChooseHeroScene.__instanceDict.getFirstHandValue=function(self) return self._currentSelectedHero[8] end
ctrl.sendTSLGRetreatArmyReq=function(id) Game.recalls[#Game.recalls+1]=id end
ctrl.sendTSLGGetBeaconTowerEventRewardReq=function(self,id) Game.claims[#Game.claims+1]=id end
'''


class BeaconLuaTests(unittest.TestCase):
    """Guard event type, native formation, attribution, freshness and side-effect-free cleanup."""

    def setUp(self):
        """Load the actual modules with one visible unstarted rescue and a ready hero."""
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        for source in (MOCK_GAME,COLLECTION_GAME,HUNT_GAME,BEACON_GAME):
            self.lua.execute(source)
        for file in ('hero_runtime.lua','beacon_runtime.lua'):
            self.lua.execute(Path(__file__).with_name(file).read_text(encoding='utf-8'))
        self.lua.execute('Game.finish=0;Game.capacity=4;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();'
                         'REA_AUTO_INFANTRY.beacon_info_query();REA_AUTO_INFANTRY.beacon_snapshot()')

    def call(self, source):
        """Return a single Lua result without a Frida bridge or emulator."""
        return self.lua.execute(source)

    def prepare_candidate(self):
        """Read the exact target once while ensuring the native UI callbacks remain suppressed."""
        self.call('REA_AUTO_INFANTRY.beacon_candidates_query(10)')

    def test_native_aim_default_followers_and_one_shot_reservation(self):
        """The production adapter sends aim45 with native defaults and blocks a duplicate attempt."""
        self.prepare_candidate()
        result=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_dispatch(10,303)'))
        self.assertEqual((result['aim'],result['followers']),(45,4))
        self.assertEqual(self.lua.globals().Game.trips[1]['soldiers'][1][2],2)
        self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_dispatch,10,303)')[0])
        self.assertEqual(len(self.lua.globals().Game.trips),1)

    def test_nonrescue_types_never_query_depart_recall_or_claim(self):
        """A shared protocol is not authorization to act on monsters, resources or treasure."""
        for kind in (2,3,4):
            self.setUp();self.call(f'Game.events[1][2]={kind}')
            for source in ('REA_AUTO_INFANTRY.beacon_candidates_query,10',
                           'REA_AUTO_INFANTRY.beacon_dispatch,10,303',
                           'REA_AUTO_INFANTRY.beacon_recall,10,303,77',
                           'REA_AUTO_INFANTRY.beacon_claim,10'):
                self.assertFalse(self.call('return pcall('+source+')')[0])
            self.assertEqual(self.lua.globals().Game.candidateQueries,0)
            self.assertEqual(len(self.lua.globals().Game.trips),0)
            self.assertEqual(len(self.lua.globals().Game.claims),0)

    def test_busy_cooling_stale_and_full_queue_block_before_send(self):
        """Recheck final eligibility even when Python previously selected this hero."""
        for change in ('Game.finish=Game.time+100000;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()',
                       'Game.state=1;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()',
                       'Game.time=Game.time+3001','Game.beaconLimit=1;Game.events[1][3]=1'):
            self.setUp();self.prepare_candidate();self.call(change)
            self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_dispatch,10,303)')[0])
            self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_recall_requires_arrival_exact_army_and_fresh_busy_hero(self):
        """Marching, foreign and returning armies cannot enter the shortcut."""
        for state,event_state,army_id in ((2,1,77),(2,2,77),(9,2,77),(6,2,78)):
            self.setUp()
            self.call(f'Game.ownArmy={{[1]=77,[4]={state},[5]=45,[6]=10,[11]=2000000,[15]={{[1]=303}}}};'
                      f'Game.events[1][3]={event_state};Game.events[1][4]={army_id};'
                      'REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')
            self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_recall,10,303,77)')[0])
        self.setUp()
        self.call('Game.ownArmy={[1]=77,[4]=6,[5]=45,[6]=10,[11]=2000000,[15]={[1]=303}};'
                  'Game.events[1][3]=2;Game.events[1][4]=77;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')
        self.call('REA_AUTO_INFANTRY.beacon_recall(10,303,77)')
        self.assertEqual(self.lua.globals().Game.recalls[1],77)
        self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_recall,10,303,77)')[0])

    def test_claim_only_completed_rescue_and_never_twice(self):
        """State3 must be native-confirmed, and an uncertain first claim cannot be resubmitted."""
        self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_claim,10)')[0])
        self.call('Game.events[1][3]=3;REA_AUTO_INFANTRY.beacon_claim(10)')
        self.assertEqual(self.lua.globals().Game.claims[1],10)
        self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_claim,10)')[0])

    def test_refresh_anchor_does_not_slide_and_watch_ignores_query_generations(self):
        """A cached relative60s refresh duration retains one deadline despite local reads and new GET responses."""
        first=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_snapshot()'))
        signature=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_watch()'))
        self.call('Game.time=Game.time+5000')
        second=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_snapshot()'))
        self.assertEqual(first['refresh_end_ms'],second['refresh_end_ms'])
        self.call('REA_AUTO_INFANTRY.beacon_info_query();REA_AUTO_INFANTRY.beacon_snapshot()')
        self.assertEqual(signature,json.loads(self.call('return REA_AUTO_INFANTRY.beacon_watch()')))
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_queue_excludes_treasure_and_cleanup_restores_callbacks(self):
        """Snapshot display retains all types while native capacity excludes treasure and finished events."""
        self.call('Game.events={{{{101,59,0},10,1010},1,2,77,0,2000},'
                  '{{{102,59,0},11,1011},2,2,0,0,0},{{{103,59,0},12,1012},3,3,0,0,0}};'
                  'REA_AUTO_INFANTRY.beacon_info_query()')
        state=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_snapshot()'))
        self.assertEqual((state['queue_used'],state['queue_limit'],len(state['events'])),(1,4,3))
        self.call('REA_AUTO_INFANTRY.beacon_close()')
        self.assertIsNone(self.lua.globals().Game.mainObserver)
        self.call('CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{0,10,45,list({})})')
        self.assertEqual(self.lua.globals().Game.forwardScene,1)

    def test_returning_armies_count_after_claimed_events_disappear(self):
        """The reproduced2 active+2 returning case occupies4 slots, with no double count of active event rows."""
        self.call('Game.events[1][3]=2;Game.events[1][4]=77;'
            'Game.ownArmies={{[1]=77,[4]=6,[5]=45,[6]=10,[11]=2000000,[15]={[1]=303}},'
            '{[1]=78,[4]=6,[5]=45,[6]=11,[11]=2000000,[15]={[1]=303}},'
            '{[1]=79,[4]=9,[5]=45,[6]=12,[11]=1100000,[15]={[1]=303}},'
            '{[1]=80,[4]=9,[5]=45,[6]=13,[11]=1100000,[15]={[1]=303}}};'
            'REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')
        state=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_snapshot()'))
        self.assertEqual((state['queue_used'],state['queue_full']),(4,True))
        self.assertEqual(state['returning_count'],2)

    def test_final_sender_counts_return_and_only_rejected_reservation_can_release(self):
        """Python's earlier free-slot plan cannot bypass a newly observed returning army at final send time."""
        self.prepare_candidate()
        self.call('Game.beaconLimit=1;Game.ownArmy={[1]=77,[4]=9,[5]=45,[6]=11,[11]=1100000,[15]={[1]=303}};'
                  'REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();'
                  'REA_AUTO_INFANTRY.beacon_info_query();REA_AUTO_INFANTRY.beacon_snapshot()')
        result=json.loads(self.call('return REA_AUTO_INFANTRY.beacon_dispatch(10,303)'))
        self.assertEqual((result['not_sent'],result['reason']),(True,'capacity_full'))
        self.assertEqual(len(self.lua.globals().Game.trips),0)
        self.setUp();self.prepare_candidate()
        self.call('REA_AUTO_INFANTRY.beacon_dispatch(10,303)')
        self.assertFalse(self.call('return pcall(REA_AUTO_INFANTRY.beacon_rejected,10,6012)')[0])
        self.call('REA_AUTO_INFANTRY.beacon_rejected(10,6395);REA_AUTO_INFANTRY.beacon_dispatch(10,303)')
        self.assertEqual(len(self.lua.globals().Game.trips),2)


if __name__=='__main__':
    unittest.main()
