-- Caller-driven resource queries and guarded collection. No autonomous work is scheduled here.
local api=assert(REA_AUTO_INFANTRY,'Hero API required')
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local buildings=manager:getModel(CSLTypes.SLGBuildingsModel)
local search=CSLTypes.DBSearcher.sharedInstance()
local ctrl=assert(package.loaded.SLGMainController.__instanceDict._instance)
local sceneNotifier=CSLTypes.SceneNotifier.getInstance()
local tripModel=manager:getModel(CSLTypes.SLGArmyTripModel)
local _,clock=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
local encode=api.encode_flat_state
local detail,available
local detailSeq,availableSeq=0,0
local detailAt,availableAt=-1e15,-1e15
local pendingTarget
local targetKinds={}
local observerFailed=false
local mainRegistered,sceneRegistered,tripRegistered=false,false,false
local wantDetail,wantAvailable,suppressAvailableState=false,false,false
local mainRaw,sceneRaw,stateRaw
local mainWrapper,sceneWrapper,stateWrapper
local observer={class={name='REACollectionObserver'}}
local pushSeq=0
local pushObserver={class={name='REACollectionPushObserver'}}

-- Treat native own-army status notifications as wake hints only; never query or spend in a callback.
function pushObserver:updateSelf(param)
 if not param or param.id~=2 or type(param.updateData)~='table' then return end
 local ok,own=pcall(main.checkIsMyArmy,param.updateData)
 if ok and own==true then
  pushSeq=pushSeq+1
  if api.note_army_push then pcall(api.note_army_push,param.updateData) end
 end
end

-- Return a local notification counter without reading or requesting any server state.
function api.collect_push_status()
 return string.format('{"seq":%d}',pushSeq)
end

-- Export server-provided stage deadlines with the same server clock; never estimate from resource rates.
function api.collect_schedule()
 local world=api.read_hero_state()
 assert(world.fresh and world.army_known,'Fresh army state is required for collection scheduling')
 local rows={}
 local armies=main._myActionState[2]
 for i=0,armies:get_Count()-1 do
  local army=armies:get_Item(i)
  if army[5]==0 or army[5]==1 then
   if army[5]==1 and army[4]~=7 and army[4]~=9 then
    assert(type(army[6])=='number' and army[6]>0,'Collection army target is unknown')
   end
   rows[#rows+1]=encode({army_id=army[1],state=army[4],hero_id=army[15][1],aim=army[5],target_id=army[6],
    end_ms=type(army[11])=='number' and army[11] or 0})
  end
 end
 return '{"server_now_ms":'..string.format('%.0f',clock():GetCurrentServerTime()*1000)..
  ',"stages":['..table.concat(rows,',')..']}'
end

-- Read live stock and carried resource items from all own armies, including manual trips and returns.
function api.collect_balance_state()
 local world=api.read_hero_state()
 assert(world.fresh and world.army_known,'Fresh army state is required for resource balancing')
 local stock=main:getMySLGResource()
 assert(type(stock)=='table','Current resource stock unavailable')
 for k=1,3 do assert(type(stock[k])=='number' and stock[k]>=0,'Invalid current resource stock') end
 local queue=api.read_collection_queue(world)
 assert(queue.queue_known and queue.queue_limit>0,'Collection queue limit unavailable')
 local rows,seen={},{}
 -- TSLGGetAllArmyRsp[3] is enemy armies; only [2] owns our resource income.
 for _,index in ipairs({2}) do
  local armies=main._myActionState[index]
  assert(type(armies)=='table' and armies.get_Count,'Own army list unavailable')
  for i=0,armies:get_Count()-1 do
   local army=armies:get_Item(i)
   assert(type(army[1])=='number' and type(army[4])=='number' and type(army[5])=='number','Invalid own army')
   if not seen[army[1]] and army[4]~=7 then
    seen[army[1]]=true
    local cargo={0,0,0};local items=army[12]
    assert(type(items)=='table' and items.get_Count,'Army carried items unavailable')
    for j=0,items:get_Count()-1 do
     local item=items:get_Item(j);local kind=item[1]-70000
     if kind>=1 and kind<=3 then
      assert(type(item[2])=='number' and item[2]>=0,'Invalid army carried resource')
      cargo[kind]=cargo[kind]+item[2]
     end
    end
    rows[#rows+1]=encode({army_id=army[1],state=army[4],aim=army[5],target_id=army[6],hero_id=army[15][1],
     carried_food=cargo[1],carried_wood=cargo[2],carried_iron=cargo[3]})
   end
  end
 end
 return '{"food":'..string.format('%.0f',stock[1])..',"wood":'..string.format('%.0f',stock[2])..
  ',"iron":'..string.format('%.0f',stock[3])..',"queue_limit":'..queue.queue_limit..
  ',"armies":['..table.concat(rows,',')..']}'
