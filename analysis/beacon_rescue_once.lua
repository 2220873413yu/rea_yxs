-- One authorized rescue experiment. No recurring automation, reward claim, scouting or item use exists here.
local api=assert(REA_BEACON_RESCUE_TEST)
local manager=CSLTypes.ModelManager.sharedInstance();local main=manager:getModel(CSLTypes.SLGMainModel)
local map=manager:getModel(CSLTypes.SLGMapObjectModel);local search=CSLTypes.DBSearcher.sharedInstance()
local scene=CSLTypes.SceneNotifier.getInstance();local bound=main.mTSLGLoginMapRsp
local clock=CSLTypes.RefreshTimer.getServerNatureTimeNow
local target,available,availableAt,beforeInfo,chosenEvent
local pending,suppress=false,false
local sentKey='REA_BEACON_RESCUE_SENT_'..(api.run_key or '20261107')
local recalledKey='REA_BEACON_RESCUE_RECALLED_'..(api.run_key or '20261107')
local rawScene,rawState=rawget(scene,'notifyUpdateData'),rawget(main,'notifyStateChange')
local originalScene,originalState=scene.notifyUpdateData,main.notifyStateChange

-- Resolve declarations only; never instantiate real scenes or their UI controls.
local function methods(name)
 local c=package.loaded[name]
 if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 if type(c)~='table' then local ok,v=pcall(require,name);if ok then c=v end end
 assert(type(c)=='table' and c.__instanceDict,'Native declaration unavailable: '..name)
 return c.__instanceDict
end

-- Read the actual beacon aim from the native rescue entry, never from an assumed numeric constant.
local aimType
do
 local _,panel=debug.getupvalue(methods('SLGFengHuoTaiSaveDialog').onSaveClick,1)
 for i=1,10 do local name,value=debug.getupvalue(panel,i);if not name then break end
  if type(value)=='table' and type(value.E_SLG_ARMY_AIM_TYPE_BEACON_TOWER_EVENT)=='number' then
   aimType=value.E_SLG_ARMY_AIM_TYPE_BEACON_TOWER_EVENT;break
  end
 end
 assert(aimType==45,'Native beacon aim layout changed')
end

-- Stop all requests/actions on an account or world change.
local function checkWorld()
 assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==bound,'World changed; one-shot test stopped')
end

local sw=function(self,id,payload,...)
 if pending and id==1060 and type(payload)=='table' and payload[2]==target and payload[3]==aimType then
  assert(payload[1]==0,'Rescue candidates rejected');available=payload;availableAt=clock();pending=false;suppress=true;return
 end
 return originalScene(self,id,payload,...)
end
local tw=function(self,id,...)
 if suppress and id==-9991 then suppress=false;return end
 return originalState(self,id,...)
end
rawset(scene,'notifyUpdateData',sw);rawset(main,'notifyStateChange',tw)

-- Retrieve one fresh beacon response, without refreshing events or claiming rewards.
function api.info_query()
 checkWorld();beforeInfo=main:getTSLGGetBeaconTowerInfoRsp()
 CSLTypes.SLGMainController.getInstance():sendTSLGGetBeaconTowerInfoReq();return 'info_query_sent'
end

-- Select the nearest visible unstarted rescue once, retaining its exact event identity.
function api.info_result()
 checkWorld();local r=main:getTSLGGetBeaconTowerInfoRsp()
 if not r or r==beforeInfo then return '{"ready":false}' end
 assert(r[1]==0,'Beacon query failed');assert(r[6]>0,'Beacon capacity unknown')
 if not target then
  local best,distance;local home=map:getMyMainCityCoordinates()
  local fog=manager:getModel(CSLTypes.SLGWarFogModel)
  for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i)
   local c=search:searchTMapIntelStation_Event_Map(e[2]);local pos=e[1][1]
   if c[2]==1 and e[3]==0 and (not api.required_target or e[1][2]==api.required_target) and
    fog:isCellVisible(pos[1],pos[2],pos[3]) then
    local d=CSLTypes.SLGMapUtils.calMapP2PDistance(home,pos)
    if not best or d<distance then best=e;distance=d end
   end
  end
  assert(best,'No visible unstarted rescue; no departure attempted')
  chosenEvent=best;target=best[1][2]
 end
 local e=assert(main:getTSLGBeaconTowerEventByCommObjID(target),'Chosen rescue disappeared')
 local p=CSLTypes.SLGMapUtils.logicToDisplay(e[1][1])
 return api.encode_flat_state({ready=true,target_id=target,config_id=e[2],x=p[1],y=p[2],event_state=e[3],
  max_queue=r[6],queue_full=main:checkMaxFengHuoTaiArmyCount()})
