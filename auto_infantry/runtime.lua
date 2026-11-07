-- Install a caller-driven API. This module never schedules autonomous game actions.
local api = {version=2, train_seq=0, speed_seq=0, barrack_seq=0}
local validUnits = {[411]=true, [412]=true, [413]=true, [803]=true}

-- Reject unknown troop identifiers before reading or sending a business command.
local function checkedUnit(unit)
 unit=unit or 411
 assert(validUnits[unit], "Unsupported troop identifier")
 return unit
end
local manager=CSLTypes.ModelManager.sharedInstance()
local model=manager:getModel(CSLTypes.SLGBuildingsModel)
local items=manager:getModel(CSLTypes.ItemsModel)
local main=manager:getModel(CSLTypes.SLGMainModel)
local boundMap=main.mTSLGLoginMapRsp
local boundConfig=main.mMapConfigID
assert(type(boundMap)=="table" and main.mIsMapLoaded, "World map is not ready")
local controller=package.loaded.SLGBuildingsController.__instanceDict._instance
assert(type(controller)=="table", "Buildings controller is not initialized")
-- Resolve lazy native declarations without constructing or opening any game dialog.
local function nativeMethods(name)
 local cls=package.loaded[name]
 if type(cls)~='table' then
  local ok,value=pcall(function() return CSLTypes[name] end)
  cls=package.loaded[name] or (ok and value)
 end
 if type(cls)~='table' then
  local ok,value=pcall(require,name);if ok then cls=value end
 end
 assert(type(cls)=='table' and type(cls.__instanceDict)=='table','Native module unavailable: '..name)
 return cls.__instanceDict
end
local use=nativeMethods('UpgradeAccelerationNewDialog').useButtonCallback
assert(type(use)=='function','Native acceleration callback unavailable')
local itemName, itemType=debug.getupvalue(use,2)
assert(itemName=="T_TItemInfo" and type(itemType)=="userdata", "Unexpected item constructor layout")
local util=require("jit.util")
assert(util.funcinfo(controller.sendTSLGTrainSoldierReq).params==2 and util.funcinfo(controller.sendTSLGBuildSpeedupReq).params==5,
 "Business function signatures changed; helper stopped")
local trainRef, speedRef, barrackRef
local upgradePredicate

-- Reuse the native barrack UI predicate; unknown native layout must never authorize training.
local function upgradeState()
 local ok,result=pcall(function()
  if not upgradePredicate then
   local cls=package.loaded.BarracksDialog
   if type(cls)~='table' then pcall(function() return CSLTypes.BarracksDialog end);cls=package.loaded.BarracksDialog end
   if type(cls)~='table' then local loaded,value=pcall(require,'BarracksDialog');if loaded then cls=value end end
   local init=type(cls)=='table' and cls.__instanceDict and cls.__instanceDict.initArmTrainingList
   assert(type(init)=='function','Native barrack predicate unavailable')
   for i=1,20 do local name,value=debug.getupvalue(init,i);if not name then break end
    if name=='checkIsUpdating' and type(value)=='function' then upgradePredicate=value;break end
   end
  end
  assert(upgradePredicate,'Native barrack predicate changed')
  local value=upgradePredicate();assert(type(value)=='boolean','Unknown barrack upgrade state')
  return value
 end)
 return ok,ok and result or false
end

-- Guard even read-only initialization requests against a changed world/session context.
local function checkedMap()
 assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==boundMap and main.mMapConfigID==boundConfig, "World map changed; reconnect the helper")
end

-- Observe response generations without requiring a pre-existing barrack cache after account switching.
function api.barrack_probe()
 checkedMap()
 local rsp=model:getTSLGGetBarrackRsp()
 if rsp~=barrackRef then api.barrack_seq=api.barrack_seq+1;barrackRef=rsp end
 local received=type(rsp)=='table' and type(rsp[1])=='number'
 return string.format('{"received":%s,"ret":%d,"barrack_seq":%d}',
  tostring(received),received and rsp[1] or -999,api.barrack_seq)