end

-- Resolve existing game class declarations lazily; creating a background query never creates UI objects.
local function methods(name)
 local cls=package.loaded[name]
 if type(cls)~='table' then
  pcall(function() return CSLTypes[name] end)
  cls=package.loaded[name]
  if type(cls)~='table' then local ok,value=pcall(require,name);if ok then cls=value end end
 end
 assert(type(cls)=='table' and type(cls.__instanceDict)=='table','Game class unavailable: '..name)
 return cls.__instanceDict
end

-- Retain only matching native response objects; no original handler or UI callback is replaced.
function observer:updateSelf(param)
 local ok=pcall(function()
  local payload=param and param.updateData
  if type(payload)~='table' or payload[1]~=0 then return end
  if param.id==-9995 then
   local id=payload[2][1][1][2]
   if id==pendingTarget then detail=payload;detailSeq=detailSeq+1;detailAt=clock():GetCurrentServerTime()*1000 end
  elseif param.id==1060 and payload[3]==1 and payload[2]==pendingTarget then
   available=payload;availableSeq=availableSeq+1;availableAt=clock():GetCurrentServerTime()*1000
  end
 end)
 if not ok then observerFailed=true end
end

-- Explicitly release model observers on detach so they cannot retain account state or leak callbacks.
function api.collect_close()
 if mainRegistered then mainRegistered=not pcall(main.removeObserver,main,observer) end
 if sceneRegistered then sceneRegistered=not pcall(sceneNotifier.removeObserver,sceneNotifier,observer) end
 if tripRegistered then tripRegistered=not pcall(tripModel.removeObserver,tripModel,pushObserver) end
 if mainWrapper and rawget(main,'notifyUpdateData')==mainWrapper then rawset(main,'notifyUpdateData',mainRaw) end
 if sceneWrapper and rawget(sceneNotifier,'notifyUpdateData')==sceneWrapper then rawset(sceneNotifier,'notifyUpdateData',sceneRaw) end
 if stateWrapper and rawget(main,'notifyStateChange')==stateWrapper then rawset(main,'notifyStateChange',stateRaw) end
 if main.observers and main.observers.Contains then assert(not main.observers:Contains(observer),'Resource observer cleanup failed') end
 if sceneNotifier.observers and sceneNotifier.observers.Contains then assert(not sceneNotifier.observers:Contains(observer),'Selection observer cleanup failed') end
 if tripModel.observers and tripModel.observers.Contains then assert(not tripModel.observers:Contains(pushObserver),'Army push observer cleanup failed') end
 assert(not mainRegistered and not sceneRegistered and not tripRegistered,'Collection observer cleanup is incomplete')
 detail=nil;available=nil;pendingTarget=nil
 return 'collection_closed'
end
local registered=pcall(function()
 main:addObserver(observer);mainRegistered=true
 sceneNotifier:addObserver(observer);sceneRegistered=true
 tripModel:addObserver(pushObserver);tripRegistered=true
end)
if not registered then api.collect_close();error('Collection observer registration failed') end

-- The game's query handlers normally open resource/selection UI. Consume only our outstanding,
-- exact-target notifications; unrelated/manual notifications retain their original implementation.
mainRaw=rawget(main,'notifyUpdateData');sceneRaw=rawget(sceneNotifier,'notifyUpdateData');stateRaw=rawget(main,'notifyStateChange')
local originalMain=main.notifyUpdateData
local originalScene=sceneNotifier.notifyUpdateData
local originalState=main.notifyStateChange
mainWrapper=function(self,id,payload,...)
 if self==main and id==-9995 and wantDetail and type(payload)=='table' then
  local ok,target=pcall(function() return payload[2][1][1][2] end)
  if ok and target==pendingTarget then
   wantDetail=false;observer:updateSelf({id=id,updateData=payload});return
  end
 end
 return originalMain(self,id,payload,...)
