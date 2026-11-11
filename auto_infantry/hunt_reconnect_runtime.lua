-- Passive native reconnection witness. Private account identifiers never leave this closure.
local old=REA_HUNT_RECONNECT
if old then old.close() end
local mm=CSLTypes.ModelManager.sharedInstance()
local account=mm:getModel(CSLTypes.MainModel)
local main=mm:getModel(CSLTypes.SLGMainModel)
local uid=assert(account.myUserId)
local identity={uid[1],uid[2],uid[3],uid[4]}
local scope=main:getTMapGameDataID()
local mapId,zoneId=scope[1],scope[2]
local started,finished,invalid,closed=false,false,false,false
local api={};REA_HUNT_RECONNECT=api
local observer={class={name='REAHuntReconnectWitness'}}

-- An actual role or world change is terminal; an unloaded old world is only a temporary wait.
local function sameScope()
 local a=mm:getModel(CSLTypes.MainModel);local m=mm:getModel(CSLTypes.SLGMainModel)
 local u=a and a.myUserId;local s=m and m:getTMapGameDataID()
 if not u or not s then return false end
 if (not u[1] or u[1]==0)and(not u[2]or u[2]=='')then return false end
 if not s[1]or s[1]==0 or not s[2]then return false end
 for i=1,4 do if u[i]~=identity[i] then invalid='account';return false end end
 if s[1]~=mapId or s[2]~=zoneId then invalid='map';return false end
 return true
end

-- Callback handlers are hints only: they never query, log in, dispatch or skip a battle.
function observer:NotifyReplayStart()
 started=true;finished=false
end
function observer:NotifyConnectSuc() end
function observer:NotifyReplayLoginSuc()
 if started then finished=true;sameScope() end
end

-- Fence existing queued work as soon as the native reconnection starts.
function api.paused()return started or invalid or closed end

-- At the single delayed attempt, confirm the current cache even when only the helper transport was lost.
function api.recovery_status(key)
 if key~=reconnectKey or closed then return 'unverified' end
 local same=sameScope()
 if invalid then return invalid end
 if not same or (started and not finished) then return 'pending' end
 local a=mm:getModel(CSLTypes.MainModel);local m=mm:getModel(CSLTypes.SLGMainModel)
 local login,world=a.mTLoginRsp,m.mTSLGLoginMapRsp
 local u=world and world[5] and world[5][1]
 if not login or login[1]~=0 or not world or world[1]~=0 or not u or m.mIsMapLoaded~=true then return 'pending' end
 for i=1,4 do if u[i]~=identity[i] then return 'pending' end end
 return 'ready'
end

-- Unregister only our callback; normal game reconnection and all other observers remain untouched.
function api.close()
 if not closed then CSLTypes.Reconnection.unRegisterReconnection(observer);closed=true end
end
CSLTypes.Reconnection.RegisterReconnection(observer)
return 'hunt_reconnect_witness_installed'
