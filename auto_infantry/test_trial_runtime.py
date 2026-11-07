"""Execute the production Lua adapter with fake native models and protocol senders."""
import json
from pathlib import Path
import unittest
from lupa import LuaRuntime

FIXTURE=r'''
Game={now=100,skip=110,round=1,inGame=false,sent={},results=0}
function L(rows)
 local x={rows=rows or {}};function x:get_Count()return #self.rows end;function x:get_Item(i)return self.rows[i+1]end
 function x:Add(v)self.rows[#self.rows+1]=v end;return x
end
function H(id,power,state,limited,stock)
 return {{{0,0,id},0,id},L({{411,stock or 20}}),0,power,0,0,5000,0,limited or false,action=state or 0}
end
function selected()return L({{{219,5,50},0,0,424972},{{213,5,50},0,0,423244},{{208,5,50},0,0,417672}})end
Game.account={mTLoginRsp={0},myUserId={1,'fake-private-id',0,1}}
Game.world={mIsMapLoaded=true,mTSLGLoginMapRsp={0,0,0,0,{{1,'fake-private-id',0,1}}}}
function Game.world:getTSLGSitDownRsp()return Game.sit end
function Game.world:getSkipTime()return Game.skip end
Game.profile={0,19,0,24,3,false,L({}),false,L({}),0,0,10010010,80}
Game.tower={getMainData=function()return Game.profile end}
Game.pve={getTPushPVEResult=function()return Game.cachedResult end};Game.game={isInGame=function()return Game.inGame end,getRoundCount=function()return Game.round end}
local models={MainModel=Game.account,SLGMainModel=Game.world,SLGTowerModel=Game.tower,PVEModel=Game.pve,GameModel=Game.game}
local T_ID={E_SVR_MSG_ID_SLG_QCT_GET_QUEST_PROFILE_INFO=10900,E_SVR_MSG_ID_SLG_GET_AVAIL_HERO_LIST=11012,
 E_SVR_MSG_ID_SLG_QCT_CHOOSE_TRIAL_HERO=10901,E_SVR_MSG_ID_SLG_SITDOWN=11006,
 E_SVR_MSG_ID_SLG_SITDOWN_GAME=10020,E_SVR_MSG_ID_SLG_TIMEOUT_SKIP=11015}
local function send(kind,code,args)Game.sent[#Game.sent+1]={kind=kind,code=code,args=args}end
local tc={sendTSLGGetQCTQuestProfileInfoReq=function()send('profile',T_ID.E_SVR_MSG_ID_SLG_QCT_GET_QUEST_PROFILE_INFO)end,
 sendTSLGQCTChooseTrialHeroReq=function(list)send('select',T_ID.E_SVR_MSG_ID_SLG_QCT_CHOOSE_TRIAL_HERO,list.rows)end}
local ctrl={sendTSLGGetAvailHeroListReq=function(q,a)send('available',T_ID.E_SVR_MSG_ID_SLG_GET_AVAIL_HERO_LIST,{q,a})end,
 sendTSLGSitDownClientReq=function(q,a,mode,army)send('challenge',T_ID.E_SVR_MSG_ID_SLG_SITDOWN,{q,mode,army[1]})end,
 sendTSLGTimeoutSkipReq=function()send('skip',T_ID.E_SVR_MSG_ID_SLG_TIMEOUT_SKIP,{Game.sit[11][7]})end,
 backToSLGInResult=function()send('return',0)end}
local chooser={show=function(r)Game.ui=r end,setContent=function(self,r)Game.ui=r end}
local hall={parseTPushPVEResult=function(self,r)Game.results=Game.results+1 end}
local T_TMakeArmyReq={}
package.loaded.SLGTowerController={__instanceDict=tc};package.loaded.SLGMainController={__instanceDict=ctrl}
package.loaded.SLGTowerChooseHeroScene={__instanceDict=chooser};package.loaded.HallMsgMgr={__instanceDict=hall}
package.loaded.SLGTowerReadyScene={__instanceDict={onStartBtnClick=function()return T_TMakeArmyReq end}}
package.loaded.SLGChooseHeroItem={__instanceDict={getActionState=function(h)return h.action end}}
CSLTypes={ModelManager={sharedInstance=function()return {getModel=function(self,k)return models[k]end}end},
 MainModel='MainModel',SLGTowerModel={getConsumeSoldierCount=function()return 2 end},SLGMainModel={GetMapTimeNow=function()return Game.now*1000 end},
 PVEModel='PVEModel',GameModel='GameModel',CSLList={},DBSearcher={sharedInstance=function()return {searchHeroInfoByStarAndGroup=function(self,s,id)return {0,0,0,0,0,0,'Hero'..id}end}end},
 YXSUtils={GBK2UTF8=function(s)return s end}}
models[CSLTypes.SLGTowerModel]=Game.tower;models[CSLTypes.SLGMainModel]=Game.world
function CSLNew(t)if t==CSLTypes.CSLList then return L()end;return {}end
REA_HELPER_SESSION_VALID=function()return Game.world.mIsMapLoaded end
function readyBattle()
 REA_TRIAL.begin();Game.profile[7]=selected();REA_TRIAL.challenge();REA_TRIAL.ack(11006,0)
 Game.inGame=true;Game.world.mIsMapLoaded=false
 Game.sit={0,0,0,6255,8,9,0,0,0,0,{10010010,0,0,0,0,16,77}}
 REA_TRIAL.status()
end
'''


