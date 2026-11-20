-- Native per-type policies. Only explicit gated API calls can dispatch, scout or skip combat.
local api=assert(REA_AUTO_INFANTRY);local n=assert(api.beacon_native)
local main,map,search=n.main,n.map,n.search
local buildings=n.manager:getModel(CSLTypes.SLGBuildingsModel)
local resource,resourceAt,resourceTarget,wantResource
local scoutCount,scoutAt,scoutPending
local monster,monsterAt,monsterTarget,wantMonster
local attempts={scout={},skip={}}
local stockObserver={class={name='REABeaconScoutStock'}}

-- Count existing scouts only after a new native stock response for species803.
function stockObserver:updateSelf(param)
 if param and param.id==11116 and type(param.addData)=='table' and param.addData[1]==803 then
  scoutCount=param.addData[2];scoutAt=n.now();scoutPending=false
 end
end
buildings:addObserver(stockObserver)
n.close=function() buildings:removeObserver(stockObserver);wantResource=false end

-- Resolve the event configuration rather than identifying its type from icon colour or coordinates.
local function kind(e) return assert(search:searchTMapIntelStation_Event_Map(e[2]))[2] end

-- Capture only the pending resource's native response, suppressing its normal popup.
n.consume=function(id,payload)
 if id==-9956 and monsterTarget and type(payload)=='table' and payload[2]==monsterTarget then return true end
 if id==-9995 and wantResource and type(payload)=='table' then
  local ok,id2=pcall(function() return payload[2][1][1][2] end)
  if ok and id2==resourceTarget then
   assert(payload[1]==0,'Beacon resource query refused')
   resource=payload;resourceAt=n.now();wantResource=false;return true
  end
 end
 return false
end
n.cancel=function() wantResource=false;resource=nil;wantMonster=false end

-- The native monster entrance passes the detail's quest ID as the third availability argument.
n.targetQuery=function(e)
 monster=nil;monsterTarget=e[1][2];wantMonster=kind(e)==4
 if wantMonster then n.methods('SLGMainController').sendTSLGGetMonsterDetailReq(monsterTarget) end
end
n.consumeScene=function(id,payload)
 if wantMonster and (id==1058 or id==1223) and type(payload)=='table' and payload[2]==monsterTarget then
  monster=payload;monsterAt=n.now();wantMonster=false;return true
 end
 return false
end
n.targetResult=function()
 if wantMonster then return '{"ready":false}' end
 if monster then
  assert(monster[1]==0 and monster[4]==0 and tonumber(monster[5])>0,'Beacon monster unavailable')
  local e=n.event(monsterTarget);local p=e[1][1]
  assert(monster[6][1]==p[1] and monster[6][2]==p[2],'Beacon monster detail position mismatch')
 end
 return '{"ready":true}'
end

-- Resource eligibility needs the real detail, not just the generic event icon.
n.beforeCandidates=function(e)
 resource=nil;resourceTarget=e[1][2];wantResource=kind(e)==3
 if wantResource then
  package.loaded.SLGMainController.__instanceDict._instance:sendTSLGResourceInfo(resourceTarget)
 end
 if kind(e)==4 then
  assert(monster and monsterTarget==e[1][2] and n.now()-monsterAt<=3000,'Beacon monster detail required')
  return tonumber(monster[5])
 end
 return 0
end
n.candidatesReady=function(e) return kind(e)~=3 or resource~=nil end

-- Run the game's event-specific permission predicate on its actual response and configuration.
local function canResource(e)
 assert(resource and resourceTarget==e[1][2] and n.now()-resourceAt<=3000,'Beacon resource detail expired')
 local c=assert(search:searchTMapIntelStation_Event_Map(e[2]))
 local cfg=assert(search:searchTTMapIntelStation_Resource_Map(c[3]),'Beacon resource configuration missing')
 return n.methods('SLGFengHuoTaiResourceCommonDialog').canCollect({mTSLGResourceInfoRsp=resource,resourceConfig=cfg})==true
end

-- Compute the native default formation's displayed total power and its exact victory recommendation.
local function monsterMetrics(h,e)
 if h[2]:get_Count()==0 or h[2]:get_Item(0)[2]<2 or main.getMaxSoldierForFight(h[2]:get_Item(0)[1])<2 then
  return {power=h[4],eligible=false,overwhelming=false,strength_known=false}
 end
 local _,_,_,power,enemy=n.formation(h,e)
 assert(type(power)=='number' and type(enemy)=='number' and enemy>0,'Beacon enemy power unavailable: '..tostring(power)..'/'..tostring(enemy))
 local _,update=debug.getupvalue(n.methods('SLGChooseHeroArmyInfo').setCombatValue,1)
 local _,tips=debug.getupvalue(update,1)
 local label=CSLArrayGet(tips(power,enemy),power>=enemy and 0 or 1)
 local win=power>=enemy and label=='我方超强，胜券在握'
 return {power=power,eligible=win and main:isSLGMonthCardEnabled()==true,overwhelming=win}
end
n.metrics=function(h,e)
 if kind(e)==4 then return monsterMetrics(h,e) end
 return {power=h[4],eligible=kind(e)~=3 or canResource(e)}
end

-- Recheck native combat/resource conditions on the update thread immediately before departure.
n.guardDispatch=function(e,h)
 if kind(e)==4 then
  assert(monster and monster[4]==0 and n.now()-monsterAt<=3000,'Beacon monster detail expired')
  assert(monsterMetrics(h,e).eligible,'Beacon monster is not overwhelming or skip unavailable')
 end
 if kind(e)==3 then assert(canResource(e),'Beacon resource cannot be collected') end
end

