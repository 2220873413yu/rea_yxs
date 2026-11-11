"""Run the actual Lua recovery API against an isolated fake game, without Frida."""
import unittest
import json
from pathlib import Path

from lupa import LuaRuntime

MOCK_GAME = r'''
Game={time=1000000,stock=10,state=0,finish=1660000,busy=false,unknown=false,sends={}}
function list(entries)
 entries.get_Count=function(self) return #self end
 entries.get_Item=function(self,i) return self[i+1] end
 entries.Add=function(self,v) self[#self+1]=v end
 return entries
end
local model={}
local main={mIsMapLoaded=true,mTSLGLoginMapRsp={},mMapConfigID=1}
local items={getItemCount=function(self,id) assert(id==70291);return Game.stock end}
function model:getTSLGGetHeroPubRsp() return self.rsp end
local function heroResponse()
 local entries={{[1]={[3]=303},[2]=Game.state,[3]=Game.finish,[4]=113554}}
 for _,hero in ipairs(Game.extra or {}) do entries[#entries+1]={[1]={[3]=hero.id},[2]=hero.state,[3]=hero.finish,[4]=hero.power or 100} end
 model.rsp={[1]=0,[2]={[2]={[1]=list(entries)}}}
end
local function armyResponse()
 local entries={}
 if Game.busy then entries={{[15]={[1]=303}}} end
 if Game.unknown then entries={{}} end
 main._myActionState={[1]=0,[2]=list(entries),[3]=list({})}
end
heroResponse();armyResponse()
local ctrl={}
function ctrl:sendTSLGGetHeroPubReq() heroResponse() end
function ctrl:sendTSLGBuildSpeedupReq(kind,action,target,vec)
 Game.sends[#Game.sends+1]={kind,action,target,vec[1][1],vec[1][2]}
 Game.stock=Game.stock-1
 if target==303 then Game.finish=math.max(0,Game.finish-300000)
 else for _,hero in ipairs(Game.extra or {}) do if hero.id==target then hero.finish=math.max(0,hero.finish-300000) end end end
 model._stTSLGBuildSpeedupRsp={0,kind,action,target}
end
CSLTypes={SLGBuildingsModel='building',SLGMainModel='main',ItemsModel='items',CSLList='list',
 DBSearcher={sharedInstance=function() return {searchHeroInfoByStarAndGroup=function(self,star,id) return {[7]=(Game.names and Game.names[id]) or tostring(id)} end} end},
 YXSUtils={GBK2UTF8=function(value) return value end},
 ModelManager={sharedInstance=function() return {getModel=function(self,name)
  if name=='building' then return model elseif name=='main' then return main else return items end
 end} end}}
CSLNew=function(t) if t=='list' then return list({}) else return {} end end
package.loaded.HeroPalaceItem={__instanceDict={Update=function() end}}
package.loaded.UpgradeAccelerationNewDialog={__instanceDict={useButtonCallback=function() end}}
package.loaded.SLGBuildingsController={__instanceDict={_instance=ctrl}}
package.loaded.SLGMainController={__instanceDict={sendTSLGGetAllArmyReq=armyResponse}}
debug.getupvalue=function(f,n)
 if n==1 then return 'clock',function() return {GetCurrentServerTime=function() return Game.time/1000 end} end
 else return 'item','item' end
end
REA_AUTO_INFANTRY={}
'''


