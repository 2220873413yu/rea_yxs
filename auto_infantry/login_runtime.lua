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
 -- Validate and bind in the same game update so a role change cannot slip between them.
 if recoveryKey then
  if not REA_HUNT_RECONNECT then return 'unverified' end
  local reason=REA_HUNT_RECONNECT.recovery_status(recoveryKey)
  if reason~='ready' then return reason end
  local tickets=package.loaded.TicketsProtocol and package.loaded.TicketsProtocol.__instanceDict._instance
  local info=tickets and tickets:getLoginInfo()
  if stage=='LoginStage' or stage=='MainHallSceneStage' or not info or not info:isLogined() then return 'pending' end
 end
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
  if not u then return false,'account_unavailable' end
  for i=1,4 do if u[i]~=id[i] then return false,'account_identity_changed' end end
  if REA_HUNT_RECONNECT and REA_HUNT_RECONNECT.paused() then return false,'native_reconnect' end
  if not wm or wm.mIsMapLoaded~=true then return false,'map_not_loaded' end
  if live~=main or live.mTLoginRsp~=response then return false,'login_data_replaced' end
  if wm~=world or wm.mTSLGLoginMapRsp~=map then return false,'map_data_replaced' end
  return true
 end
 return 'session_bound'
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.MainModel)
local r=main.mTLoginRsp
local uid=main.myUserId or {}
local tickets=package.loaded.TicketsProtocol.__instanceDict._instance
local info=tickets and tickets:getLoginInfo()
local logged=info and info:isLogined() and type(r)=='table' and r[1]==0 and stage~='LoginStage'
if operation=='identity_key' then
 -- Python hashes this local identity before publishing role metadata to either tab.
 local identity=logged and type(uid[2])=='string' and uid[2] or ''
 local hex=identity:gsub('.',function(c) return string.format('%02x',string.byte(c)) end)
 local zone=logged and CSLTypes.QQGameSystem.getSystemInstance():getCurZoneID() or 0
 return string.format('{"identity_hex":"%s","identity_zone":%d,"open_platform":%d,"mobile_platform":%d}',
  hex,tonumber(zone) or 0,tonumber(uid[3]) or -1,tonumber(uid[4]) or -1)
end
assert(operation=='status','Unsupported login operation')
local name=type(r)=='table' and tostring(r[6] or '') or ''
local hex=name:gsub('.',function(c) return string.format('%02x',string.byte(c)) end)
return string.format('{"stage":"%s","agreement":%s,"logged_in":%s,"ret":%d,"nickname_hex":"%s","level":%d,"open_platform":%d,"mobile_platform":%d}',
 tostring(stage):gsub('[^%w_]',''),tostring(settings:getLicenseAcceptance() and settings:getLicensePrivacyAcceptance()),
 tostring(not not logged),type(r)=='table' and tonumber(r[1]) or -999,hex,type(r)=='table' and tonumber(r[2]) or 0,
 tonumber(uid[3]) or -1,tonumber(uid[4]) or -1)