end

-- Request target-specific hero eligibility without opening the selection scene.
function api.candidates_query()
 checkWorld();assert(target);pending=true;available=nil
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq(target,aimType,0,0)
 return 'candidate_query_sent'
end

-- Expose only target-response coordinates and scalar fields to diagnose a pre-send mismatch safely.
function api.candidates_debug()
 if not available then return '{"ready":false}' end
 local e=main:getTSLGBeaconTowerEventByCommObjID(target)
 local r={ready=true,target=target,event_x=e[1][1][1],event_y=e[1][1][2],
  response_x=available[5][1],response_y=available[5][2],response_z=available[5][3]}
 for i=1,18 do if type(available[i])=='number' then r['field_'..i]=available[i] end end
 return api.encode_flat_state(r)
end

-- Produce only protocol objects via native default formation routines; no Unity objects are created.
local function formation(h)
 local sm,sol,logicMethods=methods('SLGChooseHeroScene'),methods('SLGChosenSoldier'),methods('SLGChooseHeroLogicFengHuoTaiSave')
 local name,ctor=debug.getupvalue(sol.initialize,1);assert(name=='T_TSoldierInfo','Soldier schema changed')
 local function slot(left)
  local s={_soldierInfo=CSLNew(ctor)};sol.setPosition(s,left)
  s.setSodierId=function(self,id) self._soldierInfo[1]=id end
  s.setNum=function(self,n) self._soldierInfo[2]=n end
  s.getNum=sol.getNum;s.getSoldierInfo=sol.getSoldierInfo;s.setFreeNum=function(self,n) self._freeNum=n end
  return s
 end
 local enabled;local noop=function() end
 local fake={_currentSelectedHero=h,_soldierLeft=slot(true),_soldierRight=slot(false),
  commonScene={setStartBtnInteractable=function(self,v) enabled=v end},
  armyInfo={setTitle=noop,setEnemyCombatValueVisible=noop,setCombatValueAreaVisible=noop,
   setCombatValue=noop,SetTipText=noop,addValue=noop}}
 fake.getContent=function() return available end;fake.getSelectedHero=function() return h end
 fake.getSoldierInfoList=sm.getSoldierInfoList;fake.getFirstHandValue=sm.getFirstHandValue
 local logic=setmetatable({_scene=fake},{__index=logicMethods});fake._logic=logic
 sm.updateSoldier(fake)
 local n=sm.getTotalSoldierNum(fake);local f=h[2]:get_Item(0)
 assert(enabled and n>=2 and n<=f[2] and n<=main.getMaxSoldierForFight(f[1]),'Native rescue formation unavailable')
 return logic,n,f[1]
end