class HeroLuaTests(unittest.TestCase):
    """Verify the final in-game guard itself, beyond Python decision tests."""

    def setUp(self):
        """Load the unmodified production Lua module into a fresh fake account."""
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_GAME)
        self.lua.execute(Path(__file__).with_name('hero_runtime.lua').read_text(encoding='utf-8'))

    def run_lua(self, source):
        """Run one isolated scenario and return its result for Python assertions."""
        return self.lua.execute(source)

    def test_cold_hero_and_acceleration_declarations_load_without_spending(self):
        """Recovery startup resolves both lazy UI declarations without triggering their actions."""
        self.run_lua('''
         for _,name in ipairs({'HeroPalaceItem','UpgradeAccelerationNewDialog'}) do
          local declaration=package.loaded[name]
          package.loaded[name]=nil
          package.preload[name]=function() return declaration end
         end
        ''')
        self.lua.execute(Path(__file__).with_name('hero_runtime.lua').read_text(encoding='utf-8'))
        self.assertEqual(len(self.lua.globals().Game.sends),0)
        self.assertEqual(self.lua.globals().Game.stock,10)

    def test_one_item_has_exact_hero_type_and_inventory(self):
        """Only recovery item70291, target303 and business500 may reach the sender."""
        self.run_lua('REA_AUTO_INFANTRY.hero_refresh(); REA_AUTO_INFANTRY.hero_status(); REA_AUTO_INFANTRY.hero_speed(303)')
        sent = self.lua.globals().Game.sends[1]
        self.assertEqual([sent[i] for i in range(1, 6)], [3, 500, 303, 70291, 1])
        self.assertEqual(self.lua.globals().Game.stock, 9)

    def test_no_spending_from_initial_or_stale_cache(self):
        """Initial cached data and a query older than three seconds fail the final guard."""
        self.assertFalse(self.run_lua('return pcall(REA_AUTO_INFANTRY.hero_speed,303)')[0])
        self.run_lua('REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status();Game.time=Game.time+3001')
        self.assertFalse(self.run_lua('return pcall(REA_AUTO_INFANTRY.hero_speed,303)')[0])
        self.assertEqual(len(self.lua.globals().Game.sends), 0)

    def test_busy_unknown_recovered_and_empty_inventory_fail_closed(self):
        """Runtime guards catch busy heroes even if Python made an earlier idle decision."""
        for change in ('Game.state=20', 'Game.busy=true', 'Game.unknown=true', 'Game.finish=0', 'Game.stock=0'):
            with self.subTest(change=change):
                self.setUp()
                self.run_lua(change + ';REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status()')
                self.assertFalse(self.run_lua('return pcall(REA_AUTO_INFANTRY.hero_speed,303)')[0])
                self.assertEqual(len(self.lua.globals().Game.sends), 0)

    def test_short_remainder_accepts_exactly_one_item(self):
        """The final Lua guard permits the approved sub-five-minute remainder policy."""
        self.run_lua('Game.finish=Game.time+1000;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status();REA_AUTO_INFANTRY.hero_speed(303)')
        self.assertEqual(len(self.lua.globals().Game.sends), 1)

    def test_fast_step_stops_at_completion_without_an_extra_item(self):
        """Even a queued batch step consults current native cooldown rather than a precomputed Python budget."""
        self.run_lua('Game.finish=Game.time+1000;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status()')
        first=json.loads(self.run_lua('return REA_AUTO_INFANTRY.hero_speed_step(303)'))
        self.assertTrue(first['sent'])
        self.run_lua('Game.finish=0;REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status()')
        second=json.loads(self.run_lua('return REA_AUTO_INFANTRY.hero_speed_step(303)'))
        self.assertEqual(second,{'sent':False,'reason':'complete'})
        self.assertEqual(len(self.lua.globals().Game.sends),1)

    def test_fast_step_does_not_spend_for_busy_missing_or_stale_hero(self):
        """Fast mode cannot bypass the normal runtime freshness, ownership and activity guards."""
        for change in ('Game.busy=true','Game.unknown=true','Game.state=20','Game.stock=0'):
            with self.subTest(change=change):
                self.setUp()
                self.run_lua(change+';REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status()')
                self.run_lua('pcall(REA_AUTO_INFANTRY.hero_speed_step,303)')
                self.assertEqual(len(self.lua.globals().Game.sends),0)
        self.setUp()
        self.run_lua('REA_AUTO_INFANTRY.hero_refresh();REA_AUTO_INFANTRY.hero_status();Game.time=Game.time+3001')
        self.assertFalse(self.run_lua('return pcall(REA_AUTO_INFANTRY.hero_speed_step,303)')[0])

    def test_dynamic_roster_and_targeted_non_xishi_recovery(self):
        """Roster IDs, escaped names and per-hero recovery targets come from actual Lua snapshots."""
        self.run_lua('Game.extra={{id=305,state=0,finish=1660000},{id=315,state=20,finish=1660000}};'
                     'Game.names={[305]=\'陈圆圆"测试\'};REA_AUTO_INFANTRY.hero_refresh()')
        roster = json.loads(self.run_lua('return REA_AUTO_INFANTRY.hero_list()'))
        self.assertEqual([row['hero_id'] for row in roster['heroes']], [303, 305, 315])
        self.assertEqual(roster['heroes'][1]['name'], '陈圆圆"测试')
        self.run_lua('REA_AUTO_INFANTRY.hero_speed(305)')
        self.assertEqual(self.lua.globals().Game.sends[1][3], 305)
        self.assertFalse(self.run_lua('return pcall(REA_AUTO_INFANTRY.hero_speed,315)')[0])
        self.assertFalse(self.run_lua('return pcall(REA_AUTO_INFANTRY.hero_speed,999)')[0])


if __name__ == '__main__':
    unittest.main()
