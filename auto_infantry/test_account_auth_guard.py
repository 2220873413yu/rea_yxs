"""Exercise the real account adapter at the native login request/response boundaries."""
import json
import unittest

from lupa.luajit21 import LuaRuntime

from account_service import SOURCE


FIXTURE = r'''
Game={sdk={platform=1,flag=0,open_id='old-id',GetAccessToken=function()return 'old-token'end},
 headers={},qr=0,auto=1,stopped=false,native_responses=0,stored_ticket='unchanged'}
local T_ID={E_SVR_MSG_ID_LOGIN=2}
local tickets={strOpenId='old-id',bCloudMatrixIos=true}
local apollo={cached=Game.sdk}
function apollo:getAccountInfo() self.cached=Game.sdk;return Game.sdk end
function apollo:getAccountCacheInfo() return self.cached end
function apollo:clearAccountInfoCache() self.cached=nil end
function tickets:Clear() self.strOpenId='';Game.logged=false end
function tickets:getOpenId()
 if self.strOpenId=='' then self.strOpenId=(apollo.cached or apollo:getAccountInfo()).open_id end
 return self.strOpenId
end
function tickets:getAccessToken() return apollo:getAccountInfo():GetAccessToken() end
function tickets:setCloudMatrixIos(v) self.bCloudMatrixIos=v end
function tickets:getLoginInfo() return {isLogined=function()return Game.logged end} end
local list={}
function list:get_Count() return #self end
function list:get_Item(i) return self[i+1] end
function list:Remove(v) for i,x in ipairs(self)do if x==v then table.remove(self,i);return true end end end
list[1]={callback=function(rsp)Game.native_responses=Game.native_responses+1 end}
local proto={recvSwitch={get=function(self,id)assert(id==T_ID.E_SVR_MSG_ID_LOGIN);return list end}}
function proto.addRecvCallback(id,callback) assert(id==2);list[#list+1]={callback=callback} end
local send={}
function send.sendData(id,body,noEncrypt)
 if id==2 then Game.headers[#Game.headers+1]={open_id=tickets:getOpenId(),token=body[1],noEncrypt=noEncrypt}
 else Game.other=(Game.other or 0)+1 end
 return 'native-result'
end
Game.original_send=send.sendData
function Game.respond(ret) local copy={};for _,h in ipairs(list)do copy[#copy+1]=h end;for _,h in ipairs(copy)do h.callback({ret})end end
function Game.authorize(id,token,platform)
 Game.sdk={open_id=id,flag=0,platform=platform or 1,GetAccessToken=function()return token end}
 send.sendData(2,{token},false)
end
Game.list=list;Game.send=send;Game.tickets=tickets
local manager={}
function manager:loginOut(toPage,sdkLogout)
 Game.stopped=true;Game.sdk_logout=sdkLogout
 if Game.retry_during_stop then send.sendData(2,{Game.sdk:GetAccessToken()},false) end
end
local function initialize()return T_ID.E_SVR_MSG_ID_LOGIN end
local setting={getGlobalSettingInt=function()return Game.auto end,setGlobalSettingInt=function(self,k,v)Game.auto=v end,
 getLicenseAcceptance=function()return true end,getLicensePrivacyAcceptance=function()return true end}
local T_TYPE={E_MOBILE_PLAT_TYPE_IOS=1}
local function setPlatformInfoForCloudMatrix(self,value)Game.mobile=value end
local function qr()setPlatformInfoForCloudMatrix({},T_TYPE.E_MOBILE_PLAT_TYPE_IOS);Game.qr=Game.qr+1 end
package.loaded.LoginCloudMatrix={__instanceDict={onBtnIosWechatClicked=qr,onBtnAndroidWechatClicked=qr,onBtnAndroidQQClicked=qr,onBtnIosQQClicked=qr}}
package.loaded.LoginPanel={__instanceDict={getCurrentStageName=function()return 'LoginStage' end}}
package.loaded.LoginManager={__instanceDict={initialize=initialize}}
package.loaded.TicketsProtocol={__instanceDict={_instance=tickets}}
package.loaded.MsgManager=send
CSLNewfunc=function(self,fn)return function(...)return fn(self,...)end end
CSLTypes={MsgManager=send,ProtoController=proto,Setting={sharedInstance=function()return setting end},
 ApolloLoginController={getInstance=function()return apollo end},TicketsProtocol={getInstance=function()return tickets end},
 LoginManager={sharedInstance=function()return manager end}}
'''