end
sceneWrapper=function(self,id,payload,...)
 if self==sceneNotifier and id==1060 and wantAvailable and type(payload)=='table' and
  payload[2]==pendingTarget and payload[3]==1 then
  wantAvailable=false;suppressAvailableState=true;observer:updateSelf({id=id,updateData=payload});return
 end
 return originalScene(self,id,payload,...)
end
stateWrapper=function(self,id,...)
 if self==main and id==-9991 and suppressAvailableState then suppressAvailableState=false;return end
 return originalState(self,id,...)
end
rawset(main,'notifyUpdateData',mainWrapper)
rawset(sceneNotifier,'notifyUpdateData',sceneWrapper)
rawset(main,'notifyStateChange',stateWrapper)

-- Query the caller-selected resource ID, invalidating earlier target responses first.
function api.collect_query(target)
 assert(type(target)=='number' and target==math.floor(target) and target>0,'Invalid resource target')
 api.read_hero_state()
 methods('SLGResourceCommonDialog');methods('SLGChooseHeroItem')
 assert(not observerFailed,'Collection observer state is uncertain')
 pendingTarget=target;detail=nil;available=nil;wantDetail=true;wantAvailable=true
 ctrl:sendTSLGResourceInfo(target)
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq(target,1,0,0)
 return 'collection_query_sent'
end

-- Include our own inbound teams; the resource's resident list alone misses armies still marching.
local function ownResourceTargetInUse(target)
 local state=main._myActionState
 local armies=state and state[1]==0 and state[2]
 if type(armies)~='table' or not armies.get_Count then return nil end
 for i=0,armies:get_Count()-1 do
  local army=armies:get_Item(i)
  if army[5]==1 and army[4]~=7 and army[4]~=9 then
   if type(army[6])~='number' or army[6]<=0 or type(army[4])~='number' then return nil end
   if army[6]==target then return true end
  end
 end
 return false
end

-- Require known slots and combine resident occupancy with current own-action destinations.
local function resourceSlots(response,config)
 local capacity=config[9]
 local occupied=response[2][2]:get_Count()
 local ok,own=pcall(main.isMyArmyExist_InResourceField,response[2][1])
 local inbound=ownResourceTargetInUse(response[2][1][1][2])
 local known=type(capacity)=='number' and capacity>0 and capacity==math.floor(capacity) and
  type(occupied)=='number' and occupied>=0 and occupied==math.floor(occupied) and ok and type(own)=='boolean' and
  type(inbound)=='boolean'
 return known,capacity,occupied,own==true or inbound==true
end

-- Export configured slot capacity and own presence alongside the native relationship decision.
function api.collect_status()
 local world=api.read_hero_state()
 local queue=api.read_collection_queue(world)
 local state={detail_seq=detailSeq,available_seq=availableSeq,target_id=pendingTarget or 0,ready=false,observer_error=observerFailed,
  queue_free=queue.queue_free,queue_used=queue.queue_used,queue_known=queue.queue_known,queue_limit=queue.queue_limit,
  queue_reason=queue.queue_reason}
 if detail and available then
  local now=clock():GetCurrentServerTime()*1000
  local point=detail[2][1]
  local config=search:searchTNewPlay_Resource_Map(point[2])
  local pos=point[1][1]
  local shown=CSLTypes.SLGMapUtils.logicToDisplay(pos)
  local ok,can=pcall(methods('SLGResourceCommonDialog').canCollect,
   {mTSLGResourceInfoRsp=detail,mTNewPlay_Resource=config})
  local slotsKnown,capacity,used,own=resourceSlots(detail,config)
  state.ready=true;state.fresh=now>=detailAt and now>=availableAt and now-detailAt<=3000 and now-availableAt<=3000
  state.detail_age_ms=now-detailAt;state.available_age_ms=now-availableAt
  state.can_collect=ok and can==true;state.rules_known=ok and slotsKnown
  state.capacity=capacity;state.own_present=slotsKnown and own==true
  state.kind=config[3];state.level=config[2];state.config_id=point[2]
  if state.fresh then targetKinds[pendingTarget]=config[3] end
  state.x=shown[1];state.y=shown[2];state.quantity=point[6];state.occupants=used
  -- The native check reports 'limit reached', rather than 'a free queue exists'.
  state.queue_free=queue.queue_free
 end
 return encode(state)
