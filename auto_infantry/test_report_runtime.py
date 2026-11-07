"""Execute the real report adapter against native-shaped Lua fakes, never against the live reward endpoint."""
import json
from pathlib import Path
import unittest
from lupa import LuaRuntime

FIXTURE=r'''
function L(rows)local x={rows=rows};function x:get_Count()return #self.rows end;function x:get_Item(i)return self.rows[i+1]end;return x end
G={now=100000,sends={},mapId=1,cacheMap=0}
G.account={mTLoginRsp={}};G.main={mTSLGLoginMapRsp={},mIsMapLoaded=true,getCurrentMapId=function()return G.mapId end}
G.buildings={getmapId4MilitaryNews=function()return G.cacheMap end,getTSLGGetAllEmailRsp=function()return G.r end}
local ctrl={}
function ctrl:sendTSLGGetAllEmailReq(a,b)G.sends[#G.sends+1]={'refresh',a,b};G.r=nil;G.cacheMap=G.mapId end
function ctrl:sendTSLGGetEmailRewardReq(a,b,c)G.sends[#G.sends+1]={'claim',a,b,c}end
local models={MainModel=G.account,SLGMainModel=G.main,SLGBuildingsModel=G.buildings}
CSLTypes={MainModel='MainModel',SLGMainModel={GetMapTimeNow=function()return G.now end},SLGBuildingsModel='SLGBuildingsModel',
 ModelManager={sharedInstance=function()return {getModel=function(self,k)return models[k]end}end},
 SLGBuildingsController={getInstance=function()return ctrl end},
 DBSearcher={sharedInstance=function()return {searchMilitaryNewsItemInfo=function(self,id)return ({[1]={1,1,0,3},[2]={2,2,0,2},[3]={3,3,0,6}})[id]end}end}}
models[CSLTypes.SLGMainModel]=G.main
function response()
 G.r={0,L({{101,1,{},L({1}),0},{102,1,{},L({1}),1},{103,2,{},L({}),0},{104,3,{},L({2}),0}}),999,{},0}
end
'''


class ReportRuntimeTests(unittest.TestCase):
    """Require a fresh full list and one-use native receive token tied to the current world."""

    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FIXTURE)
        self.lua.execute(Path(__file__).with_name('report_runtime.lua').read_text(encoding='utf-8'))

    def test_install_sends_nothing_and_first_refresh_works_without_a_previous_mail_cache(self):
        self.assertEqual(self.lua.execute('return #G.sends'),0)
        self.lua.execute('REA_REPORT.refresh();response()')
        result=json.loads(self.lua.execute('return REA_REPORT.confirm()'))
        self.assertEqual((result['total'],result['claimable']),(4,2))

    def test_claim_uses_exact_native_parameter_order_once(self):
        self.lua.execute('REA_REPORT.refresh();response();REA_REPORT.confirm();REA_REPORT.claim()')
        self.assertEqual([self.lua.execute(f'return G.sends[2][{i}]')for i in (2,3,4)],[0,0,1])
        with self.assertRaises(Exception):self.lua.execute('REA_REPORT.claim()')
        self.assertEqual(self.lua.execute('return #G.sends'),2)

    def test_old_cache_changed_world_and_expired_confirmation_cannot_claim(self):
        self.lua.execute('response()')
        with self.assertRaises(Exception):self.lua.execute('REA_REPORT.confirm()')
        with self.assertRaises(Exception):self.lua.execute('REA_REPORT.claim()')
        self.lua.execute('REA_REPORT.refresh();response();REA_REPORT.confirm();G.now=110001')
        with self.assertRaises(Exception):self.lua.execute('REA_REPORT.claim()')
        self.lua.execute('G.now=100000;G.main.mTSLGLoginMapRsp={}')
        with self.assertRaises(Exception):self.lua.execute('REA_REPORT.claim()')

    def test_waiting_for_new_model_does_not_resend_list(self):
        self.lua.execute('REA_REPORT.refresh()')
        for _ in range(10):self.assertFalse(json.loads(self.lua.execute('return REA_REPORT.confirm()'))['ready'])
        self.assertEqual(self.lua.execute('return #G.sends'),1)
