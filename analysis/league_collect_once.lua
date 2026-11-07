-- One explicitly authorized league-mine departure. This chunk shares the private read probe's closures.

-- Resolve class declarations only, without creating a real scene, map popup or Unity object.
local function nativeMethods(name)
 local c=package.loaded[name]
 if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 if type(c)~='table' then local ok,v=pcall(require,name);if ok then c=v end end
 assert(type(c)=='table' and c.__instanceDict,'Native class unavailable: '..name)
 return c.__instanceDict
end

-- Generate the exact native league default using protocol-only slot adapters and native scene routines.
local function defaultLeagueFormation(h)
 local sceneMethods=nativeMethods('SLGChooseHeroScene')
 local soldierMethods=nativeMethods('SLGChosenSoldier')
 local leagueMethods=nativeMethods('SLGChooseHeroLogicLeagueCollect')
 local name,soldierType=debug.getupvalue(soldierMethods.initialize,1)
 assert(name=='T_TSoldierInfo','Follower schema changed')
 local function slot(left)
  local s={_soldierInfo=CSLNew(soldierType)}
  soldierMethods.setPosition(s,left)
  s.setSodierId=function(self,id) self._soldierInfo[1]=id end
  s.setNum=function(self,n) assert(n>=0 and n==math.floor(n),'Invalid native count');self._soldierInfo[2]=n end
  s.getNum=soldierMethods.getNum;s.getSoldierInfo=soldierMethods.getSoldierInfo
  s.setFreeNum=function(self,n) self._freeNum=n end
  return s
 end
 local enabled;local noop=function() end
 local fake={_currentSelectedHero=h,_soldierLeft=slot(true),_soldierRight=slot(false),
  commonScene={setStartBtnInteractable=function(self,v) enabled=v end},
  armyInfo={setTitle=noop,setEnemyCombatValueVisible=noop,setCombatValueAreaVisible=noop,
   setCombatValue=noop,SetTipText=noop,addValue=noop}}
 fake.getContent=function() return available end
 fake.getSelectedHero=function() return h end
 fake.getSoldierInfoList=sceneMethods.getSoldierInfoList
 fake.getCollectMax=sceneMethods.getCollectMax
 fake.getCollectSpeed=sceneMethods.getCollectSpeed
 fake.getCostSecond=sceneMethods.getCostSecond
 local logic=setmetatable({_scene=fake},{__index=leagueMethods});fake._logic=logic
 sceneMethods.updateSoldier(fake)
 local n=sceneMethods.getTotalSoldierNum(fake)
 local soldiers=sceneMethods.getSoldierInfoList(fake)
 local follower=h[2]:get_Item(0);local cap=main.getMaxSoldierForFight(follower[1])
 assert(enabled==true and n>0 and n<=cap and n<=follower[2],'Native league formation cannot depart')
 local sum=0
 for i=0,soldiers:get_Count()-1 do local s=soldiers:get_Item(i);assert(s[1]==follower[1],'Follower species changed');sum=sum+s[2] end
 assert(sum==n,'Native formation counts disagree')
 return logic,n,follower[1]
end

-- Prepare just one best ready collector using current target-specific speed, load and native defaults.
function api.league_once_plan()
 assert(main.mTSLGLoginMapRsp==bound and main.mIsMapLoaded,'World changed')
 assert(_G.REA_LEAGUE_12572_ONCE==nil,'This validation was already submitted; never retry')
 local r=league:getTSLGLeagueGetResourceRsp()
 assert(r and r~=beforeDetail and r[1]==0 and available and available[1]==0,'Fresh mine reads missing')
 local p=r[2];local shown=CSLTypes.SLGMapUtils.logicToDisplay(p[1])
 assert(p[2]==target and shown[1]==125 and shown[2]==72 and p[3]==10003,'Requested league iron mine changed')
 assert(p[9]==main:getMyLeagueId() and p[5]>0,'Mine is empty or not owned by our league')
 assert(manager:getModel(CSLTypes.SLGWarFogModel):isCellVisible(p[1][1],p[1][2],p[1][3]),'Mine is not visible')
 local config=search:searchTLeagueResource(p[3]);assert(config and r[3]:get_Count()<config[11],'Mine has no free shared slot')
 for i=0,r[3]:get_Count()-1 do assert(not main.checkIsMyArmy(r[3]:get_Item(i)),'An own army is already in this mine') end
 local world=api.read_hero_state();assert(world.fresh and world.army_known,'Fresh own army state required')
 for i=0,main._myActionState[2]:get_Count()-1 do
  local a=main._myActionState[2]:get_Item(i)
  assert(a[5]~=12 and a[6]~=target,'An own league-mine departure/return already exists')
 end
 local best,bestState
 for i=0,available[4]:get_Count()-1 do
  local h=available[4]:get_Item(i);local id=h[1][1][3];local s=api.read_hero_state(id)
  if s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and s.remaining_ms<=0 and
   nativeMethods('SLGChooseHeroItem').getActionState(h)==0 and h[2]:get_Count()>0 and h[6]>0 then
   if not best or h[6]>best[6] or (h[6]==best[6] and (h[5]>best[5] or (h[5]==best[5] and h[3]<best[3]))) then
    best=h;bestState=s
   end
  end
 end
 assert(best,'No ready hero available; no recovery items will be used')
 local logic,n,species=defaultLeagueFormation(best)
 local barrack=manager:getModel(CSLTypes.SLGBuildingsModel):getTSLGGetBarrackRsp()
 assert(barrack and barrack[1]==0 and barrack[4]:get_Item(species)[3][1]>=n,'Follower stock cannot be confirmed')
 assert(available[2]==target and available[3]==12 and available[5][1]==p[1][1] and available[5][2]==p[1][2],
  'Available-hero response does not match the mine')
 local record={hero_id=best[1][1][3],name=bestState.name,target_id=target,x=shown[1],y=shown[2],
  speed=best[6],load=best[5],travel_seconds=best[3],followers=n,soldier_id=species,
  secondary_target=logic:getTargetID2(),stock=p[5],occupied=r[3]:get_Count(),capacity=config[11]}
 return record,logic
end

-- Persist the at-most-once marker before invoking the native league startTrip2, even if it throws.
function api.league_once_send()
 local record,logic=api.league_once_plan()
 _G.REA_LEAGUE_12572_ONCE=record
 nativeMethods('SLGChooseHeroLogicLeagueCollect').startTrip2(logic,nil,false)
 return api.encode_flat_state(record)
end

-- Read one validation army after an explicit server refresh; no follow-up departures or item requests exist.
function api.league_once_status(heroId)
 local s=api.read_hero_state(heroId);local a=main:getMyArmyInfoByHeroGroupId(heroId)
 local r={fresh=s.fresh,army_known=s.army_known,busy=s.busy,hero_id=heroId,hero_state=s.hero_state,found=a~=nil}
 if a then r.army_id=a[1];r.stage=a[4];r.aim=a[5];r.target_id=a[6];r.end_ms=a[11] end
 return api.encode_flat_state(r)
end
return 'league_one_shot_ready'
