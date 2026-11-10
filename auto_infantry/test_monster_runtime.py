"""Execute the production hunting Lua final guard against an isolated fake native game."""
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lupa import LuaRuntime
from test_hero_runtime import MOCK_GAME
from test_collection_runtime import COLLECTION_GAME
from monster import HuntOptions
from monster_service import MonsterService
from connection import Connection

HUNT_GAME=r'''
local oldManager=CSLTypes.ModelManager.sharedInstance()
local main=oldManager:getModel('main');local map=oldManager:getModel('map')
local nativeView={mViewDataCenterX=99,mViewDataCenterY=62}
map.mInViewDataChunkCacheManager.mtNewPlay_Map={[10]=250,[11]=250}
map.loadViewData=function(self,data)
 nativeView.mViewDataCenterX=data[1][1];nativeView.mViewDataCenterY=data[1][2]
 Game.regionLoads=(Game.regionLoads or 0)+1
end
local nativeLoad=map.loadViewData
Game.base=110;Game.per=20;Game.enemy=100;Game.visible=true;Game.monsterIdle=true;Game.capacity=2
Game.followerStock=4;Game.infantry=4;Game.skipAllowed=true;Game.skipCalls=0
Game.combatLimit=3
CSLTypes.SLGWarFogModel='fog';CSLTypes.SLGWildMonsterModel='wild'
local fog={isCellVisible=function(self,x,y,layer)
 assert(layer==0 or layer==-1)
 Game.fogCalls=Game.fogCalls or {};table.insert(Game.fogCalls,{x,y,layer})
 if layer==0 and Game.singleLayerVisible~=nil then return Game.singleLayerVisible end
 return Game.visible
end}
local wild={GetMonsterState=function() return Game.monsterIdle and 0 or 1 end,
 GetMonsterArmyId=function() return Game.attacker end,GetDieMonsterViewData=function() return Game.dead end}
CSLTypes.ModelManager.sharedInstance=function() return {getModel=function(self,name)
 if name=='fog' then return fog elseif name=='wild' then return wild else return oldManager:getModel(name) end
end} end
CSLTypes.SLGMapUtils.createKey=function(x,y) return x*1000+y end
main.getSignedMapTypeID=function() return 1 end
main.getMaxSoldierForFight=function() return Game.capacity end
main.getQuestCombatValue=function() return Game.enemy end
main.checkMaxCombateArmyCount=function() return Game.queueFull end
main.getMaxCombateArmyCount=function() return Game.combatLimit end
main.isAttackAimType=function(aim) return aim==3 or aim==2 end
main.isSLGMonthCardEnabled=function() return Game.skipAllowed end
main.getMyArmyInfoByHeroGroupId=function(self,id)
 if Game.ownArmy and Game.ownArmy[15][1]==id then return Game.ownArmy end
 for _,a in ipairs(Game.ownArmies or {}) do if a[15][1]==id then return a end end
end
local oldSearch=CSLTypes.DBSearcher.sharedInstance
CSLTypes.DBSearcher.sharedInstance=function()
 local s=oldSearch()
 s.searchTWildMonster_Map=function() return {[3]=1,[5]='100101'} end
 s.searchTNewPlayQuest=function() return {[3]='monster'} end
 return s
end
local notifier=CSLTypes.SceneNotifier.getInstance()
local ctrl=package.loaded.SLGMainController.__instanceDict
ctrl.sendTSLGViewInfoReq=function(self,x,y,rx,ry)
 Game.regionRequests=Game.regionRequests or {};table.insert(Game.regionRequests,{x,y,rx,ry})
 if not Game.regionTimeout then map:loadViewData({{x,y,0},rx,ry}) end
end
local oldArmyResponse=ctrl.sendTSLGGetAllArmyReq
ctrl.sendTSLGGetAllArmyReq=function()
 local busy=Game.busy;Game.busy=false;oldArmyResponse();Game.busy=busy
 if Game.ownArmy then main._myActionState[2]:Add(Game.ownArmy)
 elseif busy then main._myActionState[2]:Add({[15]={[1]=303}}) end
 for _,a in ipairs(Game.ownArmies or {}) do main._myActionState[2]:Add(a) end
end
ctrl.sendTSLGGetMonsterDetailReq=function(target)
 notifier:notifyUpdateData(1058,{0,target,20101,Game.monsterIdle and 0 or 1,100101,{101+target-2792,59,0}})
 main:notifyUpdateData(-9956,{0,target})
end
ctrl.sendTSLGGetAvailHeroListReq=function(target,aim)
 local h={[1]={[1]={[3]=Game.currentHero or 303},[2]=Game.state,[3]=Game.finish},[2]=list({{411,Game.followerStock}}),
 [3]=6,[4]=Game.base,[7]=Game.per}
 Game.candidate=h
 notifier:notifyUpdateData(1060,{0,target,aim,list({h}),{101+target-2792,59,0},0})
 main:notifyStateChange(-9991)
end
local tripFn=function() end;local soldierInit=package.loaded.SLGChosenSoldier.__instanceDict.initialize
local nativeSet=function() end;local update=function() end
local tips=function(own,enemy)
 local ratio=math.max(own,enemy)/math.min(own,enemy)
 if ratio>=1.5 then return {'我方超强，胜券在握','敌方过强，几无胜算'} end
 return {'优势明显','劣势明显'}
end
local skipStart=function() end
local skipClick=function(context) Game.skipCalls=Game.skipCalls+1;Game.lastSkip=context.mTArmyInfo[1] end
package.loaded.SLGChooseHeroLogicMonster={__instanceDict={startTrip2=tripFn}}
package.loaded.SLGChooseHeroScene={__instanceDict={getMyCombatValue=function(scene)
 return scene._currentSelectedHero[4]+(scene._soldierLeft:getNum()+scene._soldierRight:getNum())*scene._currentSelectedHero[7]
end}}
local soldierMethods=package.loaded.SLGChosenSoldier.__instanceDict
soldierMethods.setPosition=function(self,left) self._soldierInfo[3]=left and (Game.nativeLeft or 5) or (Game.nativeRight or 1) end
soldierMethods.getNum=function(self) return self._soldierInfo[2] or 0 end
soldierMethods.getSoldierInfo=function(self) return self._soldierInfo end
local sceneMethods=package.loaded.SLGChooseHeroScene.__instanceDict
sceneMethods.updateSoldier=function(scene)
 Game.nativeDefaultsCalled=(Game.nativeDefaultsCalled or 0)+1
 local option=scene._currentSelectedHero[2]:get_Item(0)
 local n=math.min(Game.capacity,option[2])
 scene._soldierLeft:setSodierId(option[1]);scene._soldierRight:setSodierId(option[1])
 scene._soldierLeft:setNum(math.floor(n/2));scene._soldierRight:setNum(math.floor((n+1)/2))
 scene.commonScene:setStartBtnInteractable(n>0 and not Game.nativeBlockStart)
 scene.armyInfo:setCombatValue(sceneMethods.getMyCombatValue(scene),scene._logic:getEnemyCombatValue())
end
sceneMethods.getTotalSoldierNum=function(scene) return scene._soldierLeft:getNum()+scene._soldierRight:getNum() end
sceneMethods.getSoldierInfoList=function(scene) return list({scene._soldierLeft:getSoldierInfo(),scene._soldierRight:getSoldierInfo()}) end
package.loaded.SLGChooseHeroArmyInfo={__instanceDict={setCombatValue=nativeSet}}
package.loaded.SLGSitdownPromptDialog={__instanceDict={Start=skipStart}}
CSLArrayGet=function(array,index) return array[index+1] end
local oldUpvalue=debug.getupvalue
debug.getupvalue=function(fn,index)
 if fn==nativeLoad and index==1 then return 'T_CSSLGMapObjectModel',nativeView
 elseif fn==tripFn then if index==1 then return 'T_TSLGStartArmyTripReq','trip' else return 'T_TMakeArmyReq','army' end
 elseif fn==nativeSet then return 'update',update
 elseif fn==update then return 'tips',tips
 elseif fn==skipStart then return 'skip',skipClick
 else return oldUpvalue(fn,index) end
end
'''


