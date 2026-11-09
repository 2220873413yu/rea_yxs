-- Caller-driven ordinary monster hunting. Every network action is issued by the serial Python worker.
local api=assert(REA_AUTO_INFANTRY,'Hero API required')
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local fog=manager:getModel(CSLTypes.SLGWarFogModel)
local wild=manager:getModel(CSLTypes.SLGWildMonsterModel)
local trip=manager:getModel(CSLTypes.SLGArmyTripModel)
local scene=CSLTypes.SceneNotifier.getInstance()
local search=CSLTypes.DBSearcher.sharedInstance()
local buildings=manager:getModel(CSLTypes.SLGBuildingsModel)
local ctrl=package.loaded.SLGMainController.__instanceDict
local _,clock=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
local encode=api.encode_flat_state
local boundMap,boundConfig=main.mTSLGLoginMapRsp,main.mMapConfigID
local target,detail,available
local detailSeq,availableSeq=0,0
local detailAt,availableAt=-1e15,-1e15
local wantDetail,wantAvailable,suppressState,suppressDetail=false,false,false,false
local active,skipSent={},{}
local submitted
local pushSeq=0
local pushedStages={}
local mainRaw,sceneRaw,stateRaw
local mainWrapper,sceneWrapper,stateWrapper
local push={class={name='REAHuntPushObserver'}}
local registered=false
local regionSeq,regionX,regionY=0,-1,-1
local regionRaw=rawget(map,'loadViewData')
local regionOriginal=map.loadViewData
local regionWrapper

-- Refuse all operations after account/map replacement, including purely local candidate reads.
local function world()
 assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==boundMap and main.mMapConfigID==boundConfig,
  'World map changed; reconnect the helper')
 assert(main:getSignedMapTypeID()==1,'Hunting supports the verified Xiyou world only')
end

-- Load class declarations without creating a scene or invoking a button.
local function methods(name)
 local c=package.loaded[name]
 if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 if type(c)~='table' then local ok,v=pcall(require,name);if ok then c=v end end
 assert(type(c)=='table' and type(c.__instanceDict)=='table','Native hunt class unavailable: '..name)
 return c.__instanceDict
end

-- Match native monster rendering/detail buttons: the third argument is -1, not the map position's z value.
-- Discovery, detail metrics and final departure all use this predicate; cached presence never implies visibility.
local function visible(pos)
 return fog:isCellVisible(pos[1],pos[2],-1)==true
end

-- Interpret cached monster flags conservatively; absent local state alone never authorizes spending.
local function idle(pos)
 local key=CSLTypes.SLGMapUtils.createKey(pos[1],pos[2])
 return wild:GetMonsterState(key)==0 and wild:GetMonsterArmyId(key)==nil and wild:GetDieMonsterViewData(key)==nil
end

-- Capture own-army pushes only as wake hints; callbacks never query or send commands.
function push:updateSelf(param)
 if not param or param.id~=2 or type(param.updateData)~='table' then return end
 local ok,own=pcall(main.checkIsMyArmy,param.updateData)
 if ok and own then
  local a=param.updateData
  if type(a[1])~='number' or type(a[4])~='number' then return end
  local signature=tostring(a[4])..':'..tostring(a[5])..':'..tostring(a[6])
  if a[5]==3 then signature=signature..':'..tostring(a[11]) end
  if pushedStages[a[1]]~=signature then
   pushedStages[a[1]]=signature;pushSeq=pushSeq+1
  end
 end
end

-- Restore wrappers in reverse installation order, preserving the earlier collection wrappers.
function api.hunt_close()
 if registered then registered=not pcall(trip.removeObserver,trip,push) end
 if rawget(main,'notifyStateChange')==stateWrapper then rawset(main,'notifyStateChange',stateRaw) end
 if rawget(main,'notifyUpdateData')==mainWrapper then rawset(main,'notifyUpdateData',mainRaw) end
 if rawget(scene,'notifyUpdateData')==sceneWrapper then rawset(scene,'notifyUpdateData',sceneRaw) end
 if rawget(map,'loadViewData')==regionWrapper then rawset(map,'loadViewData',regionRaw) end
 detail=nil;available=nil;wantDetail=false;wantAvailable=false;suppressDetail=false;suppressState=false
 assert(not registered,'Hunt observer cleanup is incomplete')
 return 'hunt_closed'
