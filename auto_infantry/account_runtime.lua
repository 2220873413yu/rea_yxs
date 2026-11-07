-- Fixed account operations. The private identity result is consumed only by the encrypted-profile service, never UI/logs.
if operation=='ready' then
 local p=package.loaded.LoginPanel
 local t=package.loaded.TicketsProtocol
 return p and p.__instanceDict and t and t.__instanceDict and t.__instanceDict._instance and 'ready' or 'pending'
end
local settings=CSLTypes.Setting.sharedInstance()
if operation=='pause' then
 local previous=settings:getGlobalSettingInt('mNoAutoLogin',0)
 settings:setGlobalSettingInt('mNoAutoLogin',1)
 return tostring(previous)
elseif operation=='cancel_auth' then
 -- Stop native reconnect/hello/login callbacks too; do not revoke the SDK authorization or erase saved files.
 settings:setGlobalSettingInt('mNoAutoLogin',1)
 CSLTypes.LoginManager.sharedInstance():loginOut(true,false)
 return 'authentication_stopped'
elseif operation=='resume' then
 -- QR authorization must finish before restoring startup auto-login; never resume on a failed scan.
 local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.MainModel)
 local tickets=CSLTypes.TicketsProtocol.getInstance():getLoginInfo()
 assert(main.mTLoginRsp and main.mTLoginRsp[1]==0 and tickets and tickets:isLogined()
  and package.loaded.LoginPanel.__instanceDict.getCurrentStageName({})~='LoginStage','Server login not confirmed')
 settings:setGlobalSettingInt('mNoAutoLogin',resume_auto)
 return 'startup_preference_restored'
end
local a=CSLTypes.ApolloLoginController.getInstance()
local sdk=a:getAccountInfo()
if operation=='identity' then
 -- Only this operation returns secret material; no request parameters contain a credential value.
 local function hex(s) return tostring(s or ''):gsub('.',function(b)return string.format('%02x',string.byte(b))end) end
 local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.MainModel)
 local uid=main.myUserId
 local matches=uid and sdk and uid[2]==sdk.open_id
 return string.format('{"sdk_platform":%d,"openid_hex":"%s","access_token_hex":"%s","zone":%d,"server_matches":%s,"auto_login":%d}',
  sdk and tonumber(sdk.platform) or -1,hex(sdk and sdk.open_id),hex(sdk and sdk:GetAccessToken()),
  CSLTypes.QQGameSystem.getSystemInstance():getCurZoneID(),tostring(not not matches),settings:getGlobalSettingInt('mNoAutoLogin',0))
elseif operation=='watch' then
 return string.format('{"sdk_platform":%d,"sdk_flag":%d,"has_token":%s}',sdk and tonumber(sdk.platform) or -1,
  sdk and tonumber(sdk.flag) or -999,tostring(not not (sdk and sdk:GetAccessToken() and sdk:GetAccessToken()~='')))
end
assert(operation=='restore' or operation=='qr','Unsupported account operation')
assert(mobile==0 or mobile==1,'Invalid mobile platform')
assert(open_platform==0 or open_platform==1,'Invalid authorization platform')
assert(resume_auto==0 or resume_auto==1,'Invalid startup preference')
assert(package.loaded.LoginPanel.__instanceDict.getCurrentStageName({})=='LoginStage','Expected native login screen')
assert(settings:getLicenseAcceptance() and settings:getLicensePrivacyAcceptance(),'Please accept login agreements yourself')
assert(REA_ACCOUNT_AUTH_ATTEMPT==nil,'Account authentication already attempted; do not repeat')
local cls=package.loaded.LoginCloudMatrix
if type(cls)~='table' then pcall(function()return CSLTypes.LoginCloudMatrix end);cls=package.loaded.LoginCloudMatrix end
assert(cls and cls.__instanceDict,'Native platform selector unavailable')
local d=cls.__instanceDict
if operation=='qr' then
 local callbacks={ [0]={[0]='onBtnAndroidWechatClicked',[1]='onBtnAndroidQQClicked'},
                  [1]={[0]='onBtnIosWechatClicked',[1]='onBtnIosQQClicked'} }
 local callback=assert(d[callbacks[mobile][open_platform]],'Native QR entry unavailable')
 REA_ACCOUNT_AUTH_ATTEMPT='qr'
 settings:setGlobalSettingInt('mNoAutoLogin',1)
 callback({})
 return 'qr_requested'
end
local expected_sdk=open_platform==0 and 1 or 2
assert(sdk and sdk.platform==expected_sdk and sdk.open_id~='' and sdk:GetAccessToken()~='','Saved SDK ticket unavailable')
local setter,types
for i=1,10 do local name,v=debug.getupvalue(d.onBtnIosWechatClicked,i);if not name then break end
 if name=='setPlatformInfoForCloudMatrix' then setter=v elseif name=='T_TYPE' then types=v end
end
assert(setter and types and types.E_MOBILE_PLAT_TYPE_IOS==1,'Native platform selector changed')
setter({},mobile)
CSLTypes.TicketsProtocol.getInstance():setCloudMatrixIos(mobile==1)
settings:setGlobalSettingInt('mNoAutoLogin',resume_auto)
REA_ACCOUNT_AUTH_ATTEMPT='restore'
return tostring(a:canAutoLogin())
