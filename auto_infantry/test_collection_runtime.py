"""Execute the production Lua final collection guard against isolated fake native models."""
import json
import unittest
from pathlib import Path

from lupa import LuaRuntime
from test_hero_runtime import MOCK_GAME

COLLECTION_GAME = r'''
local originalManager=CSLTypes.ModelManager.sharedInstance()
local main=originalManager:getModel('main')
local building=originalManager:getModel('building')
Game.queueFull=false;Game.canCollect=true;Game.infantry=2;Game.followerStock=2;Game.soldierId=411;Game.quantity=20000;Game.occupied=false;Game.trips={}
local map={getMyMainCityCoordinates=function() return {[1]=99,[2]=62} end}
local cachePoint={[1]={[2]=2792},[2]=32002,[4]=list({}),[6]=20000}
local points={GetDictKeys=function() return list({123}) end,get_Item=function() return cachePoint end}
local chunk={ContainsKey=function(self,kind) return kind==1000 end,get_Item=function() return points end}
map.mInViewDataChunkCacheManager={mtNewPlay_Map={[10]=250,[11]=250},getAllViewData=function() return list({{mViewDataCache=chunk}}) end}
CSLTypes.SLGMapObjectModel='map'
CSLTypes.SLGArmyTripModel='trip'
local trip={addObserver=function(self,observer) Game.tripObserver=observer end,
 removeObserver=function(self,observer) if Game.tripObserver==observer then Game.tripObserver=nil end end}
CSLTypes.ModelManager.sharedInstance=function() return {getModel=function(self,name)
 if name=='map' then return map elseif name=='trip' then return trip else return originalManager:getModel(name) end
end} end
main.checkIsMyArmy=function(army) return army.own==true end
main.isMyArmyExist_InResourceField=function() return Game.ownPresent==true end
main.addObserver=function(self,observer) Game.mainObserver=observer end
main.removeObserver=function(self,observer) if Game.mainObserver==observer then Game.mainObserver=nil end end
main.checkMaxCollectionArmyCount=function() return Game.queueFull end
main.getMaxCollectionArmyCount=function() return 2 end
main.notifyUpdateData=function() Game.forwardMain=(Game.forwardMain or 0)+1 end
main.notifyStateChange=function() Game.forwardState=(Game.forwardState or 0)+1 end
local notifier={addObserver=function(self,observer) Game.sceneObserver=observer end,
 removeObserver=function(self,observer) if Game.sceneObserver==observer then Game.sceneObserver=nil end end}
notifier.notifyUpdateData=function() Game.forwardScene=(Game.forwardScene or 0)+1 end
CSLTypes.SceneNotifier={getInstance=function() return notifier end}
CSLTypes.DBSearcher.sharedInstance=function() return {
 searchHeroInfoByStarAndGroup=function(self,star,id) return {[7]=tostring(id)} end,
 searchTNewPlay_Resource_Map=function() return {[2]=Game.resourceLevel or 2,[3]=3,[9]=Game.slotCapacity or 1} end} end
CSLTypes.SLGMapUtils={logicToDisplay=function(pos) return {[1]=pos[1],[2]=250-pos[2]} end,
 keyToPos=function() return {[1]=101,[2]=59} end,
 calMapP2PDistance=function() return Game.distance or 5 end}
package.loaded.SLGResourceCommonDialog={__instanceDict={canCollect=function(context)
 assert(context.mTSLGResourceInfoRsp and context.mTNewPlay_Resource)
 return Game.canCollect
end}}
local ctrl=package.loaded.SLGBuildingsController.__instanceDict._instance
ctrl.sendTSLGResourceInfo=function(self,target)
 local occupants=Game.occupied and {{}} or {}
 local point={[1]={[1]={[1]=101,[2]=59},[2]=target},[2]=32002,[4]=list(occupants),[6]=Game.quantity}
 main:notifyUpdateData(-9995,{[1]=0,[2]={[1]=point,[2]=list(occupants)}})
end
package.loaded.SLGMainController.__instanceDict._instance=ctrl
package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq=function(target,kind)
 local heroes={}
 local data={{id=303,state=Game.state,finish=Game.finish,speed=300}}
 for _,hero in ipairs(Game.extra or {}) do data[#data+1]=hero end
 for _,hero in ipairs(data) do heroes[#heroes+1]={[1]={[1]={[3]=hero.id},[2]=hero.state,[3]=hero.finish},
  [2]=list({{[1]=Game.soldierId,[2]=Game.followerStock}}),
  [3]=8,[4]=100,[5]=40000,[6]=hero.speed or 200} end
 notifier:notifyUpdateData(1060,{[1]=0,[2]=target,[3]=kind,[4]=list(heroes),
  [5]={[1]=101,[2]=59},[6]=0})
 main:notifyStateChange(-9991)
end
package.loaded.SLGMainController.__instanceDict.sendTSLGStartArmyTripReq=function(req) Game.trips[#Game.trips+1]=req end
package.loaded.SLGChooseHeroItem={__instanceDict={getActionState=function(hero)
 if hero[1][2]~=0 then return 2 elseif hero[1][3]>Game.time then return 5 else return 0 end
end}}
building.getTSLGGetBarrackRsp=function() return {[1]=0,[4]={get_Item=function(self,id)
 return {[3]={[1]=id==411 and Game.infantry or Game.followerStock}}
end}} end
local soldierInit=function() end
local tripFn=function() end
package.loaded.SLGChosenSoldier={__instanceDict={initialize=soldierInit}}
package.loaded.SLGChooseHeroLogicCollectResource={__instanceDict={startTrip2=tripFn}}
local oldUpvalue=debug.getupvalue
debug.getupvalue=function(fn,index)
 if fn==soldierInit then return 'T_TSoldierInfo','soldier'
 elseif fn==tripFn then if index==1 then return 'T_TSLGStartArmyTripReq','trip' else return 'T_TMakeArmyReq','army' end
 else return oldUpvalue(fn,index) end
end
'''


