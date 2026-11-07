-- Use only the tested native login path; never export tokens, signatures or unmasked account IDs.
-- Resolve lazily loaded native declarations without constructing authentication dialogs.
local function methods(name)
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 assert(cls and cls.__instanceDict,'Native login module unavailable: '..name)
 return cls.__instanceDict
end
local stage=methods('LoginPanel').getCurrentStageName({})
local settings=CSLTypes.Setting.sharedInstance()
if operation=='logout' then
 assert(stage~='LoginStage','Already on login screen')
 CSLTypes.LoginManager.sharedInstance():loginOut(true,true)
 return 'logout_requested'
elseif operation=='qr' then
 assert(stage=='LoginStage','Please return to login screen')
 assert(settings:getLicenseAcceptance() and settings:getLicensePrivacyAcceptance(),'Please accept the login agreements yourself')
 local callback=assert(methods('LoginCloudMatrix').onBtnIosWechatClicked,'Native iOS WeChat callback unavailable')
 callback({})
 return 'qr_requested'
elseif operation=='bind' then
 local manager=CSLTypes.ModelManager.sharedInstance()
 local main=manager:getModel(CSLTypes.MainModel)
 local world=manager:getModel(CSLTypes.SLGMainModel)
 local response,map=main.mTLoginRsp,world.mTSLGLoginMapRsp
 local uid=assert(main.myUserId,'Current account unavailable')
 local id={uid[1],uid[2],uid[3],uid[4]}
 assert(response and response[1]==0 and world.mIsMapLoaded and map and map[1]==0,'Current account world is not ready')
 local worldUid=map[5] and map[5][1]
 assert(worldUid and worldUid[1]==id[1] and worldUid[2]==id[2] and worldUid[3]==id[3] and worldUid[4]==id[4],
  'Account session changed; world cache does not belong to the current account')
 -- Compare live models as well as values: logout can leave the old objects otherwise unchanged.
 REA_HELPER_SESSION_VALID=function()
  local current=CSLTypes.ModelManager.sharedInstance()
  local live=current:getModel(CSLTypes.MainModel)
  local wm=current:getModel(CSLTypes.SLGMainModel)
  local u=live.myUserId
  return live==main and wm==world and live.mTLoginRsp==response and wm.mTSLGLoginMapRsp==map and wm.mIsMapLoaded==true
   and u and u[1]==id[1] and u[2]==id[2] and u[3]==id[3] and u[4]==id[4]
 end
 return 'session_bound'
end
assert(operation=='status','Unsupported login operation')
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.MainModel)
local r=main.mTLoginRsp
local uid=main.myUserId or {}
local tickets=package.loaded.TicketsProtocol.__instanceDict._instance
local info=tickets and tickets:getLoginInfo()
local logged=info and info:isLogined() and type(r)=='table' and r[1]==0 and stage~='LoginStage'
local name=type(r)=='table' and tostring(r[6] or '') or ''
local hex=name:gsub('.',function(c) return string.format('%02x',string.byte(c)) end)
return string.format('{"stage":"%s","agreement":%s,"logged_in":%s,"ret":%d,"nickname_hex":"%s","level":%d,"open_platform":%d,"mobile_platform":%d}',
 tostring(stage):gsub('[^%w_]',''),tostring(settings:getLicenseAcceptance() and settings:getLicensePrivacyAcceptance()),
 tostring(not not logged),type(r)=='table' and tonumber(r[1]) or -999,hex,type(r)=='table' and tonumber(r[2]) or 0,
 tonumber(uid[3]) or -1,tonumber(uid[4]) or -1)
