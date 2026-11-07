-- Caller-driven beacon events. No autonomous timers or purchases are installed.
local api=assert(REA_AUTO_INFANTRY,'Hero API required')
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local scene=CSLTypes.SceneNotifier.getInstance()
local search=CSLTypes.DBSearcher.sharedInstance()
local encode=api.encode_flat_state
local _,clock=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
local bound,config=main.mTSLGLoginMapRsp,main.mMapConfigID
local infoBefore,infoRef,infoAt,refreshEnd
local queryPending=false
local available,availableAt,target,want,suppress
local attempts={dispatch={},recall={},claim={}}
local selected={[1]=true}
local native={}
api.beacon_native=native
local registered=false
local rawScene,rawState=rawget(scene,'notifyUpdateData'),rawget(main,'notifyStateChange')
local rawMain=rawget(main,'notifyUpdateData');local originalMain=main.notifyUpdateData
local originalScene,originalState=scene.notifyUpdateData,main.notifyStateChange
local observer={class={name='REABeaconRescueObserver'}}

-- Load declarations without creating UI objects or evaluating scene action callbacks.
local function methods(name)
 local c=package.loaded[name]
 if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 if type(c)~='table' then local ok,v=pcall(require,name);if ok then c=v end end
 assert(type(c)=='table' and c.__instanceDict,'Native beacon class unavailable: '..name)
 return c.__instanceDict
end

local aim
do
 local _,panel=debug.getupvalue(methods('SLGFengHuoTaiSaveDialog').onSaveClick,1)
 for i=1,10 do local name,value=debug.getupvalue(panel,i);if not name then break end
  if type(value)=='table' and type(value.E_SLG_ARMY_AIM_TYPE_BEACON_TOWER_EVENT)=='number' then
   aim=value.E_SLG_ARMY_AIM_TYPE_BEACON_TOWER_EVENT;break
  end
 end
 assert(aim==45,'Native beacon aim changed; helper stopped')
end

-- Reject old-account data for both reads and actions.
local function checkWorld()
 assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==bound and main.mMapConfigID==config,
  'World map changed; reconnect the helper')
end

-- Express every scheduling timestamp in server epoch milliseconds.
local function nowMs()
 return clock():GetCurrentServerTime()*1000
end

-- Anchor a new relative refresh duration once, at its observed response arrival.
local function acceptInfo(r)
 if r~=infoRef then
  assert(type(r)=='table' and r[1]==0 and type(r[5])=='number' and r[5]>=0,'Invalid beacon response')
  infoRef=r;infoAt=nowMs();refreshEnd=r[5]>0 and infoAt+r[5]*1000 or 0
 end
end

-- Record only successful beacon information responses; never issue any callback-driven request.
function observer:updateSelf(param)
 if native.observe then native.observe(param) end
 if param and param.id==11042 and type(param.updateData)=='table' and param.updateData[1]==0 then
  acceptInfo(param.updateData)
 end
end

local sw=function(self,id,payload,...)
 if native.consumeScene and native.consumeScene(id,payload) then return end
 if want and id==1060 and type(payload)=='table' and payload[2]==target and payload[3]==aim then
  available=payload;availableAt=nowMs();want=false;suppress=true;return
 end
 return originalScene(self,id,payload,...)
end
local tw=function(self,id,...)
 if suppress and id==-9991 then suppress=false;return end
 return originalState(self,id,...)
end
local mw=function(self,id,payload,...)
 if native.consume and native.consume(id,payload) then return end
 return originalMain(self,id,payload,...)
end

-- Remove only this module's observer/wrapper layer on reconnect or shutdown.
function api.beacon_close()
 if native.close then native.close() end
 want=false;available=nil;queryPending=false
 if registered then main:removeObserver(observer);registered=false end
 if rawget(scene,'notifyUpdateData')==sw then rawset(scene,'notifyUpdateData',rawScene) end
 if rawget(main,'notifyStateChange')==tw then rawset(main,'notifyStateChange',rawState) end
 if rawget(main,'notifyUpdateData')==mw then rawset(main,'notifyUpdateData',rawMain) end
 return 'beacon_closed'