class NativeAuthenticationGuardTests(unittest.TestCase):
    """A successful SDK callback cannot send a new token under a stale cached account identity."""

    def setUp(self):
        """Keep every SDK credential and server response synthetic and confined to a fresh Lua VM."""
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FIXTURE)

    def operation(self, name):
        """Execute the production service source with one fixed account operation."""
        return self.lua.execute(f'local operation={json.dumps(name)};local mobile=1;local open_platform=0;local resume_auto=0;\n' + SOURCE)

    def test_new_authorization_replaces_stale_header_before_first_native_send(self):
        """Reproduce the observed new-token/old-OpenID package without touching stored tickets."""
        self.operation('qr')
        self.assertEqual(self.lua.eval('Game.tickets.strOpenId'), 'old-id')
        self.lua.execute("Game.authorize('new-id','new-token')")
        self.assertEqual(self.lua.eval('Game.headers[1].open_id'), 'new-id')
        self.assertEqual(self.lua.eval('Game.headers[1].token'), 'new-token')
        self.assertEqual(self.lua.eval('#Game.headers'), 1)
        self.assertEqual(self.lua.eval('Game.stored_ticket'), 'unchanged')

    def test_mismatched_request_token_is_blocked_without_rewrite_or_retry(self):
        """A raced SDK change cannot authenticate the request body under the wrong identity."""
        self.operation('qr')
        self.lua.execute("Game.send.sendData(2,{'another-token'},false)")
        self.assertEqual(self.lua.eval('#Game.headers'), 0)
        self.assertNotEqual(json.loads(self.operation('watch')).get('auth_error', ''), '')

    def test_server_rejection_is_observed_and_native_retries_are_blocked(self):
        """Keep the native error handler while exposing its first response and forbidding a second send."""
        self.operation('qr')
        self.lua.execute("Game.authorize('new-id','new-token');Game.respond(2);Game.authorize('new-id','new-token')")
        self.assertEqual(self.lua.eval('#Game.headers'), 1)
        self.assertEqual(self.lua.eval('Game.native_responses'), 1)
        self.assertEqual(json.loads(self.operation('watch')).get('auth_ret'), 2)

    def test_cancel_stops_native_auth_before_restoring_the_dispatcher(self):
        """A reconnect attempted inside native logout is still blocked; cleanup preserves original handlers."""
        self.operation('qr')
        self.lua.execute("Game.authorize('new-id','new-token');Game.retry_during_stop=true")
        self.operation('cancel_auth')
        self.assertEqual(self.lua.eval('#Game.headers'), 1)
        self.assertTrue(self.lua.eval('Game.send.sendData==Game.original_send'))
        self.assertEqual(self.lua.eval('#Game.list'), 1)
        self.assertFalse(self.lua.eval('Game.sdk_logout'))

    def test_success_cleanup_does_not_block_later_native_operations(self):
        """The temporary login guard cannot survive into normal manual game use."""
        self.operation('qr')
        self.lua.execute("Game.authorize('new-id','new-token');Game.respond(0)")
        self.operation('auth_cleanup')
        self.assertTrue(self.lua.eval('Game.send.sendData==Game.original_send'))
        self.assertEqual(self.lua.eval('#Game.list'), 1)
        self.lua.execute("Game.send.sendData(40,{},false)")
        self.assertEqual(self.lua.eval('Game.other'), 1)

    def test_wrong_provider_is_blocked_before_changing_identity_cache(self):
        """The user's WeChat selection cannot accidentally authenticate an SDK QQ context."""
        self.operation('qr')
        self.lua.execute("Game.authorize('qq-id','qq-token',2)")
        self.assertEqual(self.lua.eval('#Game.headers'), 0)
        self.assertEqual(self.lua.eval('Game.tickets.strOpenId'), 'old-id')

    def test_cleanup_does_not_overwrite_a_later_dispatcher_owner(self):
        """Restoring the login scope must not replace an unrelated wrapper installed afterward."""
        self.operation('qr')
        self.lua.execute('Game.later=function()end;Game.send.sendData=Game.later')
        self.operation('auth_cleanup')
        self.assertTrue(self.lua.eval('Game.send.sendData==Game.later'))
        self.assertEqual(self.lua.eval('#Game.list'), 1)


if __name__ == '__main__':
    unittest.main()