-- Invoke the event's own native sender with its target-bound response and default formation.
n.startTrip=function(logic,e)
 local cls=({[1]='SLGChooseHeroLogicFengHuoTaiSave',[3]='SLGChooseHeroLogicCollectResource',[4]='SLGChooseHeroLogicMonster'})[kind(e)]
 local methods=n.methods(assert(cls))
 -- The resource specialization inherits startTrip; native startTrip2 is its actual packet builder.
 if kind(e)==3 then methods.startTrip2(logic,nil,false) else methods.startTrip(logic,nil) end
end

-- Query fresh scout inventory once; no purchase or automatic training is reachable from this module.
function api.beacon_scout_query(id)
 n.world();local e=n.event(id);assert(kind(e)==2 and e[3]==0,'Treasure unavailable')
 scoutPending=true;scoutCount=nil
 package.loaded.SLGBuildingsController.__instanceDict._instance:sendTSLGGetSoldierNumReq(803)
 return 'beacon_scout_stock_requested'
end

-- Match an existing scout's destination to prevent a second dispatch during its journey, including after restart.
local function scoutStages()
 local rows={};local list=main._myScoutInfoList
 if list then for i=0,list:get_Count()-1 do local s=list:get_Item(i);local path=s[3]
  assert(path and path:get_Count()>0,'Scout path unavailable')
  local p=path:get_Item(path:get_Count()-1);local shown=CSLTypes.SLGMapUtils.logicToDisplay(p)
  -- Native lEndTime is already milliseconds and may outlive the corresponding treasure event.
  if type(s[2])=='number' and s[2]>n.now() then
   rows[#rows+1]={end_ms=s[2],x=shown[1],y=shown[2]}
  end
 end end
 return rows
end
n.scoutStages=scoutStages

-- Check the native treasure scout flow: cost, stock and duplicate protection apply even in fog.
function api.beacon_scout_result(id)
 n.world();local e=n.event(id);assert(kind(e)==2,'Not a treasure event')
 if scoutPending or scoutCount==nil then return '{"ready":false}' end
 local cfg=assert(search:searchGlobalVariable(103010));local divisor=math.floor(tonumber(cfg[2]))
 assert(divisor>0,'Scout cost configuration invalid')
 local distance=CSLTypes.SLGMapUtils.calMapP2PDistance(e[1][1],map:getMyMainCityCoordinates())
 local cost=math.floor((distance+divisor-1)/divisor)
 local p=e[1][1]
 local shown=CSLTypes.SLGMapUtils.logicToDisplay(p);local busy=false
 for _,s in ipairs(scoutStages()) do if s.x==shown[1] and s.y==shown[2] and s.end_ms>n.now() then busy=true end end
 return api.encode_flat_state({ready=true,event_id=id,cost=cost,stock=scoutCount,x=shown[1],y=shown[2],
  fresh=n.now()-scoutAt<=3000,eligible=not busy and not attempts.scout[id] and e[3]==0 and scoutCount>=cost})
end

-- Spend existing scouts once through the native confirm callback, only for a selected beacon treasure.
function api.beacon_scout(id)
 local e=n.event(id)
 assert(kind(e)==2 and e[3]==0 and not attempts.scout[id] and not scoutPending and scoutCount~=nil and
  n.now()-scoutAt<=3000,'Fresh treasure scout stock required')
 local p=e[1][1];local shown=CSLTypes.SLGMapUtils.logicToDisplay(p)
 local k=math.floor(tonumber(search:searchGlobalVariable(103010)[2]));assert(k>0,'Invalid scout cost')
 local cost=math.floor((CSLTypes.SLGMapUtils.calMapP2PDistance(p,map:getMyMainCityCoordinates())+k-1)/k)
 assert(scoutCount>=cost,'Insufficient scouts; no purchase')
 for _,s in ipairs(scoutStages()) do assert(s.x~=shown[1] or s.y~=shown[2] or s.end_ms<=n.now(),'Scout already inbound') end
 local _,click=debug.getupvalue(n.methods('SLGScoutDialog').Awake,1)
 assert(type(click)=='function','Native scout callback unavailable')
 attempts.scout[id]=true;click({mScoutGoalPos=p,popLayout=nil})
 return api.encode_flat_state({event_id=id,x=shown[1],y=shown[2],logic_x=p[1],logic_y=p[2],cost=cost})
end

-- Skip only an arrived owned beacon monster army; ordinary hunt armies and noncombat events cannot pass.
function api.beacon_skip(id,heroId,armyId)
 n.world();local e=n.event(id);assert(kind(e)==4,'Only beacon monsters may skip combat')
 local a=n.ownArmy(id,heroId,armyId)
 assert(a[4]==3 and main:isSLGMonthCardEnabled()==true and not attempts.skip[armyId],'Beacon quick combat unavailable')
 local _,click=debug.getupvalue(n.methods('SLGSitdownPromptDialog').Start,3)
 assert(type(click)=='function','Native quick combat callback missing')
 attempts.skip[armyId]=true;click({mTArmyInfo=a});return 'beacon_skip_sent'
end

-- Cached stock and scout journeys are passive wake hints; this function sends no request.
n.watch=function()
 -- Use the verified barrack response also read by troop automation; the client has no getSoldierInfoById.
 local response=buildings:getTSLGGetBarrackRsp()
 local stock=response and response[1]==0 and response[4] and response[4]:get_Item(803)
 local parts={tostring(stock and stock[3] and stock[3][1] or scoutCount)}
 for _,s in ipairs(scoutStages()) do parts[#parts+1]=s.x..':'..s.y..':'..s.end_ms end
 table.sort(parts);return table.concat(parts,'|')
end
return 'beacon_all_types_installed'
