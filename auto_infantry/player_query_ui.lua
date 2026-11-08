-- Attribute helper-owned profile replies without disabling normal game profile browsing.
if REA_PLAYER_QUERY_UI then return 'player_query_ui_installed' end
local api={};local active,interrupted,owned,pending,foreground=false,false,false,nil,{}
local patches={}
local unpack=unpack or table.unpack
local suppressed,lastProfileNotification=0,0
local externalLeases,owner=0,false
local hall=assert(package.loaded.HallMsgMgr.__instanceDict)
local friend=assert(package.loaded.FriendController.__instanceDict)
local notifier=assert(package.loaded.SceneNotifier.__instanceDict)
local findRequest=assert(friend.sendTFindUserInfoReq)
local account=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.MainModel)
local hallObject=CSLTypes.HallMsgMgr.sharedInstance()
local friendObject=CSLTypes.FriendController.sharedInstance()
local notifierObject=CSLTypes.SceneNotifier.getInstance()

-- Resolve the protocol constant from the original method, whose upvalues the wrapper does not retain.
function api.lookup_code()
 for i=1,12 do local n,v=debug.getupvalue(findRequest,i);if not n then break end
  if n=='T_ID'then return v.E_SVR_MSG_ID_FIND_GAME_USER_INFO end
 end
end

-- Compare native and reconstructed identities without relying on native table metadata.
local function same(a,b)
 return a and b and a[1]==b[1]and a[2]==b[2]and a[3]==b[3]and a[4]==b[4]
end

-- Preserve the exact original function and only undo our own wrapper during orderly disconnect.
local function patch(dict,key,make)
 local original=assert(dict[key],'Missing native profile method: '..key)
 local raw=rawget(dict,key);local wrapper=make(original);rawset(dict,key,wrapper)
 patches[#patches+1]={dict,key,raw,wrapper}
end

-- Begin a local operation only when no earlier profile reply can be confused with its result.
function api.begin()
 assert(not pending and #foreground==0,'上一笔玩家资料仍在等待响应，请稍后查询')
 active=true;interrupted=false
end

-- A manual lookup invalidates helper ownership immediately, even for the same target identity.
function api.check()
 assert(not interrupted,'检测到游戏内手动查询，助手本次查询已取消')
end

-- Limit helper request attribution to this synchronous native call, restoring the flag on errors.
function api.send(fn,...)
 api.check();if not active then api.begin()end
 local previous=owned;owned=true
 local result={pcall(fn,...)};owned=previous
 if not result[1]then error(result[2],0)end
 return unpack(result,2)
end

-- End local work while retaining a late-reply marker until its reply or explicit disconnect.
function api.finish(rejected)
 active=false;interrupted=false
 if rejected then pending=nil end
 local r=account:getCurrUserProfileRsp()
 if pending and r and r~=pending.before and r[1]~=0 then pending=nil end
 return 'player_query_finished'
end

-- Expose only local attribution state for diagnostics, never identities or credentials.
function api.status()
 return active,interrupted,pending~=nil,suppressed,lastProfileNotification
end

-- A world helper owns these shared hooks until its connection closes.
function api.claim()
 owner=true
end

-- A temporary hall query keeps the common hook alive across unrelated world-helper teardown.
function api.retain()
 externalLeases=externalLeases+1
end

-- Release only this temporary caller; idle unowned hooks restore their native methods.
function api.release()
 externalLeases=math.max(0,externalLeases-1)
 if externalLeases==0 and not owner then api.close()end
end

patch(hallObject,'sendTUserProfileReq',function(original)return function(self,uid,...)
 if owned then
  assert(not pending,'玩家资料请求尚未完成')
  pending={uid[1],uid[2],uid[3],uid[4],silent=true,before=account:getCurrUserProfileRsp()}
 else
  if active then interrupted=true end
  if pending then pending.silent=false end
  foreground[#foreground+1]={uid[1],uid[2],uid[3],uid[4]}
 end
 local helper=owned;local result={pcall(original,self,uid,...)}
 if not result[1]then if helper then pending=nil end;error(result[2],0)end
 return unpack(result,2)
end end)

patch(friendObject,'sendTFindUserInfoReq',function(original)return function(...)
 if not owned then
  if active then interrupted=true end
  if pending then pending.silent=false end
 end
 return original(...)
end end)

patch(notifierObject,'notifyStateChange',function(original)return function(self,id,...)
 if id==1039 or id==1035 then lastProfileNotification=id end
 -- The registered response delegate can retain the original parser. Intercept at the actual
 -- singleton notifier after that parser has committed its fresh, identity-matched cache.
 if id==1039 or id==1035 then
  local rsp=account:getCurrUserProfileRsp();local uid=rsp and rsp[2]and rsp[2][1]
  local helper=pending and rsp~=pending.before and rsp[1]==0 and same(uid,pending)
  local silent=helper and pending.silent and not interrupted and #foreground==0
  if helper then pending=nil end
  for i=#foreground,1,-1 do if same(uid,foreground[i])then table.remove(foreground,i);break end end
  if silent then suppressed=suppressed+1;return end
 end
 return original(self,id,...)
end end)

-- Restore native methods on disconnect; unrelated wrappers installed later are never overwritten.
function api.close()
 owner=false
 if externalLeases>0 then return end
 active=false;interrupted=false;pending=nil;foreground={}
 for i=#patches,1,-1 do local p=patches[i];if rawget(p[1],p[2])==p[4]then rawset(p[1],p[2],p[3])end end
 if REA_PLAYER_QUERY_UI==api then REA_PLAYER_QUERY_UI=nil end
end
REA_PLAYER_QUERY_UI=api
return 'player_query_ui_installed'