end

-- Suppress only the exact outstanding helper query's popups; manual/unrelated traffic forwards unchanged.
mainRaw=rawget(main,'notifyUpdateData');sceneRaw=rawget(scene,'notifyUpdateData');stateRaw=rawget(main,'notifyStateChange')
local originalMain,originalScene,originalState=main.notifyUpdateData,scene.notifyUpdateData,main.notifyStateChange
sceneWrapper=function(self,id,payload,...)
 if self==scene and type(payload)=='table' and payload[2]==target then
  if (id==1058 or id==1223) and wantDetail then
   wantDetail=false;detail=payload;detailSeq=detailSeq+1;detailAt=clock():GetCurrentServerTime()*1000
   suppressDetail=true;return
  end
  if id==1060 and wantAvailable and payload[3]==3 then
   wantAvailable=false;available=payload;availableSeq=availableSeq+1;availableAt=clock():GetCurrentServerTime()*1000
   suppressState=true;return
  end
 end
 return originalScene(self,id,payload,...)
end
mainWrapper=function(self,id,payload,...)
 if self==main and id==-9956 and suppressDetail and type(payload)=='table' and payload[2]==target then
  suppressDetail=false;return
 end
 return originalMain(self,id,payload,...)
end
stateWrapper=function(self,id,...)
 if self==main and id==-9991 and suppressState then suppressState=false;return end
 return originalState(self,id,...)
end
rawset(scene,'notifyUpdateData',sceneWrapper);rawset(main,'notifyUpdateData',mainWrapper);rawset(main,'notifyStateChange',stateWrapper)
-- Observe completed native loads without sending requests or suppressing normal rendering.
assert(type(regionOriginal)=='function','Native regional cache loader unavailable')
regionWrapper=function(self,data,...)
 local result=regionOriginal(self,data,...)
 if self==map and data and data[1] then
  regionSeq=regionSeq+1;regionX=data[1][1];regionY=data[1][2]
 end
 return result
end
rawset(map,'loadViewData',regionWrapper)
local ok,err=pcall(function() trip:addObserver(push);registered=true end)
if not ok then api.hunt_close();error(err) end

-- Validate the helper's chosen scope at both discovery and the final departure boundary.
local function checkedRadius(radius)
 assert(type(radius)=='number' and radius>=1 and radius<=200 and radius==math.floor(radius),'Invalid hunt radius')
 return radius
end

-- Read the native view-data center, distinct from the unchanged camera center.
local function regionView()
 for i=1,20 do
  local name,value=debug.getupvalue(regionOriginal,i)
  if not name then break end
  if name=='T_CSSLGMapObjectModel' then return value.mViewDataCenterX,value.mViewDataCenterY end
 end
 error('Native regional view center unavailable')
end

-- Old or same-center caches cannot satisfy a new request without a completed load generation.
function api.hunt_region_state()
 world();local x,y=regionView()
 return encode({seq=regionSeq,last_x=regionX,last_y=regionY,view_x=x,view_y=y,
  camera_x=map.screenCenter and map.screenCenter[1],camera_y=map.screenCenter and map.screenCenter[2]})
end

-- Pass explicit ranges because optional argument marshaling can otherwise send0/0.
function api.hunt_region_query(x,y)
 world();local cfg=map.mInViewDataChunkCacheManager.mtNewPlay_Map
 assert(type(x)=='number' and type(y)=='number' and x==math.floor(x) and y==math.floor(y) and
  x>=0 and y>=0 and x<cfg[10] and y<cfg[11],'Invalid regional query center')
 ctrl.sendTSLGViewInfoReq(nil,x,y,24,18)
 return 'hunt_region_query_sent'
end