end

-- Read the live numeric field layout verified against the current 4.31.0 responses.
function api.status(unit)
 unit=checkedUnit(unit)
 checkedMap()
 local rsp=model:getTSLGGetBarrackRsp()
 assert(type(rsp)=="table" and rsp[1]==0, "Barrack response unavailable or unsuccessful")
 local army=rsp[4]:get_Item(unit)
 assert(type(army)=="table" and type(army[3])=="table", "Infantry state unavailable")
 local count,deployed,limit,pending,left=army[3][1],army[3][2],army[6],army[3][4],army[3][3]
 assert(type(count)=="number" and type(limit)=="number" and limit>0 and limit<=1000, "Invalid infantry capacity")
 assert(type(deployed)=="number" and deployed>=0 and count>=0 and count+deployed<=limit and pending>=0 and pending<=army[2] and left>=0, "Invalid infantry queue")
 local tr=model._stTSLGTrainSoldierRsp
 local sr=model._stTSLGBuildSpeedupRsp
 if tr~=trainRef then api.train_seq=api.train_seq+1;trainRef=tr end
 if sr~=speedRef then api.speed_seq=api.speed_seq+1;speedRef=sr end
 if rsp~=barrackRef then api.barrack_seq=api.barrack_seq+1;barrackRef=rsp end
 local stock=items:getItemCount(70251)
 local upgradeKnown,upgrading=upgradeState()
 return string.format('{"soldier_id":%d,"count":%d,"deployed":%d,"limit":%d,"pending":%d,"queue_capacity":%d,"remaining_ms":%d,"duration_ms":%d,"items":%d,"train_seq":%d,"speed_seq":%d,"barrack_seq":%d,"train_ret":%d,"speed_ret":%d,"train_unit":%d,"speed_unit":%d,"upgrade_known":%s,"upgrading":%s}',
 unit,count,deployed,limit,pending,army[2],left,army[1]*1000,stock,api.train_seq,api.speed_seq,api.barrack_seq,
 type(tr)=="table" and tr[1] or -999,type(sr)=="table" and sr[1] or -999,
 type(tr)=="table" and tr[2] or -1,type(sr)=="table" and sr[4] or -1,tostring(upgradeKnown),tostring(upgrading))
end

-- Refresh server state without opening a building window or spending resources.
function api.refresh()
 checkedMap()
 controller:sendTSLGGetBarrackReq()
 return "refresh_sent"
end

-- Submit one training only after native capacity, queue and current building-upgrade guards pass.
function api.train(unit)
 unit=checkedUnit(unit)
 api.status(unit)
 local rsp=model:getTSLGGetBarrackRsp()
 local army=rsp[4]:get_Item(unit)
 assert(army[3][1]+army[3][2]+army[3][4]<army[6], "Infantry capacity already reached")
 assert(army[3][4]<army[2], "Training queue is full")
 local known,upgrading=upgradeState()
 assert(known and not upgrading,'REA_BARRACK_TRAINING_UNAVAILABLE')
 controller:sendTSLGTrainSoldierReq(unit)
 return "train_sent"
end

-- Use exactly one specified training item, rebuilding identity through the game's own sender.
function api.speed(unit)
 unit=checkedUnit(unit)
 api.status(unit)
 local rsp=model:getTSLGGetBarrackRsp()
 local army=rsp[4]:get_Item(unit)
 assert(army[3][4]>0 and army[3][3]>0, "No infantry training to accelerate")
 assert(items:getItemCount(70251)>0, "Five-minute training items exhausted")
 local vec=CSLNew(CSLTypes.CSLList)
 local item=CSLNew(itemType)
 item[1]=70251
 item[2]=1
 vec:Add(item)
 controller:sendTSLGBuildSpeedupReq(3,400,unit,vec)
 return "speed_sent"
end

_G.REA_AUTO_INFANTRY=api
return 'troop_api_installed'
