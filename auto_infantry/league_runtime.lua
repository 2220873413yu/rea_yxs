-- Caller-driven own-alliance mining; no timer, departure or recovery runs inside a callback.
local api=assert(REA_AUTO_INFANTRY)
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local league=manager:getModel(CSLTypes.SLGLeagueModel)
local search=CSLTypes.DBSearcher.sharedInstance()
local ctrl=CSLTypes.SLGLeagueController.getInstance()
local scene=CSLTypes.SceneNotifier.getInstance()
local trip=manager:getModel(CSLTypes.SLGArmyTripModel)
local _,clock=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
local bound=main.mTSLGLoginMapRsp
local encode=api.encode_flat_state
local beforeBuild,beforeDetail,target,available,buildAt,detailAt
local requested,pending,suppress=false,false,false
local attempted=false
local pushSeq=0
local lastPush={}
local rawScene,rawState=rawget(scene,'notifyUpdateData'),rawget(main,'notifyStateChange')
local originalScene,originalState=scene.notifyUpdateData,main.notifyStateChange

-- Reject old-account objects even for local display and never reuse them to authorize spending.
local function checkWorld()
 assert(main.mTSLGLoginMapRsp==bound and main.mIsMapLoaded,'World map changed; reconnect the helper')
end

-- Resolve native declarations without constructing graphics, popups or a scene.
local function nativeMethods(name)
 local c=package.loaded[name]
 if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 if type(c)~='table' then local ok,v=pcall(require,name);if ok then c=v end end
 assert(type(c)=='table' and c.__instanceDict,'Native class unavailable: '..name)
 return c.__instanceDict
end

-- Observe meaningful own-army transitions, not query response generations or countdown ticks.
local observer={class={name='REALeagueCollectionObserver'}}
function observer:updateSelf(param)
 local a=param and param.updateData
 if not param or param.id~=2 or type(a)~='table' or not main.checkIsMyArmy(a) then return end
 local signature=tostring(a[4])..':'..tostring(a[5])..':'..tostring(a[6])..':'..tostring(a[11])
 if lastPush[a[1]]~=signature then lastPush[a[1]]=signature;pushSeq=pushSeq+1 end
end
trip:addObserver(observer)
local sw=function(self,id,payload,...)
 if pending and id==1060 and type(payload)=='table' and payload[2]==target and payload[3]==12 then
  available=payload;pending=false;suppress=true;return
 end
 return originalScene(self,id,payload,...)
end
local tw=function(self,id,...)
 if suppress and id==-9991 then suppress=false;return end
 return originalState(self,id,...)
end
rawset(scene,'notifyUpdateData',sw);rawset(main,'notifyStateChange',tw)

-- Restore the exact callback chain in reverse installation order on detach/reconnect.
function api.league_close()
 pending=false;suppress=false
 trip:removeObserver(observer)
 if rawget(scene,'notifyUpdateData')==sw then rawset(scene,'notifyUpdateData',rawScene) end
 if rawget(main,'notifyStateChange')==tw then rawset(main,'notifyStateChange',rawState) end
 return 'league_closed'
end

-- Read only already-received changes; this function never sends a network request.
function api.league_watch()
 checkWorld()
 local r=league:getTSLGLeagueGetAllBuildRsp()
 local p=r and r[1]==0 and r[5]
 local mine=type(p)=='table' and tostring(p[2])..':'..tostring(p[3])..':'..tostring(p[9]) or 'none'
 local d=league:getTSLGLeagueGetResourceRsp()
 local p=d and d[1]==0 and d[2]
 return encode({seq=pushSeq,mine=mine,stock=type(p)=='table' and p[5] or -1,
  occupied=d and d[1]==0 and d[3] and d[3]:get_Count() or -1})
end

-- Ask the server for the current account's alliance buildings; stale map chunks are never a fallback.
function api.league_build_query()
 checkWorld();beforeBuild=league:getTSLGLeagueGetAllBuildRsp()
 requested=true;buildAt=nil;detailAt=nil;available=nil;pending=false;target=nil
 ctrl:sendTSLGLeagueGetAllBuildReq()
 return 'league_build_queried'
end

-- Accept a newly received own-alliance mine only, including the valid no-mine response.
function api.league_build_result()
 checkWorld();local r=league:getTSLGLeagueGetAllBuildRsp()
 if not requested or not r or r==beforeBuild then return '{"ready":false}' end
 assert(r[1]==0,'Alliance building query failed: '..tostring(r[1]))
 buildAt=buildAt or clock():GetCurrentServerTime()*1000
 local p=r[5]
 local own=type(p)=='table' and type(p[2])=='number' and p[2]>0 and p[9]==main:getMyLeagueId()
 return encode({ready=true,found=own,target_id=own and p[2] or 0})
end