end

-- Return target-specific hero speed/load and native action state; busy heroes remain visible but ineligible.
function api.collect_metrics()
 assert(detail and available,'Resource query is incomplete')
 local rows={}
 local heroes=available[4]
 local state=api.collect_status()
 for i=0,heroes:get_Count()-1 do
  local hero=heroes:get_Item(i)
  local id=hero[1][1][3]
  local base=api.read_hero_state(id)
  rows[#rows+1]=encode({hero_id=id,name=base.name,speed=hero[6],load=hero[5],travel_seconds=hero[3],
   action_state=methods('SLGChooseHeroItem').getActionState(hero),
   hero_state=hero[1][2],finish_ms=hero[1][3],busy=base.busy,found=base.found,
   fresh=base.fresh,army_known=base.army_known,power=hero[4]})
 end
 local collectors={}
 local residents=detail[2][2]
 for i=0,residents:get_Count()-1 do
  local info=residents:get_Item(i);local army=info[1]
  collectors[#collectors+1]=encode({army_id=army[1],hero_id=army[15][1],count=info[2],maximum=info[3]})
 end
 return '{"target":'..state..',"heroes":['..table.concat(rows,',')..'],"collectors":['..table.concat(collectors,',')..']}'
end

-- Enumerate loaded points; zero kind/level/range remove those filters for saved-list collection.
function api.collect_candidates(kind,level,maxRange)
 assert(kind==0 or kind==1 or kind==2 or kind==3,'Unsupported resource kind')
 assert(type(level)=='number' and level>=0 and level<=10 and level==math.floor(level),'Invalid resource level')
 assert(type(maxRange)=='number' and maxRange>=0 and maxRange<=100,'Invalid collection range')
 api.read_hero_state()
 local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
 local home=map:getMyMainCityCoordinates()
 local rows,seen={},{}
 for i=0,chunks:get_Count()-1 do
  local chunk=chunks:get_Item(i).mViewDataCache
  if chunk:ContainsKey(1000) then
   local points=chunk:get_Item(1000)
   local keys=points:GetDictKeys()
   for j=0,keys:get_Count()-1 do
    local key=keys:get_Item(j)
    if not seen[key] then
     seen[key]=true
     local point=points:get_Item(key)
     local config=search:searchTNewPlay_Resource_Map(point[2])
     local pos=CSLTypes.SLGMapUtils.keyToPos(key)
     local distance=math.max(0,CSLTypes.SLGMapUtils.calMapP2PDistance(home,pos)-1)
     if (config[3]==1 or config[3]==2 or config[3]==3) and (kind==0 or config[3]==kind) and
      (level==0 or config[2]==level) and (maxRange==0 or distance<=maxRange) then
      local shown=CSLTypes.SLGMapUtils.logicToDisplay(pos)
      rows[#rows+1]=encode({target_id=point[1][2],kind=config[3],level=config[2],x=shown[1],y=shown[2],
       distance=distance,quantity=point[6],occupants=point[4]:get_Count()})
     end
    end
   end
  end
 end
 return '['..table.concat(rows,',')..']'
end