class MonsterLuaTests(unittest.TestCase):
    """Assert final native guards survive changes after Python chose a plan."""

    def setUp(self):
        """Load actual recovery and hunting runtimes into a fake world with no real senders."""
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_GAME);self.lua.execute(COLLECTION_GAME);self.lua.execute(HUNT_GAME)
        self.lua.execute(Path(__file__).with_name('hero_runtime.lua').read_text(encoding='utf-8'))
        self.lua.execute(Path(__file__).with_name('monster_runtime.lua').read_text(encoding='utf-8'))

    def prepare(self, change=''):
        """Deliver new owned hero/army and exact monster read responses before a formation decision."""
        self.lua.execute('Game.finish=0;'+change+';REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.hunt_query(2792)')

    def test_region_query_uses_explicit_ranges_and_a_new_completed_load(self):
        """Even the same center needs a new native generation; another response cannot satisfy its read."""
        state=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_region_state()'))
        self.assertEqual(state['seq'],0)
        self.lua.execute('REA_AUTO_INFANTRY.hunt_region_query(92,231)')
        state=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_region_state()'))
        self.assertEqual((state['seq'],state['last_x'],state['last_y'],state['view_x'],state['view_y']),
                         (1,92,231,92,231))
        sent=self.lua.globals().Game.regionRequests[1]
        self.assertEqual([sent[i] for i in range(1,5)],[92,231,24,18])
        self.lua.execute('REA_AUTO_INFANTRY.hunt_region_query(92,231)')
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_region_read,90,1,92,231)')[0])
        self.lua.execute("CSLTypes.ModelManager.sharedInstance():getModel('map'):loadViewData({{100,231,0},24,18})")
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_region_read,90,2,92,231)')[0])

    def test_watch_exports_map_refresh_config_and_local_server_clock_without_requests(self):
        """Refresh metadata piggybacks on the existing passive watch rather than issuing a server query."""
        self.lua.execute("CSLTypes.ModelManager.sharedInstance():getModel('map').mInViewDataChunkCacheManager.mtNewPlay_Map[20]='00:00:00|03:00:00|24:00:00'")
        state=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_watch(20)'))
        self.assertEqual(state['refresh_times'],'00:00:00|03:00:00|24:00:00')
        self.assertEqual(state['server_now_ms'],self.lua.globals().Game.time)
        self.assertIsNone(self.lua.globals().Game.regionRequests)
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_region_plan_covers_every_in_range_cell_including_map_edges(self):
        """Overlapping query cores cannot leave holes, and lower bounds never discard a reachable cell."""
        self.lua.execute('CSLTypes.SLGMapUtils.calMapP2PDistance=function(a,b) return math.abs(a[1]-b[1])+math.abs(a[2]-b[2]) end')
        regions=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_scan_plan(90)'))['regions']
        self.assertLess(len(regions),100)
        for x in range(250):
            for y in range(250):
                d=abs(x-99)+abs(y-62)
                if d>90:continue
                covering=[r for r in regions if r['left']<=x<=r['right'] and r['bottom']<=y<=r['top']]
                self.assertEqual(len(covering),1,(x,y))
                r=covering[0]
                self.assertLessEqual(r['min_distance'],d)
                self.assertLessEqual(abs(x-r['x']),24)
                self.assertLessEqual(abs(y-r['y']),18)
        for args in ('-1,0','250,0','0,250','1.5,0'):
            self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_region_query,'+args+')')[0])
        self.assertIsNone(self.lua.globals().Game.regionRequests)

    def test_region_observer_cleanup_restores_original_loader(self):
        """The passive response hook is removed together with the other hunt wrappers."""
        result=self.lua.execute("local m=CSLTypes.ModelManager.sharedInstance():getModel('map');local wrapped=m.loadViewData;"
            "REA_AUTO_INFANTRY.hunt_close();return m.loadViewData~=wrapped")
        self.assertTrue(result)

    def test_expanded_radius_accepts200_and_keeps_discovery_boundary(self):
        """Loaded targets at200 are included;201 stays outside scope and invalid radii cannot bypass Lua."""
        self.prepare('Game.distance=200')
        self.lua.execute('''
         local map=CSLTypes.ModelManager.sharedInstance():getModel('map')
         local point={{{101,59,0},2792},20101}
         local points={GetDictKeys=function() return list({2792}) end,get_Item=function() return point end}
         local cache={ContainsKey=function(self,kind) return kind==3000 end,get_Item=function() return points end}
         map.mInViewDataChunkCacheManager={getAllViewData=function() return list({{mViewDataCache=cache}}) end}
        ''')
        rows=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_candidates(200)'))
        self.assertEqual([r['target_id'] for r in rows],[2792])
        self.lua.execute('Game.distance=201')
        self.assertEqual(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_candidates(200)')),[])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_candidates,201)')[0])

    def test_final_departure_guard_accepts200_but_rejects_invalid_or_outside_scope(self):
        """A valid native formation at200 can depart; an oversized setting or a201-distance target cannot."""
        self.prepare('Game.distance=200')
        result=self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_dispatch,2792,303,411,2,1,1,200,101,191)')
        self.assertTrue(result[0],result)
        self.assertEqual(len(self.lua.globals().Game.trips),1)
        for radius,distance in ((201,200),(200,201),(0,1)):
            with self.subTest(radius=radius,distance=distance):
                self.setUp();self.prepare(f'Game.distance={distance}')
                result=self.lua.execute(f'return pcall(REA_AUTO_INFANTRY.hunt_dispatch,2792,303,411,2,1,1,{radius},101,191)')
                self.assertFalse(result[0],result)
                self.assertEqual(len(self.lua.globals().Game.trips),0)

    def send(self, n=2, target_id=2792, hero_id=303, seq=1):
        """Exercise the production main-thread final guard without allowing a real network request."""
        ok,result=self.lua.execute(f'return pcall(REA_AUTO_INFANTRY.hunt_dispatch,{target_id},{hero_id},411,{n},{seq},{seq},20,{101+target_id-2792},191)')
        return ok and result=='hunt_departure_submitted',result

    def test_unavailable_hero_reports_unsent_without_setting_submission(self):
        """A real pre-send cooldown race returns a typed status, permitting only a newly checked departure."""
        self.prepare()
        self.lua.execute('Game.finish=Game.time+60000;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')
        ok,result=self.send()
        self.assertFalse(ok);self.assertEqual(result,'hunt_replan:hero')
        self.assertEqual(len(self.lua.globals().Game.trips),0)
        self.lua.execute('Game.finish=0;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.hunt_query(2792)')
        self.assertTrue(self.send(seq=2)[0])
        self.assertEqual(len(self.lua.globals().Game.trips),1)

    def test_native_default_count_and_strong_side_metrics(self):
        """The native two-troop default qualifies; weak-side labels cannot leak through."""
        self.prepare()
        metrics=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertEqual(metrics['formations'][0]['followers'],2)
        self.assertTrue(self.send()[0])
        req=self.lua.globals().Game.trips[1]
        self.assertEqual((req[2],req[4],req[1][1]),(3,2792,303))
        self.assertEqual([req[1][2][i][2] for i in (1,2)],[1,1])
        self.assertFalse(self.send()[0]);self.assertEqual(len(self.lua.globals().Game.trips),1)
        self.setUp();self.prepare('Game.base=1;Game.per=1')
        self.assertEqual(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))['formations'],[])

    def test_native_visibility_parameter_matches_discovery_details_and_final_guard(self):
        """Replay a native-visible point rejected by layer0 without adding region requests or skipping final checks."""
        self.prepare('Game.singleLayerVisible=false;Game.visible=true')
        self.lua.execute('''
         local map=CSLTypes.ModelManager.sharedInstance():getModel('map')
         local point={{{101,59,0},2792},20101}
         local points={GetDictKeys=function() return list({2792}) end,get_Item=function() return point end}
         local cache={ContainsKey=function(self,kind) return kind==3000 end,get_Item=function() return points end}
         map.mInViewDataChunkCacheManager.getAllViewData=function() return list({{mViewDataCache=cache}}) end
        ''')
        rows=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_candidates(20)'))
        self.assertTrue(rows[0]['visible'])
        metrics=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertTrue(metrics['target']['visible'])
        self.assertIsNone(self.lua.globals().Game.regionRequests)
        self.assertEqual(len(self.lua.globals().Game.trips),0)
        self.assertTrue(self.send()[0])
        calls=self.lua.globals().Game.fogCalls
        self.assertGreaterEqual(len(calls),4)
        self.assertTrue(all(calls[i][3]==-1 for i in range(1,len(calls)+1)))
        self.assertIsNone(self.lua.globals().Game.regionRequests)

    def test_native_hidden_after_details_still_blocks_departure(self):
        """A previously visible default formation cannot authorize departure once native visibility changes."""
        self.prepare('Game.singleLayerVisible=false;Game.visible=true')
        metrics=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertTrue(metrics['target']['visible'])
        self.lua.execute('Game.visible=false')
        result=self.send()
        self.assertFalse(result[0])
        self.assertIn('Monster is hidden or occupied',str(result))
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_captured_6012_case_cannot_plan_or_send_above_native_total_limit(self):
        """Replay the rejected307 formation: 138442 + 3*24000 must not bypass the game's TOTAL cap2."""
        self.prepare('Game.base=138442;Game.per=24000;Game.enemy=139860;Game.capacity=2')
        metrics=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertEqual(metrics['formations'],[],'The captured6012 request incorrectly planned three followers')
        self.assertFalse(metrics['can_win_full'],'A total cap2 does not permit theoretical four-follower strength')
        self.assertFalse(self.send(3)[0],'The final guard must reject the recorded three-follower request')
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_captured_zero_soldier_failure_uses_native_default_instead_of_minimum(self):
        """The132314-power hero may beat a weak monster alone, but the native default still carries cap2."""
        self.prepare('Game.base=132314;Game.per=21340;Game.enemy=50320;Game.capacity=2')
        m=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertEqual(m['formations'][0]['followers'],2,'The actual zero-follower6012 packet must not be planned')
        self.assertTrue(m['formations'][0]['native_default'])
        self.assertFalse(self.send(0)[0])

    def test_native_start_disabled_or_zero_stock_cannot_reach_sender(self):
        """Native UI eligibility is required independently of combat superiority or numeric capacity."""
        for change in ('Game.followerStock=0','Game.nativeBlockStart=true'):
            with self.subTest(change=change):
                self.setUp();self.prepare('Game.base=200;'+change)
                metrics=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
                self.assertTrue(all(not row['eligible'] for row in metrics['formations']))
                self.assertFalse(self.send(0 if 'Stock' in change else 2)[0])
                self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_default_maximum_and_native_positions_are_not_manually_overridden(self):
        """Native quantities/positions pass through unchanged, even if the game's position identifiers change."""
        for base,n in ((150,2),(130,3),(90,4)):
            with self.subTest(n=n):
                self.setUp();self.prepare(f'Game.base={base};Game.capacity={n};Game.nativeLeft=8;Game.nativeRight=7')
                self.assertTrue(self.send(n)[0])
                soldiers=self.lua.globals().Game.trips[1][1][2]
                self.assertEqual([soldiers[i][2] for i in (1,2)],[n//2,n-n//2])
                self.assertEqual([soldiers[i][3] for i in (1,2)],[8,7])

    def test_final_changes_never_reach_sender(self):
        """Fog, occupancy, cooldown, stock, ownership, freshness and skip entitlement are final guards."""
        for change in ('Game.visible=false','Game.monsterIdle=false','Game.attacker=9','Game.dead={}',
                       'Game.finish=Game.time+1000;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()',
                       'Game.busy=true;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()',
                       'Game.infantry=0','Game.candidate[2][1][2]=1',
                       'Game.capacity=0','Game.skipAllowed=false','Game.queueFull=true','Game.enemy=0',
                       'Game.time=Game.time+3001','Game.state=20;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()',
                       "CSLTypes.ModelManager.sharedInstance():getModel('main').mTSLGLoginMapRsp={}"):
            with self.subTest(change=change):
                self.setUp();self.prepare();self.lua.execute(change)
                self.assertFalse(self.send()[0],change)
                self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_nondefault_too_weak_and_duplicate_target_armies_are_blocked(self):
        """Caller-specified deviations from the native default and repeated targets remain forbidden."""
        for n in (0,1,3,4):
            self.setUp();self.prepare();self.assertFalse(self.send(n)[0])
        self.setUp();self.prepare()
        self.lua.execute("local m=CSLTypes.ModelManager.sharedInstance():getModel('main');m._myActionState[2]:Add({[5]=3,[6]=2792,[15]={[1]=305}})")
        self.assertFalse(self.send()[0])

    def bind_army(self, state=3):
        """Bind the exact accepted fake army after its once-only departure."""
        self.assertTrue(self.send()[0])
        self.lua.execute(f"Game.ownArmy={{[1]=10,[4]={state},[5]=3,[6]=2792,[15]={{[1]=303}}}};"
                         "Game.busy=true;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.hunt_ack(2792,303,10)")

    def test_skip_requires_tracked_arrival_and_is_once_only(self):
        """Only a confirmed arrived helper army can execute the native skip callback, exactly once."""
        self.prepare();self.bind_army()
        self.assertTrue(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
        self.assertEqual(self.lua.globals().Game.skipCalls,1)
        for change in ('Game.ownArmy[4]=2','Game.ownArmy[6]=2793','Game.ownArmy[1]=11',
                       'Game.skipAllowed=false','Game.time=Game.time+3001'):
            with self.subTest(change=change):
                self.setUp();self.prepare();self.bind_army();self.lua.execute(change)
                self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
                self.assertEqual(self.lua.globals().Game.skipCalls,0)

    def test_expired_skip_guard_does_not_mark_submitted_and_fresh_read_allows_one_skip(self):
        """Reproduce a delayed RPC: stale rejection sends nothing, and fresh state permits exactly one skip."""
        self.prepare();self.bind_army()
        self.lua.execute('Game.time=Game.time+3001')
        ok,error=self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')
        self.assertFalse(ok);self.assertIn('Fresh busy hero required',str(error))
        self.assertEqual(self.lua.globals().Game.skipCalls,0)
        self.lua.execute('REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')
        self.assertTrue(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
        self.assertEqual(self.lua.globals().Game.skipCalls,1)

    def test_slow_preparation_does_not_leave_an_idle_hero_waiting_for_manual_check(self):
        """A slow initial log/barrack read must not strand a fresh target behind expired hero eligibility."""
        self.prepare()
        target=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))['target']
        owner=Mock();owner.guard=threading.RLock();owner.closing=threading.Event()
        connection=Connection();owner.connection=connection;connection.hunt_generation=1

        def refresh():
            """Use actual hero-response generations while keeping every sender inside the fake game."""
            self.lua.execute('REA_AUTO_INFANTRY.hero_refresh()')
            return json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hero_list()'))

        def call(operation, arguments=()):
            """Keep native capacity/metrics guards real and substitute only map discovery."""
            if operation=='hunt_watch':
                return dict(seq=0,home_x=100,home_y=60,candidates=[target])
            if operation=='hunt_candidates':return [target]
            if operation=='hunt_scan_plan':return {'regions':[]}
            result=self.lua.execute('return REA_AUTO_INFANTRY.'+operation+'('+','.join(map(str,arguments))+')')
            return json.loads(result) if operation in {'hunt_schedule','hunt_status','hunt_metrics','hunt_refresh_clock'} else result

        connection.refresh_heroes=Mock(side_effect=refresh)
        connection.hunt_call=Mock(side_effect=call)
        connection.prepare_collection=Mock(side_effect=lambda: self.lua.execute('Game.time=Game.time+4000'))
        connection.dispatch_hunt=Mock(return_value=(dict(army_id=10,hero_id=303,target_id=target['target_id']),{'heroes':[]}))
        service=MonsterService(owner);service.switch(True,HuntOptions(150))
        with patch('monster_service.time.monotonic',return_value=100):service.tick(connection)
        connection.dispatch_hunt.assert_called_once()
        self.assertEqual(connection.refresh_heroes.call_count,2)
        self.assertFalse(service.waiting)

    def test_query_suppression_does_not_consume_manual_or_collection_traffic(self):
        """Matching reads stay background-only; after cleanup unrelated original callbacks remain intact."""
        self.prepare()
        self.assertEqual(self.lua.globals().Game.forwardScene,None)
        self.lua.execute("CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{0,2792,1,list({})})")
        self.assertEqual(self.lua.globals().Game.forwardScene,1)
        self.lua.execute('REA_AUTO_INFANTRY.hunt_close()')
        self.lua.execute("CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1058,{0,2792})")
        self.assertEqual(self.lua.globals().Game.forwardScene,2)

    def test_hunt_and_collection_wrappers_cleanup_in_reverse_order(self):
        """The real collection wrapper still receives its aim1 query while hunt owns only aim3 responses."""
        self.lua.execute('REA_AUTO_INFANTRY.hunt_close()')
        self.lua.execute(Path(__file__).with_name('collection_runtime.lua').read_text(encoding='utf-8'))
        self.lua.execute(Path(__file__).with_name('monster_runtime.lua').read_text(encoding='utf-8'))
        self.prepare()
        self.lua.execute('REA_AUTO_INFANTRY.collect_query(2792)')
        status=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_status()'))
        self.assertTrue(status['ready'])
        self.assertEqual(self.lua.globals().Game.forwardScene,None)
        self.lua.execute('REA_AUTO_INFANTRY.hunt_close();REA_AUTO_INFANTRY.collect_close()')
        self.lua.execute("CSLTypes.SceneNotifier.getInstance():notifyUpdateData(1060,{0,2792,3,list({})})")
        self.assertEqual(self.lua.globals().Game.forwardScene,1)

    def test_repeated_same_phase_pushes_do_not_trigger_server_checks(self):
        """Position-only or duplicate updates for one army coalesce until its phase/deadline changes."""
        self.prepare()
        self.lua.execute("local o=Game.tripObserver;local a={[1]=12,[4]=2,[5]=3,[6]=2792,[11]=1001000,own=true};"
                         "for i=1,100 do o:updateSelf({id=2,updateData=a}) end")
        first=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_watch(20)'))['seq']
        self.assertEqual(first,1)

    def test_troop_shortage_waits_and_local_stock_change_is_visible(self):
        """Lack of compatible soldiers is temporary, not grounds for moving to a farther hunting ring."""
        self.prepare('Game.followerStock=1')
        metrics=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertTrue(metrics['potential']);self.assertTrue(metrics['needs_soldiers'])
        self.assertEqual(metrics['formations'],[])
        before=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_watch(20)'))
        self.lua.execute('Game.infantry=7')
        after=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_watch(20)'))
        self.assertNotEqual(before['troops'],after['troops'])

    def test_native_capacity_counts_combat_aims_including_manual_returning_armies(self):
        """Capacity is not a count of aim3 alone: use the same aim classification as the native checker."""
        self.prepare('Game.combatLimit=4')
        self.lua.execute("Game.extra={{id=304,state=0,finish=0},{id=305,state=0,finish=0}};"
            "Game.ownArmies={{[1]=10,[4]=9,[5]=2,[6]=1,[11]=1001000,[15]={[1]=304}},"
            "{[1]=11,[4]=6,[5]=1,[6]=2,[11]=1002000,[15]={[1]=305}}};"
            "REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()")
        s=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_schedule()'))
        self.assertTrue(s['queue_known']);self.assertEqual((s['queue_used'],s['queue_limit']),(1,4))
        self.assertTrue(s['queue_free'])
        self.lua.execute('Game.combatLimit=1')
        self.assertFalse(self.send()[0])
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_two_accepted_armies_have_independent_skip_and_release_markers(self):
        """A second hero can depart to a second target, and each army remains independently attributable."""
        self.prepare('Game.extra={{id=304,state=0,finish=0}}')
        self.assertTrue(self.send()[0])
        self.lua.execute("Game.ownArmies={{[1]=10,[4]=3,[5]=3,[6]=2792,[11]=0,[15]={[1]=303}}};"
                         "REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.hunt_ack(2792,303,10);"
                         "Game.currentHero=304;REA_AUTO_INFANTRY.hunt_query(2793)")
        self.assertTrue(self.send(target_id=2793,hero_id=304,seq=2)[0])
        self.lua.execute("table.insert(Game.ownArmies,{[1]=11,[4]=3,[5]=3,[6]=2793,[11]=0,[15]={[1]=304}});"
                         "REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list();REA_AUTO_INFANTRY.hunt_ack(2793,304,11)")
        self.assertTrue(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
        self.assertTrue(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2793,304,11)')[0])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2792,303,10)')[0])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_skip,2793,304,11)')[0])
        self.assertEqual(self.lua.globals().Game.skipCalls,2)
        self.lua.execute('table.remove(Game.ownArmies,1);REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_list()')
        self.assertTrue(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_release,10)')[0])
        self.assertFalse(self.lua.execute('return pcall(REA_AUTO_INFANTRY.hunt_release,11)')[0])

    def test_full_strength_evidence_separates_weak_targets_from_cooldown_and_stock(self):
        """Ignored-coordinate evidence uses theoretical full strength, not the currently available follower count."""
        self.prepare('Game.base=1;Game.per=1')
        m=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertTrue(m['strength_known']);self.assertFalse(m['can_win_full'])
        self.setUp();self.prepare('Game.finish=Game.time+60000;Game.followerStock=0')
        m=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertTrue(m['strength_known']);self.assertTrue(m['can_win_full']);self.assertTrue(m['needs_soldiers'])
        self.setUp();self.prepare();self.lua.execute('Game.candidate[2]=list({})')
        self.assertFalse(json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))['strength_known'])
        self.setUp();self.prepare('Game.base=1;Game.per=1;Game.extra={{id=304,state=0,finish=0}}')
        m=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.hunt_metrics()'))
        self.assertFalse(m['strength_known']);self.assertEqual(m['missing_heroes'],1)


if __name__=='__main__':unittest.main()