class CollectionLuaTests(unittest.TestCase):
    """Verify final main-thread checks, which remain authoritative even after Python chose a plan."""

    def setUp(self):
        """Load both real Lua modules into one fake game with spending isolated from any real account."""
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_GAME)
        self.lua.execute(COLLECTION_GAME)
        self.lua.execute(Path(__file__).with_name('hero_runtime.lua').read_text(encoding='utf-8'))
        self.lua.execute(Path(__file__).with_name('collection_runtime.lua').read_text(encoding='utf-8'))

    def prepare(self, changes='Game.finish=0'):
        """Deliver fresh hero, army and target responses before attempting a bounded guard scenario."""
        self.lua.execute(changes + ';REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();'
                         'REA_AUTO_INFANTRY.collect_query(2792)')

    def dispatch(self, detail=1, available=1, radius=20, x=101, y=191):
        """Call only the fake world's production guard and return its success/error pair."""
        return self.lua.execute(f'return pcall(REA_AUTO_INFANTRY.collect_dispatch,2792,303,3,2,{detail},{available},{radius},{x},{y})')

    def test_only_normal_two_follower_collection_packet_is_sent_once(self):
        """A permitted plan sends aim1, exact target, selected hero and two one-unit infantry entries."""
        self.prepare()
        self.assertTrue(self.dispatch()[0])
        req = self.lua.globals().Game.trips[1]
        self.assertEqual((req[1][1], req[2], req[4], req[5]), (303, 1, 2792, 0))
        self.assertEqual([req[1][2][i][1] for i in (1, 2)], [411, 411])
        self.assertEqual([req[1][2][i][2] for i in (1, 2)], [1, 1])
        self.assertEqual([req[1][2][i][3] for i in (1, 2)], [5, 1])
        self.assertFalse(self.dispatch()[0])
        self.assertEqual(len(self.lua.globals().Game.trips), 1)

    def test_cooling_busy_occupied_rule_failure_and_stock_never_dispatch(self):
        """Every uncertain or ineligible final condition fails before the sender is reached."""
        cases = ('Game.finish=Game.time+1000', 'Game.state=20', 'Game.busy=true', 'Game.queueFull=true',
                 'Game.canCollect=false', 'Game.occupied=true', 'Game.quantity=0', 'Game.infantry=1')
        for change in cases:
            with self.subTest(change=change):
                self.setUp()
                self.prepare('Game.finish=0;' + change)
                self.assertFalse(self.dispatch()[0])
                self.assertEqual(len(self.lua.globals().Game.trips), 0)

    def test_native_configured_shared_slots_allow_allies_but_block_full_own_and_enemy(self):
        """Run the actual final sender guard with occupied resources, including level5 capacity2."""
        cases = ((4, 2, False, True, True), (5, 2, False, True, True),
                 (6, 3, False, True, True), (4, 1, False, True, False),
                 (4, 2, True, True, False), (4, 2, False, False, False),
                 (4, 0, False, True, False))
        for level, capacity, own, native, expected in cases:
            with self.subTest(level=level, capacity=capacity, own=own, native=native):
                self.setUp()
                self.prepare(f'Game.finish=0;Game.resourceLevel={level};Game.slotCapacity={capacity};'
                             f'Game.occupied=true;Game.quantity=40000;Game.canCollect={str(native).lower()}')
                status = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))
                self.assertEqual((status['capacity'], status['occupants']), (capacity, 1))
                # Own presence can change after Python picked a plan: the Lua sender must recheck it.
                self.lua.execute(f'Game.ownPresent={str(own).lower()}')
                ok, result = self.lua.execute(f'return pcall(REA_AUTO_INFANTRY.collect_dispatch,2792,303,3,{level},1,1,20,101,191)')
                self.assertEqual(ok, expected, result)
                self.assertEqual(len(self.lua.globals().Game.trips), int(expected))

    def test_own_marching_or_collecting_target_blocks_even_when_field_reports_empty(self):
        """A different hero already heading to the resource must block a second team before arrival."""
        for state in (2,3,6):
            with self.subTest(state=state):
                self.setUp();self.prepare()
                self.lua.execute("local m=CSLTypes.ModelManager.sharedInstance():getModel('main');"
                    f"m._myActionState[2]:Add({{[1]=77,[4]={state},[5]=1,[6]=2792,[15]={{[1]=305}}}})")
                self.assertFalse(self.dispatch()[0])
                self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_other_destinations_hunts_and_returning_teams_do_not_block_free_resource(self):
        """The action-list filter applies to this resource's active collection, preserving normal other actions."""
        for state,aim,target in ((2,1,2793),(9,1,2792),(7,1,2792),(2,3,2792)):
            with self.subTest(state=state,aim=aim,target=target):
                self.setUp();self.prepare()
                self.lua.execute("local m=CSLTypes.ModelManager.sharedInstance():getModel('main');"
                    f"m._myActionState[2]:Add({{[1]=77,[4]={state},[5]={aim},[6]={target},[15]={{[1]=305}}}})")
                self.assertTrue(self.dispatch()[0])

    def test_follower_species_matches_the_selected_hero_response(self):
        """Reproduce the food failure: a cavalry-only hero must not receive fixed infantry followers."""
        for soldier_id in (412, 413):
            with self.subTest(soldier_id=soldier_id):
                self.setUp()
                self.prepare(f'Game.finish=0;Game.soldierId={soldier_id}')
                self.assertTrue(self.dispatch()[0])
                soldiers = self.lua.globals().Game.trips[1][1][2]
                self.assertEqual([soldiers[i][1] for i in (1, 2)], [soldier_id, soldier_id])

    def test_huo_guang_food_failure_uses_cavalry_in_the_corrected_packet(self):
        """Replay the observed hero242 selection: native cavalry413 replaces the rejected infantry411."""
        self.prepare('Game.finish=0;Game.soldierId=413;Game.extra={{id=242,state=0,finish=0,speed=400}}')
        ok, result = self.lua.execute('return pcall(REA_AUTO_INFANTRY.collect_dispatch,2792,242,3,2,1,1,20,101,191)')
        self.assertTrue(ok, result)
        req = self.lua.globals().Game.trips[1]
        self.assertEqual(req[1][1], 242)
        self.assertEqual([req[1][2][i][1] for i in (1, 2)], [413, 413])

    def test_final_native_guard_enforces_live_quantity_threshold(self):
        """The Lua sender cannot bypass the level4 threshold even if Python supplied an accepted plan."""
        for level, quantity, expected in ((3, 1, True), (4, 39999, False), (4, 40000, True),
                                          (7, 39999, False), (7, 40000, True), (3, 0, False)):
            with self.subTest(level=level, quantity=quantity):
                self.setUp()
                self.prepare(f'Game.finish=0;Game.resourceLevel={level};Game.quantity={quantity}')
                ok, result = self.lua.execute(f'return pcall(REA_AUTO_INFANTRY.collect_dispatch,2792,303,3,{level},1,1,20,101,191)')
                self.assertEqual(ok, expected, result)
                self.assertEqual(len(self.lua.globals().Game.trips), int(expected))

    def test_native_level_zero_enumerates_loaded_points_without_sending_actions(self):
        """List mode sees actual resource levels rather than imposing the disabled level control."""
        rows = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_candidates(3,0,20)'))
        self.assertEqual([(row['target_id'], row['level']) for row in rows], [(2792, 2)])
        self.assertEqual(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_candidates(3,3,20)')), [])
        self.assertEqual(len(self.lua.globals().Game.trips), 0)

    def test_saved_list_queries_all_resources_without_radius_and_retains_native_kind(self):
        """Zero filters enumerate distant loaded points with their true kind and level, never kind0."""
        self.lua.execute('Game.distance=150')
        rows = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_candidates(0,0,0)'))
        self.assertEqual([(row['kind'], row['level'], row['distance']) for row in rows], [(3, 2, 149)])
        self.assertEqual(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_candidates(3,2,100)')), [])
        self.prepare()
        ok, result = self.lua.execute('return pcall(REA_AUTO_INFANTRY.collect_dispatch,2792,303,3,2,1,1,0,101,191)')
        self.assertTrue(ok, result)

    def test_unsupported_or_insufficient_hero_followers_do_not_fall_back_to_infantry(self):
        """A missing native follower option or depleted compatible stock stops before sending a trip."""
        for change in ('Game.soldierId=413;Game.followerStock=1', 'Game.soldierId=999'):
            with self.subTest(change=change):
                self.setUp()
                self.prepare('Game.finish=0;' + change)
                self.assertFalse(self.dispatch()[0])
                self.assertEqual(len(self.lua.globals().Game.trips), 0)

    def test_generation_coordinate_range_and_freshness_guards(self):
        """An old or mismatched target cannot use an otherwise valid hero snapshot."""
        self.prepare()
        for changes in ({'detail': 0}, {'available': 0}, {'x': 102}, {'y': 190}, {'radius': 3}):
            with self.subTest(changes=changes):
                self.assertFalse(self.dispatch(**changes)[0])
        self.lua.execute('Game.time=Game.time+3001')
        self.assertFalse(self.dispatch()[0])

    def test_new_faster_cooling_hero_cannot_be_skipped_at_final_send(self):
        """If the fastest candidate changed, a slower hero must not be silently dispatched instead."""
        self.prepare('Game.finish=0;Game.extra={{id=305,state=0,finish=1660000,speed=400}}')
        self.assertFalse(self.dispatch()[0])

    def test_queue_boolean_and_observer_cleanup(self):
        """The native limit check is inverted correctly and temporary observers are removed on close."""
        self.prepare()
        self.assertTrue(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))['queue_free'])
        self.lua.execute('Game.queueFull=true')
        self.assertFalse(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))['queue_free'])
        self.lua.execute('REA_AUTO_INFANTRY.collect_close()')
        self.assertIsNone(self.lua.globals().Game.mainObserver)
        self.assertIsNone(self.lua.globals().Game.sceneObserver)
        self.assertIsNone(self.lua.globals().Game.tripObserver)

    def test_occupancy_counts_native_aims_and_reads_dynamic_server_limit(self):
        """Returning and gathering aim1 entries occupy slots; combat aim3 does not enter this counter."""
        self.prepare()
        self.lua.execute('local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel);'
                         'main.getMaxCollectionArmyCount=function() return 4 end;'
                         'main._myActionState={[1]=0,[2]=list({{[5]=1,[4]=6,[15]={[1]=303}},'
                         '{[5]=1,[4]=9,[15]={[1]=305}},{[5]=0,[4]=2,[15]={[1]=114}},'
                         '{[5]=3,[4]=3,[15]={[1]=242}}}),[3]=list({})}')
        state = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))
        self.assertEqual((state['queue_used'], state['queue_limit'], state['queue_known']), (3, 4, True))
        self.lua.execute('CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel).getMaxCollectionArmyCount=function() return 3 end;Game.queueFull=true')
        state = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))
        self.assertEqual(state['queue_limit'], 3)
        self.assertFalse(state['queue_free'])

    def test_only_own_native_pushes_increment_a_local_counter_without_game_actions(self):
        """Foreign, malformed and ordinary query notifications cannot generate push-driven requests."""
        self.lua.execute('Game.tripObserver:updateSelf({id=2,updateData={own=false}});'
                         'Game.tripObserver:updateSelf({id=3,updateData={own=true}});'
                         'Game.tripObserver:updateSelf({id=2,updateData={own=true}});'
                         'Game.tripObserver:updateSelf({id=2,updateData={own=true}})')
        state = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_push_status()'))
        self.assertEqual(state, {'seq': 2})
        self.assertEqual(len(self.lua.globals().Game.trips), 0)
        self.assertEqual(len(self.lua.globals().Game.sends), 0)

    def test_schedule_exports_raw_server_deadlines_without_resource_speed_math(self):
        """Use the same raw field11 as native countdowns, regardless of a resource's level bonus."""
        self.prepare()
        self.lua.execute('local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel);'
                         'main._myActionState={[1]=0,[2]=list({{[1]=123,[4]=6,[5]=1,[6]=2792,[11]=1234567,[15]={[1]=303}},'
                         '{[1]=124,[4]=9,[5]=1,[6]=2793,[11]=1345678,[15]={[1]=303}}}),[3]=list({})}')
        state = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_schedule()'))
        self.assertEqual(state['server_now_ms'], 1000000)
        self.assertEqual([(row['state'], row['end_ms']) for row in state['stages']], [(6, 1234567), (9, 1345678)])
        self.assertEqual([(row['aim'],row['target_id']) for row in state['stages']],[(1,2792),(1,2793)])
        self.assertEqual(len(self.lua.globals().Game.trips), 0)
        self.lua.execute('Game.time=Game.time+3001')
        ok, _ = self.lua.execute('return pcall(REA_AUTO_INFANTRY.collect_schedule)')
        self.assertFalse(ok)

    def test_bad_notification_cannot_escape_into_game_or_allow_a_departure(self):
        """Malformed native notifications are quarantined and make later collection fail closed."""
        self.prepare()
        self.lua.execute('Game.mainObserver:updateSelf({id=-9995,updateData={[1]=0,[2]={}}})')
        state = json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))
        self.assertTrue(state['observer_error'])
        self.assertFalse(self.dispatch()[0])

    def test_partial_observer_registration_rolls_back(self):
        """If the second model registration fails, the first model must not retain a ghost observer."""
        self.lua.execute('REA_AUTO_INFANTRY.collect_close();'
                         'CSLTypes.SceneNotifier.getInstance().addObserver=function() error("test registration failure") end')
        with self.assertRaises(Exception):
            self.lua.execute(Path(__file__).with_name('collection_runtime.lua').read_text(encoding='utf-8'))
        self.assertIsNone(self.lua.globals().Game.mainObserver)

    def test_background_query_does_not_open_ui_and_manual_notifications_are_forwarded(self):
        """Only exact pending query notifications are consumed; normal game UI remains untouched afterward."""
        self.prepare()
        self.assertIsNone(self.lua.globals().Game.forwardMain)
        self.assertIsNone(self.lua.globals().Game.forwardScene)
        self.assertIsNone(self.lua.globals().Game.forwardState)
        self.lua.execute('CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{[1]=0,[2]=2791,[3]=1})')
        self.assertEqual(self.lua.globals().Game.forwardScene, 1)
        self.lua.execute('REA_AUTO_INFANTRY.collect_close();'
                         'CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{[1]=0,[2]=2792,[3]=1})')
        self.assertEqual(self.lua.globals().Game.forwardScene, 2)


if __name__ == '__main__':
    unittest.main()