-- Overlapping rectangles cover the map; native triangle bounds preserve near-first discovery.
function api.hunt_scan_plan(radius)
 world();radius=checkedRadius(radius)
 local cfg=map.mInViewDataChunkCacheManager.mtNewPlay_Map
 local width,height=cfg[10],cfg[11]
 assert(type(width)=='number' and type(height)=='number' and width>0 and width<=1000 and
  height>0 and height<=1000,'Unknown regional map dimensions')
 local home=map:getMyMainCityCoordinates();local distance=CSLTypes.SLGMapUtils.calMapP2PDistance
 local rows={}
 for left=0,width-1,40 do for bottom=0,height-1,30 do
  local right,top=math.min(left+39,width-1),math.min(bottom+29,height-1)
  local x,y=math.min(left+20,width-1),math.min(bottom+15,height-1)
  local center={[1]=x,[2]=y,[3]=0};local d=distance(home,center);local cover=0
  for _,p in ipairs({{left,bottom,0},{left,top,0},{right,bottom,0},{right,top,0}}) do
   cover=math.max(cover,distance(center,p))
  end
  -- Conservatively allow two cells for parity in offset hex coordinates.
  local lower=math.max(0,d-cover-2)
  if lower<=radius then rows[#rows+1]=encode({x=x,y=y,min_distance=lower,distance=d,
   left=left,right=right,bottom=bottom,top=top}) end
 end end
 return '{"regions":['..table.concat(rows,',')..']}'
end

-- Share exact response attribution with saved-resource loading; validation itself never sends anything.
function api.hunt_region_assert(seq,x,y)
 world();local vx,vy=regionView()
 assert(regionSeq==seq and regionX==x and regionY==y and vx==x and vy==y,'Regional response changed')
 return 'region_confirmed'
end

-- Reject a snapshot if another user or camera query has replaced its exact completed response.
function api.hunt_region_read(radius,seq,x,y)
 api.hunt_region_assert(seq,x,y)
 return api.hunt_candidates(radius)
end

-- Enumerate loaded ordinary monsters in the approved home radius, retaining explicit visibility/state.
function api.hunt_candidates(radius)
 world();radius=checkedRadius(radius)
 local home=map:getMyMainCityCoordinates();local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
 local rows,seen={},{}
 for i=0,chunks:get_Count()-1 do
  local cache=chunks:get_Item(i).mViewDataCache
  if cache:ContainsKey(3000) then
   local points=cache:get_Item(3000);local keys=points:GetDictKeys()
   for j=0,keys:get_Count()-1 do
    local p=points:get_Item(keys:get_Item(j));local id=p[1][2]
    if not seen[id] then
     seen[id]=true
     local pos=p[1][1];local distance=CSLTypes.SLGMapUtils.calMapP2PDistance(home,pos)
     if distance<=radius then
      local c=search:searchTWildMonster_Map(p[2]);local shown=CSLTypes.SLGMapUtils.logicToDisplay(pos)
      if c then rows[#rows+1]=encode({target_id=id,config_id=p[2],level=c[3],x=shown[1],y=shown[2],logic_x=pos[1],logic_y=pos[2],
       distance=distance,visible=visible(pos),idle=idle(pos)}) end
     end
    end
   end
  end
 end
 return '['..table.concat(rows,',')..']'
end

-- Return all own deadlines plus ordinary attack occupancy; only tracked helper armies may be skipped.
local function combatQueue()
 local limit=main:getMaxCombateArmyCount()
 local list=main._myActionState and main._myActionState[2]
 local known=type(limit)=='number' and limit>=0 and limit==math.floor(limit) and
  type(list)=='table' and type(list.get_Count)=='function' and type(main.isAttackAimType)=='function'
 local used=0
 if known then
  for i=0,list:get_Count()-1 do
   local a=list:get_Item(i)
   if type(a)~='table' or type(a[5])~='number' then known=false;break end
   if main.isAttackAimType(a[5]) then used=used+1 end
  end
 end
 return known,used,type(limit)=='number' and limit or -1
end