-- Require current eligibility, exact event/coordinates and a normal native formation before any send.
function api.plan()
 checkWorld();assert(not _G[sentKey],'Rescue was already submitted; never repeat')
 local e=assert(main:getTSLGBeaconTowerEventByCommObjID(target),'Rescue no longer exists')
 assert(e[2]==chosenEvent[2] and e[3]==0 and search:searchTMapIntelStation_Event_Map(e[2])[2]==1,'Rescue changed or started')
 assert(not main:checkMaxFengHuoTaiArmyCount(),'Beacon queues are full')
 assert(available and available[1]==0 and available[2]==target and available[3]==aimType,'Rescue candidates are missing')
 assert(clock()>=availableAt and clock()-availableAt<=3,'Candidate snapshot expired')
 assert(available[5][1]==e[1][1][1] and available[5][2]==e[1][1][2],'Rescue target coordinates changed')
 assert(available[11]==0,'Native rescue requires a force-trip decision; no action taken')
 local best,state
 for i=0,available[4]:get_Count()-1 do local h=available[4]:get_Item(i);local id=h[1][1][3]
  local s=api.read_hero_state(id)
  if s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and s.remaining_ms<=0 and
   methods('SLGChooseHeroItem').getActionState(h)==0 and h[2]:get_Count()>0 then
   local f=h[2]:get_Item(0)
   if f[2]>=2 and main.getMaxSoldierForFight(f[1])>=2 and
    (not best or h[4]<best[4] or (h[4]==best[4] and h[3]<best[3])) then best=h;state=s end
  end
 end
 assert(best,'No ready hero and compatible followers; no recovery items will be used')
 local logic,n,soldier=formation(best);local p=CSLTypes.SLGMapUtils.logicToDisplay(e[1][1])
 local r={target_id=target,aim=aimType,config_id=e[2],x=p[1],y=p[2],hero_id=best[1][1][3],name=state.name,
  hero_power=best[4],followers=n,soldier_id=soldier,travel_seconds=best[3],secondary_target=logic:getTargetID2()}
 return r,logic
end

-- Consume a persistent one-shot marker before the native action; a lost reply never permits retry.
function api.send_once(expectedHero,expectedTarget)
 local r,logic=api.plan();assert(r.hero_id==expectedHero and r.target_id==expectedTarget,'Plan changed before submission')
 _G[sentKey]=r
 methods('SLGChooseHeroLogicFengHuoTaiSave').startTrip(logic,nil)
 return api.encode_flat_state(r)
end

-- Inspect only the selected event and owned test army, with no periodic network requests.
function api.status(armyId,heroId)
 checkWorld();local e=main:getTSLGBeaconTowerEventByCommObjID(target)
 local s=api.read_hero_state(heroId)
 local r={server_now_ms=clock()*1000,target_id=target,event_found=e~=nil,hero_id=heroId,hero_busy=s.busy,
  hero_state=s.hero_state,hero_remaining_ms=s.remaining_ms,hero_fresh=s.fresh,army_found=false}
 if e then r.event_state=e[3];r.event_army=e[4];r.event_start_s=e[5];r.event_end_s=e[6] end
 local rows=main._myActionState[2]
 for i=0,rows:get_Count()-1 do local a=rows:get_Item(i)
  if a[1]==armyId then
   assert(a[15][1]==heroId and a[5]==aimType and a[6]==target,'Test army identity changed')
   r.army_found=true;r.army_id=armyId;r.army_state=a[4];r.army_end_ms=a[11]
  end
 end
 return api.encode_flat_state(r)
end

-- Retreat only the accepted test army after authoritative arrival into active rescue; never claim rewards.
function api.recall_once(armyId,heroId)
 checkWorld();assert(not _G[recalledKey],'Test recall already submitted; never repeat')
 local e=assert(main:getTSLGBeaconTowerEventByCommObjID(target),'Rescue event absent')
 assert(e[3]==2 and e[4]==armyId,'Rescue arrival not confirmed; no recall sent')
 local s=api.read_hero_state(heroId);assert(s.fresh and s.army_known and s.busy,'Fresh busy hero required')
 local found
 local rows=main._myActionState[2]
 for i=0,rows:get_Count()-1 do local a=rows:get_Item(i)
  if a[1]==armyId then found=a end
 end
 assert(found and found[15][1]==heroId and found[5]==aimType and found[6]==target and
  found[4]~=2 and found[4]~=9 and found[4]~=7,'Arrived test army not confirmed')
 _G[recalledKey]={army_id=armyId,target_id=target}
 package.loaded.SLGMainController.__instanceDict.sendTSLGRetreatArmyReq(armyId)
 return 'test_recall_sent_once'
end

-- Restore only our wrapper layer, leaving the running helper's existing callbacks and gates intact.
function api.close()
 if rawget(scene,'notifyUpdateData')==sw then rawset(scene,'notifyUpdateData',rawScene) end
 if rawget(main,'notifyStateChange')==tw then rawset(main,'notifyStateChange',rawState) end
 return 'rescue_probe_closed'
end
return 'one_shot_rescue_probe_ready'