-- Request fresh mine details and target-specific hero speeds, consuming only our exact selection popup.
function api.league_mine_query(id)
 checkWorld();local b=league:getTSLGLeagueGetAllBuildRsp()
 assert(buildAt and b~=beforeBuild and b[1]==0 and type(b[5])=='table' and b[5][2]==id and
  b[5][9]==main:getMyLeagueId(),'Fresh own alliance mine required')
 nativeMethods('SLGChooseHeroItem')
 target=id;available=nil;pending=false;detailAt=nil;beforeDetail=league:getTSLGLeagueGetResourceRsp()
 ctrl:sendTSLGLeagueGetResourceReq(id)
 return 'league_mine_queried'
end

-- Poll only local response arrival during this one explicit read, not the server on a schedule.
function api.league_mine_result()
 checkWorld();local r=league:getTSLGLeagueGetResourceRsp()
 if not r or r==beforeDetail then return '{"ready":false}' end
 assert(r[1]==0,'Alliance mine query failed: '..tostring(r[1]))
 assert(r[2][2]==target,'Alliance mine response mismatch')
 detailAt=detailAt or clock():GetCurrentServerTime()*1000
 return '{"ready":true}'
end

-- Query heroes only after the mine is known to have stock/space; an empty mine is a wait, not a send error.
function api.league_heroes_query()
 checkWorld();assert(detailAt and target,'Mine details required')
 available=nil;pending=true
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq(target,12,0,0)
 return 'league_heroes_queried'
end

-- Await one exact native hero reply, surfacing its actual refusal instead of interpreting it as no heroes.
function api.league_heroes_result()
 checkWorld();if not available then return '{"ready":false}' end
 assert(available[1]==0,'Alliance available-hero query failed: '..tostring(available[1]))
 assert(available[2]==target and available[3]==12,'Alliance hero response mismatch')
 return '{"ready":true}'
end

-- Stop popup suppression after success, failure or timeout; late manual queries retain native behavior.
function api.league_cancel_query()
 pending=false;suppress=false;return 'cancelled'
end

-- Export own aim12 armies including returning/manual armies, independent of whether the mine still exists.
function api.league_schedule()
 checkWorld();local world=api.read_hero_state()
 assert(world.fresh and world.army_known,'Fresh own armies required')
 local rows,seen={},{}
 for _,index in ipairs({2,3}) do local list=main._myActionState[index]
  for i=0,list:get_Count()-1 do local a=list:get_Item(i)
   if a[5]==12 and not seen[a[1]] then
    seen[a[1]]=true;local s=api.read_hero_state(a[15][1])
    rows[#rows+1]=encode({army_id=a[1],hero_id=a[15][1],name=s.name,state=a[4],target_id=a[6],
     end_ms=type(a[11])=='number' and a[11] or 0})
   end
  end
 end
 return '{"server_now_ms":'..string.format('%.0f',clock():GetCurrentServerTime()*1000)..',"stages":['..table.concat(rows,',')..']}'
end

-- Export verified target metrics; speed comes from this mine's native hero response, not bonus arithmetic.
function api.league_metrics()
 checkWorld();assert(detailAt,'Fresh mine details required')
 local r=league:getTSLGLeagueGetResourceRsp();local p=r[2];local c=assert(search:searchTLeagueResource(p[3]))
 assert(r~=beforeDetail and r[1]==0 and p[2]==target and p[9]==main:getMyLeagueId(),'Mine identity changed')
 local pos=CSLTypes.SLGMapUtils.logicToDisplay(p[1]);local own=false
 for i=0,r[3]:get_Count()-1 do if main.checkIsMyArmy(r[3]:get_Item(i)) then own=true end end
 local info={target_id=target,config_id=p[3],x=pos[1],y=pos[2],stock=p[5],kind=c[2],
  name=CSLTypes.YXSUtils.GBK2UTF8(c[3]),capacity=c[11],occupied=r[3]:get_Count(),own_present=own,
  visible=manager:getModel(CSLTypes.SLGWarFogModel):isCellVisible(p[1][1],p[1][2],p[1][3])}
 local rows={}
 if available and available[1]==0 then
 for i=0,available[4]:get_Count()-1 do local h=available[4]:get_Item(i);local s=api.read_hero_state(h[1][1][3])
  rows[#rows+1]=encode({hero_id=s.hero_id,name=s.name,speed=h[6],load=h[5],travel_seconds=h[3],
   ready=s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and s.remaining_ms<=0 and
    nativeMethods('SLGChooseHeroItem').getActionState(h)==0 and h[2]:get_Count()>0 and h[2]:get_Item(0)[2]>0,
   remaining_ms=s.remaining_ms})
 end
 end
 return '{"mine":'..encode(info)..',"heroes":['..table.concat(rows,',')..']}'
end