end
main:addObserver(observer);registered=true
rawset(scene,'notifyUpdateData',sw);rawset(main,'notifyStateChange',tw)
rawset(main,'notifyUpdateData',mw)

-- Look up a current event, preserving native type distinctions for every action guard.
local function event(id)
 local e=main:getTSLGBeaconTowerEventByCommObjID(id)
 if e then assert(e[1][2]==id,'Beacon event identifier mismatch') end
 return e
end

-- Require an explicitly selected event type even when several types share the trip protocol.
local function authorized(id)
 local e=assert(event(id),'Beacon event no longer exists')
 local c=search:searchTMapIntelStation_Event_Map(e[2])
 assert(c and selected[c[2]],'Beacon event type is not selected')
 return e
end

-- Apply a bounded selection mask before opening the action gate; no request is sent here.
function api.beacon_configure(mask)
 checkWorld();assert(type(mask)=='number' and mask>=0 and mask<=15 and mask==math.floor(mask),'Invalid beacon types')
 selected={};for k=1,4 do selected[k]=math.floor(mask/2^(k-1))%2==1 end
 return 'beacon_types_configured'
end
native.main=main;native.map=map;native.search=search;native.manager=manager;native.methods=methods
native.now=nowMs;native.event=authorized;native.world=checkWorld
native.available=function() return available,availableAt,target end