-- Plan overlapping24/18 queries for missing saved coordinates; verify display conversion on this map.
function api.collect_region_plan(...)
 api.read_hero_state()
 local args={...};assert(#args>0 and #args<=200 and #args%2==0,'Invalid saved-coordinate batch')
 local cfg=map.mInViewDataChunkCacheManager.mtNewPlay_Map
 local width,height=cfg[10],cfg[11]
 assert(type(width)=='number' and type(height)=='number' and width>0 and height>0,'Map size unavailable')
 local groups,order={},{};local home=map:getMyMainCityCoordinates()
 for i=1,#args,2 do
  local x,y=args[i],args[i+1];local ly=height-y
  assert(type(x)=='number' and type(y)=='number' and x==math.floor(x) and y==math.floor(y) and
   x>=0 and x<width and ly>=0 and ly<height,'Saved resource coordinate is outside this map')
  local pos={[1]=x,[2]=ly,[3]=0};local shown=CSLTypes.SLGMapUtils.logicToDisplay(pos)
  assert(shown[1]==x and shown[2]==y,'Saved-coordinate conversion changed')
  local cx=math.min(math.floor(x/40)*40+20,width-1)
  local cy=math.min(math.floor(ly/30)*30+15,height-1)
  local key=cx..':'..cy
  if not groups[key] then
   groups[key]={x=cx,y=cy,distance=CSLTypes.SLGMapUtils.calMapP2PDistance(home,{cx,cy,0}),points={}}
   order[#order+1]=groups[key]
  end
  groups[key].points[#groups[key].points+1]='['..x..','..y..']'
 end
 table.sort(order,function(a,b) if a.distance~=b.distance then return a.distance<b.distance end
  if a.x~=b.x then return a.x<b.x end;return a.y<b.y end)
 local rows={}
 for _,g in ipairs(order) do
  local head=encode({x=g.x,y=g.y,distance=g.distance})
  rows[#rows+1]=string.sub(head,1,-2)..',"coordinates":['..table.concat(g.points,',')..']}'
 end
 return '{"regions":['..table.concat(rows,',')..']}'
end

-- Use the collection gate for area loads, independently of whether automatic hunting is enabled.
function api.collect_region_query(x,y)
 api.read_hero_state();return api.hunt_region_query(x,y)
end

-- Keep only an exact completed region response; an empty map cache is never a missing-resource refusal.
function api.collect_region_read(seq,x,y)
 api.hunt_region_assert(seq,x,y)
 return api.collect_candidates(0,0,0)
end

-- Recheck type diversity against current own actions immediately before a balanced departure.
local function checkBalanceLimit(kind)
 local limit=main:getMaxCollectionArmyCount()
 assert(type(limit)=='number' and limit>0,'Collection queue limit unavailable')
 local cap=math.max(1,math.ceil(limit/2));local count=0;local seen={}
 local armies=main._myActionState[2]
 for i=0,armies:get_Count()-1 do local army=armies:get_Item(i)
  if army[5]==1 and army[4]~=7 and army[4]~=9 and not seen[army[1]] then
   seen[army[1]]=true
   local known=targetKinds[army[6]]
   if not known then
    local goods=army[12];local kinds={}
    if goods and goods.get_Count then for j=0,goods:get_Count()-1 do local item=goods:get_Item(j)
     if item[1]>=70001 and item[1]<=70003 and item[2]>0 then kinds[item[1]-70000]=true end
    end end
    for k in pairs(kinds) do assert(not known,'Collection army resource kind uncertain');known=k end
   end
   assert(known==1 or known==2 or known==3,'Collection army resource kind uncertain')
   if known==kind then count=count+1 end
  end
 end
 assert(count<cap,'Collection same-resource limit reached')
end

-- Recheck one formation using the same cooldown eligibility as the Python planner.
function api.collect_dispatch(target,heroId,kind,level,expectedDetail,expectedAvailable,radius,expectedX,expectedY,balanceGuard,useHeroRecovery)
 assert(not observerFailed,'Collection observer state is uncertain')
 local chosenSoldier=methods('SLGChosenSoldier')
 local collectLogic=methods('SLGChooseHeroLogicCollectResource')
 assert(target==pendingTarget and detail and available,'Collection target changed')
 assert(expectedDetail==detailSeq and expectedAvailable==availableSeq,'Collection query generation changed')
 local raw=api.read_hero_state(heroId)
 if not (raw.found and raw.fresh and raw.army_known and not raw.busy and raw.hero_state==0 and raw.remaining_ms<=0) then
  return 'collection_replan:hero_state'
 end
 local now=clock():GetCurrentServerTime()*1000
 if not (now>=detailAt and now>=availableAt and now-detailAt<=3000 and now-availableAt<=3000) then
  return 'collection_replan:stale'
 end
 local point=detail[2][1]
 local display=CSLTypes.SLGMapUtils.logicToDisplay(point[1][1])
 assert(display[1]==expectedX and display[2]==expectedY,'Collection coordinates changed')
 assert(type(radius)=='number' and radius>=0 and radius<=100 and (radius==0 or
  math.max(0,CSLTypes.SLGMapUtils.calMapP2PDistance(map:getMyMainCityCoordinates(),point[1][1])-1)<=radius),
  'Resource is outside the selected range')
 local config=search:searchTNewPlay_Resource_Map(point[2])
 assert(config[3]==kind and config[2]==level and point[6]>0,'Resource kind, level or stock changed')
 assert(level<4 or point[6]>=40000,'Resource remaining quantity is below40000 for level4 or higher')
 local slotsKnown,capacity,occupied,own=resourceSlots(detail,config)
 assert(slotsKnown,'Resource slot state is unknown')
 assert(not own,'An own army is already collecting at this resource')
 assert(occupied<capacity,'Resource collection slots are full')
 assert(main:checkMaxCollectionArmyCount()~=true,'Collection queue limit reached')
 if balanceGuard==1 then checkBalanceLimit(kind) end
 assert(methods('SLGResourceCommonDialog').canCollect(
  {mTSLGResourceInfoRsp=detail,mTNewPlay_Resource=config})==true,'Native collection rules reject this target')
 local best
 for i=0,available[4]:get_Count()-1 do
  local h=available[4]:get_Item(i)
  local id=h[1][1][3]
  local state=api.read_hero_state(id)
  local action=methods('SLGChooseHeroItem').getActionState(h)
  local eligibleAction=(action==0 and state.remaining_ms==0) or (useHeroRecovery==1 and (action==0 or action==5))
  if state.found and state.fresh and state.army_known and not state.busy and state.hero_state==0 and
   eligibleAction and h[6]>0 then
   if not best or h[6]>best[6] or (h[6]==best[6] and (h[5]>best[5] or
    (h[5]==best[5] and (h[3]<best[3] or (h[3]==best[3] and id<best[1][1][3]))))) then best=h end
  end
 end
 if not (best and best[1][1][3]==heroId and methods('SLGChooseHeroItem').getActionState(best)==0) then
  return 'collection_replan:selection'
 end
 -- The native selection scene uses this hero's first soldier option, not a universal infantry ID.
 local options=best[2]
 assert(type(options)=='table' and options.get_Count and options:get_Count()>0,'Hero follower options are unavailable')
 local follower=options:get_Item(0)
 local soldierId=type(follower)=='table' and follower[1]
 assert(soldierId==411 or soldierId==412 or soldierId==413,'Unsupported hero follower species')
 assert(type(follower[2])=='number' and follower[2]>=2,'Two compatible hero followers are required')
 local barrack=buildings:getTSLGGetBarrackRsp()
 local stock=barrack and barrack[1]==0 and barrack[4]:get_Item(soldierId)
 assert(type(stock)=='table' and type(stock[3])=='table' and type(stock[3][1])=='number' and stock[3][1]>=2,
  'Two compatible hero followers are required')
 local name,soldierType=debug.getupvalue(chosenSoldier.initialize,1)
 assert(name=='T_TSoldierInfo','Soldier constructor changed')
 local _,tripType=debug.getupvalue(collectLogic.startTrip2,1)
 local _,armyType=debug.getupvalue(collectLogic.startTrip2,2)
 local soldiers=CSLNew(CSLTypes.CSLList)
 for _,position in ipairs({5,1}) do local item=CSLNew(soldierType);item[1]=soldierId;item[2]=1;item[3]=position;soldiers:Add(item) end
 local army=CSLNew(armyType);army[1]=heroId;army[2]=soldiers
 local req=CSLNew(tripType)
 req[1]=army;req[2]=1;req[3]=available[5];req[4]=target;req[5]=available[6];req[6]=nil;req[7]=0
 assert(req[5]==0,'Unexpected collection secondary target')
 -- Consume these native query objects before sending, so the same plan cannot be submitted twice.
 detail=nil;available=nil
 package.loaded.SLGMainController.__instanceDict.sendTSLGStartArmyTripReq(req)
 return 'collection_sent'
end
return 'collection_api_installed'
