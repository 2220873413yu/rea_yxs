"""Execute the production Lua troop capacity guard with real response field positions."""
import json
import unittest
from pathlib import Path
from lupa import LuaRuntime


class TroopRuntimeTests(unittest.TestCase):
    """Keep available and army-assigned soldiers distinct in the actual Lua adapter."""

    def make_lua(self, before_install=''):
        """Create native-like capacity and upgrade predicates while keeping every sender isolated."""
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().Constructor=object()
        lua.execute('''
         Game={sent=0};local army={[1]=675,[2]=6,[3]={[1]=47,[2]=2,[3]=665000,[4]=5},[6]=54}
         Game.army=army
         local rsp={[1]=0,[4]={get_Item=function() return army end}}
         local buildings={getTSLGGetBarrackRsp=function() return rsp end}
         local main={mIsMapLoaded=true,mTSLGLoginMapRsp={},mMapConfigID=1}
         CSLTypes={SLGBuildingsModel='b',ItemsModel='i',SLGMainModel='m',ModelManager={sharedInstance=function()
          return {getModel=function(self,k) if k=='b' then return buildings elseif k=='m' then return main
           else return {getItemCount=function() return Game.items or 0 end} end end} end}}
         package.loaded.SLGBuildingsController={__instanceDict={_instance={sendTSLGTrainSoldierReq=function(self,id)
          Game.sent=Game.sent+1;Game.lastUnit=id end,
          sendTSLGBuildSpeedupReq=function(self,kind,action,target,items)
           Game.speed={kind,action,target,items[1][1],items[1][2]} end}}}
         CSLTypes.CSLList='list'
         CSLNew=function(kind) if kind=='list' then return {Add=function(self,item) self[#self+1]=item end} else return {} end end
         local use=function() end;package.loaded.UpgradeAccelerationNewDialog={__instanceDict={useButtonCallback=use}}
         local init=function() end
         local predicate=function() if Game.unknownUpgrade then return 'unknown' end;return Game.upgrading==true end
         package.loaded.BarracksDialog={__instanceDict={initArmTrainingList=init}}
         debug.getupvalue=function(f,i)
          if f==init then if i==1 then return 'checkIsUpdating',predicate else return nil end end
          return 'T_TItemInfo',Constructor
         end
         package.preload['jit.util']=function() return {funcinfo=function(f)
          return {params=f==package.loaded.SLGBuildingsController.__instanceDict._instance.sendTSLGTrainSoldierReq and 2 or 5} end} end
        ''')
        lua.execute(before_install)
        lua.execute(Path(__file__).with_name('runtime.lua').read_text(encoding='utf-8'))
        return lua

    def test_cold_dialog_is_loaded_without_opening_or_spending(self):
        """A cold login must resolve the native declaration before reading its item constructor."""
        lua=self.make_lua('''
         local dialog=package.loaded.UpgradeAccelerationNewDialog
         package.loaded.UpgradeAccelerationNewDialog=nil
         package.preload.UpgradeAccelerationNewDialog=function()
          Game.declarationLoads=(Game.declarationLoads or 0)+1;return dialog
         end
        ''')
        self.assertEqual(lua.globals().Game.declarationLoads,1)
        self.assertEqual(lua.globals().Game.sent,0)
        self.assertIsNone(lua.globals().Game.speed)

    def test_missing_dialog_fails_with_clear_dependency_error(self):
        """Missing native modules must stop initialization before any command is sent."""
        with self.assertRaisesRegex(Exception,'Native module unavailable: UpgradeAccelerationNewDialog'):
            self.make_lua('package.loaded.UpgradeAccelerationNewDialog=nil')

    def test_assigned_soldiers_are_exported_and_block_over_capacity_training(self):
        """47 available +2 assigned +5 training must be rejected before the native sender runs."""
        lua=self.make_lua()
        state=json.loads(lua.execute('return REA_AUTO_INFANTRY.status(411)'))
        self.assertEqual((state['count'],state['deployed'],state['pending']),(47,2,5))
        ok,error=lua.execute('return pcall(REA_AUTO_INFANTRY.train,411)')
        self.assertFalse(ok)
        self.assertIn('capacity already reached',error)
        self.assertEqual(lua.globals().Game.sent,0)

    def test_native_upgrade_guard_blocks_then_allows_after_upgrade(self):
        """The actual native predicate, not a screenshot timer or manual flag, authorizes the sender."""
        lua=self.make_lua()
        lua.execute('Game.army[3][4]=0;Game.army[3][3]=0;Game.upgrading=true')
        state=json.loads(lua.execute('return REA_AUTO_INFANTRY.status(411)'))
        self.assertTrue(state['upgrade_known'])
        self.assertTrue(state['upgrading'])
        ok,error=lua.execute('return pcall(REA_AUTO_INFANTRY.train,411)')
        self.assertFalse(ok)
        self.assertIn('REA_BARRACK_TRAINING_UNAVAILABLE',error)
        self.assertEqual(lua.globals().Game.sent,0)
        lua.execute('Game.upgrading=false;REA_AUTO_INFANTRY.train(411)')
        self.assertEqual(lua.globals().Game.sent,1)

    def test_unknown_upgrade_state_cannot_authorize_training(self):
        """A changed/unavailable native predicate is reported as unknown rather than treated as idle."""
        lua=self.make_lua()
        lua.execute('Game.army[3][4]=0;Game.unknownUpgrade=true')
        self.assertFalse(json.loads(lua.execute('return REA_AUTO_INFANTRY.status(411)'))['upgrade_known'])
        self.assertFalse(lua.execute('return pcall(REA_AUTO_INFANTRY.train,411)')[0])
        self.assertEqual(lua.globals().Game.sent,0)

    def test_scout_native_status_training_and_acceleration_target(self):
        """803 retains its own duration/slots/counts and uses the same verified70251/400 item action."""
        lua=self.make_lua()
        lua.execute('Game.army[1]=375;Game.army[2]=8;Game.army[3]={12,0,373000,2};Game.army[6]=58;Game.items=5')
        state=json.loads(lua.execute('return REA_AUTO_INFANTRY.status(803)'))
        self.assertEqual((state['soldier_id'],state['duration_ms'],state['queue_capacity'],state['limit']),
                         (803,375000,8,58))
        lua.execute('REA_AUTO_INFANTRY.train(803);REA_AUTO_INFANTRY.speed(803)')
        self.assertEqual(lua.globals().Game.lastUnit,803)
        self.assertEqual([lua.globals().Game.speed[i] for i in range(1,6)], [3,400,803,70251,1])
        lua.execute('Game.upgrading=true')
        self.assertFalse(lua.execute('return pcall(REA_AUTO_INFANTRY.train,803)')[0])
        self.assertEqual(lua.globals().Game.sent,1)