class TrialRuntimeTests(unittest.TestCase):
    """Validate live schema positions, scene ownership, native eligibility and exactly-once operations."""

    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FIXTURE)
        self.lua.execute(Path(__file__).with_name('trial_runtime.lua').read_text(encoding='utf-8'))

    def run_lua(self, s):
        """Run one deterministic fake-native scenario and return only its explicit value."""
        return self.lua.execute(s)

    def test_install_and_status_send_nothing_and_choose_correct_protocol(self):
        view=json.loads(self.run_lua('return REA_TRIAL.status()'))
        self.assertEqual(view['codes']['challenge'],11006)
        self.assertEqual(self.run_lua('return #Game.sent'),0)
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.query_profile()')

    def test_native_response_capture_selects_eligible_highest_and_no_busy_hero(self):
        self.run_lua('''REA_TRIAL.begin();REA_TRIAL.query_available();REA_TRIAL.ack(11012,0)
package.loaded.SLGTowerChooseHeroScene.__instanceDict.setContent({},
 {0,10010010,16,L({H(219,190000,0),H(308,189000,5),H(213,188000,0),H(223,187000,1),H(208,186000,0),H(220,185000,0)})})''')
        view=json.loads(self.run_lua('return REA_TRIAL.status()'))
        self.assertEqual(view['available_seq'],1)
        receipt=json.loads(self.run_lua('return REA_TRIAL.select()'))
        self.assertEqual(receipt['heroes'],[219,213,208])
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.select()')

    def test_challenge_uses_group_id_not_level_and_owns_unloaded_world(self):
        self.run_lua('readyBattle()')
        self.assertEqual(self.run_lua('return Game.sent[1].args[3]'),219)
        self.assertTrue(self.run_lua('return REA_HELPER_SESSION_VALID()'))
        view=json.loads(self.run_lua('return REA_TRIAL.status()'))
        self.assertTrue(view['battle_ready']);self.assertEqual(view['army_id'],77)
        self.run_lua("Game.account.myUserId={2,'another-private-id',0,1}")
        self.assertFalse(self.run_lua('return REA_HELPER_SESSION_VALID()'))
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.status()')

    def test_skip_obeys_native_time_and_cannot_repeat(self):
        self.run_lua('readyBattle()')
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.skip()')
        self.assertEqual(self.run_lua('return #Game.sent'),1)
        self.run_lua('Game.now=110;REA_TRIAL.skip();REA_TRIAL.ack(11015,0)')
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.skip()')
        self.assertEqual(self.run_lua('return #Game.sent'),2)

    def test_foreign_result_is_forwarded_but_not_accepted_and_loss_cannot_return(self):
        self.run_lua('''readyBattle()
local r={0,false};r[18]=8;r[19]=999
package.loaded.HallMsgMgr.__instanceDict.parseTPushPVEResult({},r)''')
        self.assertNotIn('result',json.loads(self.run_lua('return REA_TRIAL.status()')))
        self.run_lua('''local r={0,false};r[18]=8;r[19]=9
package.loaded.HallMsgMgr.__instanceDict.parseTPushPVEResult({},r)''')
        v=json.loads(self.run_lua('return REA_TRIAL.status()'))
        self.assertFalse(v['result']['win']);self.assertEqual(self.run_lua('return Game.results'),2)
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.return_after_win()')
        self.assertEqual(self.run_lua('return #Game.sent'),1)

    def test_only_confirmed_win_can_return_and_advance_to_a_new_quest(self):
        self.run_lua('''readyBattle();Game.inGame=false;Game.world.mIsMapLoaded=true;Game.profile[12]=10010011''')
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.challenge()')
        self.run_lua('''local r={0,true};r[18]=8;r[19]=9
package.loaded.HallMsgMgr.__instanceDict.parseTPushPVEResult({},r)
REA_TRIAL.return_after_win();REA_TRIAL.challenge()''')
        self.assertEqual(self.run_lua('return Game.sent[#Game.sent].args[1]'),10010011)
        with self.assertRaises(Exception):self.run_lua('REA_TRIAL.challenge()')

    def test_cleanup_restores_native_handlers_and_world_guard(self):
        self.run_lua('readyBattle();REA_TRIAL.close()')
        self.assertFalse(self.run_lua('return REA_HELPER_SESSION_VALID()'))
        self.run_lua('Game.world.mIsMapLoaded=true')
        self.assertTrue(self.run_lua('return REA_HELPER_SESSION_VALID()'))

    def test_cached_native_dispatch_result_advances_when_method_wrapper_is_bypassed(self):
        """The game's dispatcher may retain the original handler registered before our wrapper."""
        self.run_lua('''readyBattle();Game.inGame=false
local r={0,true};r[18]=8;r[19]=9;r[16]={[9]=16,[10]=77};Game.cachedResult=r''')
        view=json.loads(self.run_lua('return REA_TRIAL.status()'))
        self.assertTrue(view.get('result',{}).get('win'), 'Saved matching victory must advance without a wrapper callback')
        self.run_lua('REA_TRIAL.return_after_win();Game.world.mIsMapLoaded=true;Game.profile[12]=10010011;REA_TRIAL.challenge()')
        self.assertEqual(self.run_lua('return Game.sent[#Game.sent].args[1]'),10010011)

    def test_cached_result_must_be_fresh_and_match_room_table_mode_and_army(self):
        """Reading the native cache must not accept a previous or unrelated battle's win."""
        self.run_lua('local r={0,true};r[18]=8;r[19]=9;r[16]={[9]=16,[10]=77};Game.cachedResult=r;readyBattle()')
        self.assertNotIn('result',json.loads(self.run_lua('return REA_TRIAL.status()')))
        for field, value in (('r[18]',99),('r[19]',99),('r[16][9]',3),('r[16][10]',78)):
            self.run_lua('local r={0,true};r[18]=8;r[19]=9;r[16]={[9]=16,[10]=77};'+field+'='+str(value)+';Game.cachedResult=r')
            self.assertNotIn('result',json.loads(self.run_lua('return REA_TRIAL.status()')))
        self.run_lua('local r={0,false};r[18]=8;r[19]=9;r[16]={[9]=16,[10]=77};Game.cachedResult=r')
        self.assertFalse(json.loads(self.run_lua('return REA_TRIAL.status()'))['result']['win'])


if __name__=='__main__':unittest.main()