-- Export fresh native combat capacity, including manual/returning armies under the same aim classification.
function api.hunt_schedule()
 world()
 local s=api.read_hero_state();assert(s.fresh and s.army_known,'Fresh own-army response required')
 local stages,monsters={},{}
 local list=main._myActionState[2]
 for i=0,list:get_Count()-1 do
  local a=list:get_Item(i)
  local row=encode({army_id=a[1],state=a[4],hero_id=a[15][1],target_id=a[6],aim=a[5],
   end_ms=type(a[11])=='number' and a[11] or 0})
  stages[#stages+1]=row
  if a[5]==3 then monsters[#monsters+1]=row end
 end
 local known,used,limit=combatQueue()
 return '{"server_now_ms":'..string.format('%.0f',clock():GetCurrentServerTime()*1000)..
  ',"queue_known":'..tostring(known)..',"queue_used":'..used..',"queue_limit":'..limit..
  ',"queue_free":'..tostring(known and used<limit and main:checkMaxCombateArmyCount()==false)..
  ',"can_skip":'..tostring(main:isSLGMonthCardEnabled()==true)..
  ',"stages":['..table.concat(stages,',')..'],"monsters":['..table.concat(monsters,',')..']}'
end

-- Read local changes only, without server requests; the Python side throttles this cache observation.
function api.hunt_refresh_clock()
 world()
 return encode({server_now_ms=clock():GetCurrentServerTime()*1000,
  refresh_times=map.mInViewDataChunkCacheManager.mtNewPlay_Map[20] or ''})
end

-- Reuse the same local metadata for active discovery; this never requests a game-server update.
function api.hunt_watch(radius)
 world()
 local home=map:getMyMainCityCoordinates()
 local known,used,limit=combatQueue()
 local barrack=buildings:getTSLGGetBarrackRsp();local stock={}
 for _,id in ipairs({411,412,413}) do
  local v=barrack and barrack[1]==0 and barrack[4]:get_Item(id)
  stock[#stock+1]=tostring(v and v[3] and v[3][1] or -1)
 end
 local timing=api.hunt_refresh_clock()
 return string.sub(timing,1,-2)..',"seq":'..pushSeq..',"home_x":'..home[1]..',"home_y":'..home[2]..
  ',"queue_known":'..tostring(known)..',"queue_used":'..used..',"queue_limit":'..limit..
  ',"troops":['..table.concat(stock,',')..'],"candidates":'..api.hunt_candidates(radius)..'}'
end

-- Start one exact detail/candidate read, invalidating older responses and releasing old query suppression.
function api.hunt_query(id)
 world();assert(id>0 and id==math.floor(id),'Invalid monster ID')
 methods('SLGChooseHeroScene');methods('SLGChooseHeroArmyInfo');methods('SLGChooseHeroItem')
 target=id;detail=nil;available=nil;wantDetail=true;wantAvailable=true;suppressDetail=false;suppressState=false
 ctrl.sendTSLGGetMonsterDetailReq(id)
 ctrl.sendTSLGGetAvailHeroListReq(id,3,0,0)
 return 'hunt_query_sent'
end

-- Release outstanding popup suppression after a timeout or cancelled read; do not touch game state.
function api.hunt_cancel_query()
 wantDetail=false;wantAvailable=false;suppressDetail=false;suppressState=false
 return 'hunt_query_cancelled'
end

-- Describe query generations/errors separately from eligibility, including failed native responses.
function api.hunt_status()
 world()
 return encode({target_id=target or 0,detail_seq=detailSeq,available_seq=availableSeq,
  ready=detail~=nil and available~=nil,detail_ret=detail and detail[1] or -999,
  available_ret=available and available[1] or -999})
end

-- Run the game's default formation over protocol-only slots: graphics are discarded, native quantities/positions retained.
local function defaultFormation(h,theoretical)
 local sceneMethods=methods('SLGChooseHeroScene');local soldierMethods=methods('SLGChosenSoldier')
 assert(h[2] and h[2]:get_Count()>0,'Native follower options unavailable')
 local option=h[2]:get_Item(0);local cap=main.getMaxSoldierForFight(option[1])
 assert(cap>0 and cap<=100 and cap==math.floor(cap),'Native total follower capacity is unknown')
 local selected=h
 if theoretical then
  selected={};for k,v in pairs(h) do selected[k]=v end
  selected[2]=CSLNew(CSLTypes.CSLList);selected[2]:Add({[1]=option[1],[2]=cap})
 end
 local name,soldierType=debug.getupvalue(soldierMethods.initialize,1)
 assert(name=='T_TSoldierInfo','Native follower schema changed')
 local function slot(left)
  local s={_soldierInfo=CSLNew(soldierType)}
  -- The game, rather than this adapter, assigns the protocol position for each side.
  soldierMethods.setPosition(s,left)
  s.setSodierId=function(self,id) self._soldierInfo[1]=id end
  s.setNum=function(self,n)
   assert(type(n)=='number' and n>=0 and n==math.floor(n),'Native follower quantity is invalid')
   self._soldierInfo[2]=n
  end
  s.getNum=soldierMethods.getNum;s.getSoldierInfo=soldierMethods.getSoldierInfo
  s.setFreeNum=function(self,n) self._freeNum=n end
  return s
 end
 local enemy=main.getQuestCombatValue(tonumber(detail[5]))
 assert(type(enemy)=='number' and enemy>0,'Enemy combat power is unknown')
 local enabled,power,shownEnemy
 local noop=function() end
 local fake={_currentSelectedHero=selected,_soldierLeft=slot(true),_soldierRight=slot(false),
  commonScene={setStartBtnInteractable=function(self,value) enabled=value end},
  armyInfo={setTitle=noop,setEnemyCombatValueVisible=noop,setCombatValueAreaVisible=noop,SetTipText=noop,addValue=noop,
   setCombatValue=function(self,own,foe) power=own;shownEnemy=foe end},
  _logic={getTitle=function() return '' end,needShowEnemyCombatValue=function() return true end,
   needShowCombatValueArea=function() return true end,getEnemyCombatValue=function() return enemy end,
   getTipDescription=function() return '' end,getAmyInfoData=function() return CSLNew(CSLTypes.CSLList) end}}
 -- This completes the native routine, including its actual start-button eligibility check; no partial pcall is accepted.
 sceneMethods.updateSoldier(fake)
 local n=sceneMethods.getTotalSoldierNum(fake)
 local soldiers=sceneMethods.getSoldierInfoList(fake)
 local stock=theoretical and cap or option[2]
 assert(type(enabled)=='boolean' and type(power)=='number' and shownEnemy==enemy,'Native default formation is incomplete')
 assert(n>=0 and n<=cap and n<=stock,'Native default exceeds available TOTAL capacity')
 local sum=0
 for i=0,soldiers:get_Count()-1 do local s=soldiers:get_Item(i);assert(s[1]==option[1],'Native follower species changed');sum=sum+s[2] end
 assert(sum==n,'Native payload and combat display disagree')
 local _,update=debug.getupvalue(methods('SLGChooseHeroArmyInfo').setCombatValue,1)
 local _,tips=debug.getupvalue(update,1)
 local label=CSLArrayGet(tips(power,enemy),power>=enemy and 0 or 1)
 return {soldiers=soldiers,followers=n,soldier_id=option[1],cap=cap,power=power,enemy=enemy,label=label,
  start_enabled=enabled,left=fake._soldierLeft:getNum(),right=fake._soldierRight:getNum()}
end

-- Export target alternatives and distinguish expired own-state reads from real hero blockers.
function api.hunt_metrics()
 world();assert(detail and available and detail[1]==0 and available[1]==0,'Monster query was unsuccessful')
 assert(detail[2]==target and available[2]==target and available[3]==3,'Monster response target mismatch')
 local now=clock():GetCurrentServerTime()*1000
 local fresh=now>=detailAt and now>=availableAt and now-detailAt<=3000 and now-availableAt<=3000
 local pos=detail[6];local shown=CSLTypes.SLGMapUtils.logicToDisplay(pos)
 local config=assert(search:searchTWildMonster_Map(detail[3]),'Monster configuration missing')
 local quest=search:searchTNewPlayQuest(tonumber(detail[5]))
 local enemy=main.getQuestCombatValue(tonumber(detail[5]));assert(enemy>0,'Unknown enemy power')
 local t={target_id=target,x=shown[1],y=shown[2],config_id=detail[3],level=config[3],enemy_power=enemy,
  visible=visible(pos),idle=detail[4]==0 and idle(pos),fresh=fresh,detail_seq=detailSeq,available_seq=availableSeq,
  distance=CSLTypes.SLGMapUtils.calMapP2PDistance(map:getMyMainCityCoordinates(),pos),
  name=quest and CSLTypes.YXSUtils.GBK2UTF8(quest[3]) or tostring(detail[3])}
 local ownState=api.read_hero_state()
 local ownStateFresh=ownState.fresh and ownState.army_known
 local rows={};local potential=false;local cooldown=0;local needsSoldiers=false
 local strengthKnown=fresh and available[4]:get_Count()>0
 local canWinFull=false
 local candidateIds={}
 for i=0,available[4]:get_Count()-1 do
  local h=available[4]:get_Item(i);local id=h[1][1][3];local s=api.read_hero_state(id)
  candidateIds[id]=true
  if not s.found then strengthKnown=false end
  if h[2]:get_Count()>0 then
   local actual=defaultFormation(h,false)
   local full=actual
   if actual.followers<actual.cap then full=defaultFormation(h,true) end
   local fullStrong=full.start_enabled and full.power>=full.enemy and full.label=='我方超强，胜券在握'
   if fullStrong then canWinFull=true end
   local eligible=fresh and s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and
    s.remaining_ms<=0 and methods('SLGChooseHeroItem').getActionState(h)==0 and actual.start_enabled and actual.followers>0
   if fullStrong and not eligible then
    potential=true
    if s.found and not s.busy and s.hero_state==0 and s.remaining_ms>0 then
     local finish=now+s.remaining_ms;if cooldown==0 or finish<cooldown then cooldown=finish end
    end
   end
   if actual.start_enabled and actual.followers>0 and actual.power>=actual.enemy and actual.label=='我方超强，胜券在握' then
    rows[#rows+1]=encode({hero_id=id,name=s.name,soldier_id=actual.soldier_id,followers=actual.followers,left=actual.left,right=actual.right,
     power=actual.power,enemy_power=actual.enemy,recommendation=actual.label,eligible=eligible,travel_seconds=h[3],
     native_default=true,start_enabled=actual.start_enabled})
   end
   if actual.followers<actual.cap and fullStrong then
    potential=true;needsSoldiers=true
   end
  else strengthKnown=false end
 end
 -- A missing owned hero might merely be unavailable now; do not conclude permanent weakness from a partial list.
 local roster=buildings:getTSLGGetHeroPubRsp()
 local owned=roster and roster[1]==0 and roster[2] and roster[2][2] and roster[2][2][1]
 local missing=0
 if type(owned)=='table' and owned.get_Count then
  for i=0,owned:get_Count()-1 do if not candidateIds[owned:get_Item(i)[1][3]] then missing=missing+1 end end
 else strengthKnown=false end
 if missing>0 then strengthKnown=false end
 return '{"target":'..encode(t)..',"own_state_fresh":'..tostring(ownStateFresh)..
  ',"strength_known":'..tostring(strengthKnown)..',"can_win_full":'..tostring(canWinFull)..
  ',"candidate_heroes":'..available[4]:get_Count()..',"missing_heroes":'..missing..
  ',"potential":'..tostring(potential)..',"needs_soldiers":'..tostring(needsSoldiers)..',"cooldown_ms":'..string.format('%.0f',cooldown)..
  ',"formations":['..table.concat(rows,',')..']}'
end

-- Submit native defaults only inside the validated scope, with capacity, strength and reservation guards.
function api.hunt_dispatch(id,heroId,soldierId,n,expectedDetail,expectedAvailable,radius,x,y)
 world();radius=checkedRadius(radius);assert(not submitted,'A hunting departure is already uncertain')
 for _,a in pairs(active) do assert(a.hero_id~=heroId and a.target_id~=id,'Hunt hero or target is already reserved') end
 api.hunt_metrics()
 local now=clock():GetCurrentServerTime()*1000
 assert(id==target and expectedDetail==detailSeq and expectedAvailable==availableSeq,'Hunt query generation changed')
 assert(now-detailAt<=3000 and now-availableAt<=3000,'Hunt target data expired')
 assert(detail[4]==0 and visible(detail[6]) and idle(detail[6]),'Monster is hidden or occupied')
 local shown=CSLTypes.SLGMapUtils.logicToDisplay(detail[6])
 assert(shown[1]==x and shown[2]==y,'Monster moved')
 assert(CSLTypes.SLGMapUtils.calMapP2PDistance(map:getMyMainCityCoordinates(),detail[6])<=radius,'Target exceeds hunt scope')
 assert(main:isSLGMonthCardEnabled()==true,'Native skip permission unavailable')
 local known,used,limit=combatQueue()
 assert(known and used<limit and main:checkMaxCombateArmyCount()==false,'Attack queues are full or unknown')
 local s=api.read_hero_state(heroId)
 assert(s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and s.remaining_ms<=0,'Hero unavailable')
 local armies=main._myActionState[2]
 for i=0,armies:get_Count()-1 do
  local a=armies:get_Item(i)
  assert(a[5]~=3 or a[6]~=id,'An own army is already attacking this monster')
 end
 local chosen
 for i=0,available[4]:get_Count()-1 do local h=available[4]:get_Item(i);if h[1][1][3]==heroId then chosen=h end end
 assert(chosen and methods('SLGChooseHeroItem').getActionState(chosen)==0,'Hero action changed')
 local formation=defaultFormation(chosen,false)
 assert(formation.start_enabled and formation.followers>0,'Native default formation cannot start')
 assert(n==formation.followers and soldierId==formation.soldier_id,'Native default formation changed')
 local barrack=buildings:getTSLGGetBarrackRsp()
 assert(barrack and barrack[1]==0 and barrack[4]:get_Item(soldierId)[3][1]>=n,'Follower stock unavailable')
 assert(formation.enemy>0 and formation.power>=formation.enemy and formation.label=='我方超强，胜券在握','Formation is not overwhelming')
 assert(available[5][1]==detail[6][1] and available[5][2]==detail[6][2] and available[6]==0,'Unexpected monster destination')
 local fn=methods('SLGChooseHeroLogicMonster').startTrip2
 local tn,tripType=debug.getupvalue(fn,1);local an,armyType=debug.getupvalue(fn,2)
 assert(tn=='T_TSLGStartArmyTripReq' and an=='T_TMakeArmyReq','Native trip schema changed')
 local army=CSLNew(armyType);army[1]=heroId;army[2]=formation.soldiers
 local req=CSLNew(tripType);req[1]=army;req[2]=3;req[3]=available[5];req[4]=id;req[5]=0;req[6]=nil;req[7]=0
 submitted={hero_id=heroId,target_id=id}
 detail=nil;available=nil
 ctrl.sendTSLGStartArmyTripReq(req)
 return 'hunt_departure_submitted'
end

-- Bind an attributed successful server army ID; an uncertain submission remains blocked until reconnect.
function api.hunt_ack(id,heroId,armyId)
 world();assert(submitted and submitted.target_id==id and submitted.hero_id==heroId,'No matching hunt submission')
 local a=main:getMyArmyInfoByHeroGroupId(heroId)
 assert(a and a[1]==armyId and a[5]==3 and a[6]==id,'Accepted hunt army is unconfirmed')
 assert(not active[armyId],'Hunt army is already tracked')
 active[armyId]={hero_id=heroId,target_id=id,army_id=armyId};submitted=nil;skipSent[armyId]=nil
 return 'hunt_departure_confirmed'
end

-- End only a verified returned helper army; do not release an uncertain submission for another attempt.
function api.hunt_release(armyId)
 world();local a=active[armyId];assert(a,'Untracked hunt army')
 assert(api.read_hero_state(a.hero_id).army_known,'Army state is unknown')
 assert(main:getMyArmyInfoByHeroGroupId(a.hero_id)==nil,'Hunt hero has not returned')
 active[armyId]=nil;skipSent[armyId]=nil;return 'hunt_return_confirmed'
end

-- Use the actual native skip button's handler once, only for our own arrived, confirmed army.
function api.hunt_skip(id,heroId,armyId)
 world();local tracked=active[armyId]
 assert(tracked and tracked.target_id==id and tracked.hero_id==heroId,'Untracked hunt skip')
 assert(not skipSent[armyId],'Quick combat was already submitted; do not retry')
 local s=api.read_hero_state(heroId);assert(s.fresh and s.army_known and s.busy,'Fresh busy hero required')
 local a=main:getMyArmyInfoByHeroGroupId(heroId)
 assert(a and a[1]==armyId and a[5]==3 and a[6]==id and a[4]==3,'Hunt army is not waiting at its target')
 assert(main:isSLGMonthCardEnabled()==true,'Native skip permission unavailable')
 local _,click=debug.getupvalue(methods('SLGSitdownPromptDialog').Start,3)
 assert(type(click)=='function','Native skip callback missing')
 skipSent[armyId]=true;click({mTArmyInfo=a})
 return 'hunt_skip_submitted'
end
return 'hunt_api_installed'