-- Capture cached event/army signatures locally; query generations and countdown ticks do not wake the worker.
function api.beacon_watch()
 checkWorld()
 local parts={}
 local r=main:getTSLGGetBeaconTowerInfoRsp()
 if r and r[1]==0 then
  parts[#parts+1]=tostring(r[2])..':'..tostring(r[3])..':'..tostring(r[6])
  for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i)
   parts[#parts+1]='e'..e[1][2]..':'..e[3]..':'..e[4]..':'..e[6]
  end
 end
 local a=main._myActionState
 if a and a[1]==0 then for i=0,a[2]:get_Count()-1 do local v=a[2]:get_Item(i)
  if v[5]==aim then parts[#parts+1]='a'..v[1]..':'..v[4]..':'..v[6]..':'..v[11] end
 end end
 table.sort(parts)
 if native.watch then parts[#parts+1]=native.watch() end
 return encode({signature=table.concat(parts,'|')})
end

-- Request a new authoritative task list once, with no automatic request resubmission.
function api.beacon_info_query()
 checkWorld();infoBefore=main:getTSLGGetBeaconTowerInfoRsp();queryPending=true
 CSLTypes.SLGMainController.getInstance():sendTSLGGetBeaconTowerInfoReq()
 return 'beacon_info_query_sent'
end

-- Count distinct own armies through return, then add active events not yet represented by an army response.
local function queueOccupancy(r)
 local ids,targets,used,returning={},{},0,0
 local state=main._myActionState
 assert(state and state[1]==0 and state[2],'Own beacon armies unavailable')
 for i=0,state[2]:get_Count()-1 do local a=state[2]:get_Item(i)
  if a[5]==aim and a[4]~=7 and not ids[a[1]] then
   assert(type(a[1])=='number' and a[1]>0,'Beacon army identifier unknown')
   ids[a[1]]=true;targets[a[6]]=true;used=used+1
   if a[4]==9 then returning=returning+1 end
  end
 end
 for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i)
  if e[1][3]~=1011 and e[3]~=0 and e[3]~=3 and not ids[e[4]] and not targets[e[1][2]] then
   used=used+1;targets[e[1][2]]=true
  end
 end
 return used,returning
end

-- Export all event types, deduplicated occupancy including return journeys and server deadlines.
function api.beacon_snapshot()
 checkWorld();local r=main:getTSLGGetBeaconTowerInfoRsp()
 if not r or (queryPending and r==infoBefore) or (not queryPending and not infoRef) then return '{"ready":false}' end
 assert(r[1]==0,'Beacon information refused: '..tostring(r[1]))
 acceptInfo(r);queryPending=false
 assert(type(r[6])=='number' and r[6]>0 and r[6]==math.floor(r[6]),'Beacon queue capacity unknown')
 local events,armies={},{}
 local home=map:getMyMainCityCoordinates()
 local fog=manager:getModel(CSLTypes.SLGWarFogModel)
 for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i)
  local c=assert(search:searchTMapIntelStation_Event_Map(e[2]),'Beacon event config missing')
  local p=e[1][1];local shown=CSLTypes.SLGMapUtils.logicToDisplay(p)
  events[#events+1]=encode({event_id=e[1][2],config_id=e[2],kind=c[2],state=e[3],army_id=e[4],
   start_ms=e[5]*1000,end_ms=e[6]*1000,x=shown[1],y=shown[2],
   distance=CSLTypes.SLGMapUtils.calMapP2PDistance(home,p),visible=fog:isCellVisible(p[1],p[2],p[3])})
 end
 local world=api.read_hero_state()
 assert(world.army_known,'Own army state unavailable for beacon')
 local used,returning=queueOccupancy(r)
 local list=main._myActionState[2]
 for i=0,list:get_Count()-1 do local a=list:get_Item(i)
  if a[5]==aim then
   local id=a[15][1];local h=api.read_hero_state(id)
   armies[#armies+1]=encode({army_id=a[1],hero_id=id,name=h.name,state=a[4],target_id=a[6],end_ms=a[11]})
  end
 end
 local scouts={};if native.scoutStages then for _,s in ipairs(native.scoutStages()) do scouts[#scouts+1]=encode(s) end end
 return '{"ready":true,"server_now_ms":'..string.format('%.0f',nowMs())..
  ',"refresh_end_ms":'..string.format('%.0f',refreshEnd)..',"queue_limit":'..r[6]..',"queue_used":'..used..
  ',"returning_count":'..returning..',"queue_full":'..tostring(used>=r[6] or main:checkMaxFengHuoTaiArmyCount())..
  ',"events":['..table.concat(events,',')..'],"scouts":['..table.concat(scouts,',')..'],"armies":['..table.concat(armies,',')..']}'
end

-- Query a still-unstarted selected hero event; treasure uses its separate scout path.
function api.beacon_candidates_query(id)
 checkWorld();local e=authorized(id);local p=e[1][1]
 assert(search:searchTMapIntelStation_Event_Map(e[2])[2]~=2,'Treasure does not select a hero')
 assert(e[3]==0,'Rescue event already started')
 if type(attempts.dispatch[id])=='number' then
  local list=main._myActionState[2];local found=false
  for i=0,list:get_Count()-1 do local a=list:get_Item(i)
   if a[1]==attempts.dispatch[id] or (a[5]==aim and a[6]==id) then found=true end
  end
  if not found then attempts.dispatch[id]=nil end
 end
 assert(manager:getModel(CSLTypes.SLGWarFogModel):isCellVisible(p[1],p[2],p[3]),'Rescue has no vision')
 target=id;available=nil;want=true
 local secondary=native.beforeCandidates and native.beforeCandidates(e) or 0
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq(id,aim,secondary or 0,0)
 return 'beacon_candidates_query_sent'
end

-- Prepare type-specific target details before selecting heroes, without touching UI state.
function api.beacon_target_query(id)
 checkWorld();local e=authorized(id)
 if native.targetQuery then native.targetQuery(e) end
 return 'beacon_target_query_sent'
end
-- Wait locally on the one outstanding detail query; no sender is invoked while reading.
function api.beacon_target_result()
 if native.targetResult then return native.targetResult() end
 return '{"ready":true}'
end

-- Disable capture without touching any accepted army or the other modules' observers.
function api.beacon_cancel_query()
 if native.cancel then native.cancel() end
 want=false;suppress=false;available=nil;return 'beacon_candidate_query_cancelled'
end

-- Read target-bound candidates; busy and cooling heroes are shown but never eligible for a departure.
function api.beacon_candidates_result()
 checkWorld();if not available then return '{"ready":false}' end
 assert(available[1]==0,'Rescue hero query refused: '..tostring(available[1]))
 local e=authorized(target);assert(available[2]==target and available[3]==aim,'Beacon hero response mismatched')
 if native.candidatesReady and not native.candidatesReady(e) then return '{"ready":false}' end
 assert(available[5][1]==e[1][1][1] and available[5][2]==e[1][1][2],'Rescue position mismatch')
 local rows={}
 for i=0,available[4]:get_Count()-1 do local h=available[4]:get_Item(i);local id=h[1][1][3]
  local state=api.read_hero_state(id)
  local enough=false
  if h[2]:get_Count()>0 then local s=h[2]:get_Item(0)
   enough=s[2]>=2 and main.getMaxSoldierForFight(s[1])>=2
  end
  local extra=native.metrics and native.metrics(h,e) or {power=h[4],eligible=true}
  rows[#rows+1]=encode({hero_id=id,name=state.name,power=extra.power,speed=h[6] or 0,load=h[5] or 0,
   overwhelming=extra.overwhelming,strength_known=extra.strength_known~=false,travel_seconds=h[3],remaining_ms=state.remaining_ms,
   ready=state.found and state.fresh and state.army_known and not state.busy and state.hero_state==0 and
    state.remaining_ms<=0 and methods('SLGChooseHeroItem').getActionState(h)==0 and enough and extra.eligible})
 end
 return '{"ready":true,"target_id":'..target..',"heroes":['..table.concat(rows,',')..']}'
end

-- Generate the native default formation using protocol-only slot adapters, never a Unity UI object.
local function formation(h,e)
 local kind=search:searchTMapIntelStation_Event_Map(e[2])[2]
 local class=({[1]='SLGChooseHeroLogicFengHuoTaiSave',[3]='SLGChooseHeroLogicCollectResource',[4]='SLGChooseHeroLogicMonster'})[kind]
 local sm,sol,lm=methods('SLGChooseHeroScene'),methods('SLGChosenSoldier'),methods(assert(class,'Invalid hero event'))
 local name,ctor=debug.getupvalue(sol.initialize,1);assert(name=='T_TSoldierInfo','Rescue soldier schema changed')
 local function slot(left)
  local s={_soldierInfo=CSLNew(ctor)};sol.setPosition(s,left)
  s.setSodierId=function(self,id) self._soldierInfo[1]=id end
  s.setNum=function(self,n) self._soldierInfo[2]=n end
  s.getNum=sol.getNum;s.getSoldierInfo=sol.getSoldierInfo;s.setFreeNum=function(self,n) self._freeNum=n end
  return s
 end
 local enabled,power,enemy;local noop=function() end
 local fake={_currentSelectedHero=h,_soldierLeft=slot(true),_soldierRight=slot(false),
  commonScene={setStartBtnInteractable=function(self,v) enabled=v end},
  armyInfo={setTitle=noop,setEnemyCombatValueVisible=noop,setCombatValueAreaVisible=noop,
   setCombatValue=function(self,a,b) power=a;enemy=b end,SetTipText=noop,addValue=noop}}
 fake.getContent=function() return available end;fake.getSelectedHero=function() return h end
 setmetatable(fake,{__index=sm})
 fake.getSoldierInfoList=sm.getSoldierInfoList;fake.getFirstHandValue=sm.getFirstHandValue
 local logic=setmetatable({_scene=fake},{__index=lm});fake._logic=logic
 sm.updateSoldier(fake)
 local n=sm.getTotalSoldierNum(fake);local f=h[2]:get_Item(0)
 assert(enabled and n>=2 and n<=f[2] and n<=main.getMaxSoldierForFight(f[1]),'Native rescue formation unavailable')
 if kind==4 then power=sm.getMyCombatValue(fake);enemy=lm.getEnemyCombatValue(logic) end
 return logic,n,f[1],power,enemy
end
native.formation=formation

-- Send one fresh, idle hero using native defaults, reserving the target before invoking the sender.
function api.beacon_dispatch(id,heroId)
 checkWorld();assert(not attempts.dispatch[id],'Rescue departure already attempted; reconcile before retry')
 local e=authorized(id)
 local info=assert(main:getTSLGGetBeaconTowerInfoRsp());local used=queueOccupancy(info)
 assert(e[3]==0,'Beacon event already started')
 if used>=info[6] or main:checkMaxFengHuoTaiArmyCount() then
  return encode({not_sent=true,reason='capacity_full',event_id=id})
 end
 assert(infoAt and nowMs()-infoAt<=10000,'Beacon snapshot expired')
 assert(available and target==id and available[1]==0 and available[2]==id and available[3]==aim and
  nowMs()>=availableAt and nowMs()-availableAt<=3000,'Rescue candidates stale or mismatched')
 assert(available[5][1]==e[1][1][1] and available[5][2]==e[1][1][2] and available[11]==0,'Rescue target or force-trip decision changed')
 local p=e[1][1];assert(manager:getModel(CSLTypes.SLGWarFogModel):isCellVisible(p[1],p[2],p[3]),'Rescue vision lost')
 local state=api.read_hero_state(heroId)
 assert(state.found and state.fresh and state.army_known and not state.busy and state.hero_state==0 and state.remaining_ms<=0,
  'Rescue hero is not ready')
 local h
 for i=0,available[4]:get_Count()-1 do local v=available[4]:get_Item(i);if v[1][1][3]==heroId then h=v end end
 assert(h and methods('SLGChooseHeroItem').getActionState(h)==0,'Rescue hero eligibility changed')
 if native.guardDispatch then native.guardDispatch(e,h) end
 local logic,n,soldier=formation(h,e)
 attempts.dispatch[id]=true
 if native.startTrip then native.startTrip(logic,e) else methods('SLGChooseHeroLogicFengHuoTaiSave').startTrip(logic,nil) end
 return encode({target_id=id,hero_id=heroId,aim=aim,followers=n,soldier_id=soldier})
end

-- Release only an unacknowledged departure after Python matched a definitive6395 rejection, never on timeout.
function api.beacon_rejected(id,code)
 checkWorld();assert(code==6395 and attempts.dispatch[id]==true,'No definitively rejected departure to release')
 local list=main._myActionState[2]
 for i=0,list:get_Count()-1 do local a=list:get_Item(i)
  assert(a[5]~=aim or a[6]~=id or a[4]==7,'Rejected target already has an owned army')
 end
 attempts.dispatch[id]=nil;return 'beacon_rejected_reservation_released'
end

-- Resolve only an owned army associated with the exact event and hero.
local function ownArmy(id,heroId,armyId)
 local s=api.read_hero_state(heroId);assert(s.fresh and s.army_known,'Fresh beacon own armies required')
 local list=main._myActionState[2]
 for i=0,list:get_Count()-1 do local a=list:get_Item(i)
  if a[1]==armyId then
   assert(a[15][1]==heroId and a[5]==aim and a[6]==id,'Rescue army identity mismatch');return a
  end
 end
 error('Rescue own army not confirmed')
end
native.ownArmy=ownArmy

-- Require exact accepted army confirmation before the worker may dispatch the next rescue.
function api.beacon_ack(id,heroId,armyId)
 local a=ownArmy(id,heroId,armyId)
 assert(a[4]~=7 and a[4]~=9,'Rescue departure phase not confirmed')
 attempts.dispatch[id]=armyId
 return 'beacon_departure_confirmed'
end

-- Recall only after event state2 and an arrived owned army agree; marching/returning armies cannot be recalled here.
function api.beacon_recall(id,heroId,armyId)
 checkWorld();assert(not attempts.recall[armyId],'Rescue recall already attempted; do not repeat')
 local e=authorized(id);assert(search:searchTMapIntelStation_Event_Map(e[2])[2]==1,'Only rescue may recall early')
 assert(e[3]==2 and e[4]==armyId,'Rescue arrival not confirmed')
 local a=ownArmy(id,heroId,armyId)
 assert(a[4]~=2 and a[4]~=7 and a[4]~=9,'Rescue army has not arrived or is already returning')
 attempts.recall[armyId]=true
 package.loaded.SLGMainController.__instanceDict.sendTSLGRetreatArmyReq(armyId)
 return 'beacon_recall_sent'
end

-- Claim only a completed event whose type remains selected, never infer completion from a timer.
function api.beacon_claim(id)
 checkWorld();assert(not attempts.claim[id],'Rescue claim already attempted; do not repeat')
 local e=authorized(id);assert(e[3]==3,'Beacon reward is not ready')
 assert(infoAt and nowMs()-infoAt<=10000,'Fresh beacon claim state required')
 attempts.claim[id]=true
 CSLTypes.SLGMainController.getInstance():sendTSLGGetBeaconTowerEventRewardReq(id)
 return 'beacon_claim_sent'
end
 return 'beacon_event_api_installed'