-- Generate native default league troops using protocol-only adapters, without creating Unity UI objects.
local function defaultLeagueFormation(h)
 local sm=nativeMethods('SLGChooseHeroScene');local soldier=nativeMethods('SLGChosenSoldier')
 local lm=nativeMethods('SLGChooseHeroLogicLeagueCollect')
 local name,soldierType=debug.getupvalue(soldier.initialize,1)
 assert(name=='T_TSoldierInfo','Follower schema changed')
 local function slot(left)
  local s={_soldierInfo=CSLNew(soldierType)};soldier.setPosition(s,left)
  s.setSodierId=function(self,id) self._soldierInfo[1]=id end
  s.setNum=function(self,n) assert(n>=0 and n==math.floor(n),'Invalid native count');self._soldierInfo[2]=n end
  s.getNum=soldier.getNum;s.getSoldierInfo=soldier.getSoldierInfo;s.setFreeNum=function(self,n) self._freeNum=n end
  return s
 end
 local enabled;local noop=function() end
 local fake={_currentSelectedHero=h,_soldierLeft=slot(true),_soldierRight=slot(false),
  commonScene={setStartBtnInteractable=function(self,v) enabled=v end},
  armyInfo={setTitle=noop,setEnemyCombatValueVisible=noop,setCombatValueAreaVisible=noop,
   setCombatValue=noop,SetTipText=noop,addValue=noop}}
 fake.getContent=function() return available end;fake.getSelectedHero=function() return h end
 fake.getSoldierInfoList=sm.getSoldierInfoList;fake.getCollectMax=sm.getCollectMax
 fake.getCollectSpeed=sm.getCollectSpeed;fake.getCostSecond=sm.getCostSecond
 local logic=setmetatable({_scene=fake},{__index=lm});fake._logic=logic
 sm.updateSoldier(fake)
 local n=sm.getTotalSoldierNum(fake);local soldiers=sm.getSoldierInfoList(fake);local follower=h[2]:get_Item(0)
 assert(enabled==true and n>0 and n<=main.getMaxSoldierForFight(follower[1]) and n<=follower[2],'Native league formation cannot depart')
 local sum=0
 for i=0,soldiers:get_Count()-1 do local s=soldiers:get_Item(i);assert(s[1]==follower[1],'Follower species changed');sum=sum+s[2] end
 assert(sum==n,'Native formation counts disagree')
 local b=manager:getModel(CSLTypes.SLGBuildingsModel):getTSLGGetBarrackRsp()
 assert(b and b[1]==0 and b[4]:get_Item(follower[1])[3][1]>=n,'Follower stock cannot be confirmed')
 return logic,n
end

-- Authorize one exact fresh hero/target departure; reserve before native send and never retry uncertainty.
function api.league_dispatch(id,heroId)
 checkWorld();assert(not attempted,'Alliance departure result uncertain; reconnect after checking the game')
 local now=clock():GetCurrentServerTime()*1000
 assert(detailAt and available and available[1]==0 and now>=detailAt and now-detailAt<=3000,'Alliance mine details expired')
 local schedule=api.league_schedule();local lists=main._myActionState
 for _,index in ipairs({2,3}) do local l=lists[index];for i=0,l:get_Count()-1 do
  assert(l:get_Item(i)[5]~=12,'Own alliance army already exists')
 end end
 local m=api.league_metrics();local r=league:getTSLGLeagueGetResourceRsp();local p=r[2]
 local c=search:searchTLeagueResource(p[3])
 assert(id==target and p[5]>0 and r[3]:get_Count()<c[11],'Alliance mine empty or full')
 assert(manager:getModel(CSLTypes.SLGWarFogModel):isCellVisible(p[1][1],p[1][2],p[1][3]),'Mine is not visible')
 for i=0,r[3]:get_Count()-1 do assert(not main.checkIsMyArmy(r[3]:get_Item(i)),'Own mine army exists') end
 assert(available[5][1]==p[1][1] and available[5][2]==p[1][2],'Mine position changed')
 local s=api.read_hero_state(heroId)
 assert(s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and s.remaining_ms<=0,'Hero is not ready')
 local h
 for i=0,available[4]:get_Count()-1 do local v=available[4]:get_Item(i);if v[1][1][3]==heroId then h=v end end
 assert(h and nativeMethods('SLGChooseHeroItem').getActionState(h)==0,'Native hero eligibility changed')
 local logic,n=defaultLeagueFormation(h)
 attempted=true
 nativeMethods('SLGChooseHeroLogicLeagueCollect').startTrip2(logic,nil,false)
 return encode({hero_id=heroId,target_id=id,followers=n,secondary_target=logic:getTargetID2()})
end

-- Clear the spending reservation only after fresh own-army data confirms the exact accepted server army.
function api.league_ack(id,heroId,armyId)
 local s=api.read_hero_state(heroId);assert(s.fresh and s.army_known,'Fresh acceptance required')
 local found=false
 for _,index in ipairs({2,3}) do local l=main._myActionState[index];for i=0,l:get_Count()-1 do local a=l:get_Item(i)
  if a[1]==armyId and a[15][1]==heroId and a[5]==12 and a[6]==id then found=true end
 end end
 assert(found,'Accepted alliance army not confirmed');attempted=false;return 'confirmed'
end
return 'league_ready'
