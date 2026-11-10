-- Install roster-based recovery operations; this module never schedules actions itself.
local api=assert(REA_AUTO_INFANTRY, 'Troop API must be installed first')
local manager=CSLTypes.ModelManager.sharedInstance()
local model=manager:getModel(CSLTypes.SLGBuildingsModel)
local main=manager:getModel(CSLTypes.SLGMainModel)
local items=manager:getModel(CSLTypes.ItemsModel)
local controller=package.loaded.SLGBuildingsController.__instanceDict._instance
local boundMap,boundConfig=main.mTSLGLoginMapRsp,main.mMapConfigID
-- Resolve declarations on cold logins without creating UI instances or consuming recovery items.
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
local update=nativeMethods('HeroPalaceItem').Update
local use=nativeMethods('UpgradeAccelerationNewDialog').useButtonCallback
assert(type(update)=='function' and type(use)=='function','Native recovery callbacks unavailable')
local _,clock=debug.getupvalue(update,1)
local _,itemType=debug.getupvalue(use,2)
assert(type(clock)=='function' and itemType~=nil,'Native recovery constructor layout changed')
local heroRef,armyRef,speedRef
local heroSeq,armySeq,speedSeq=0,0,0
local heroSeen,armySeen=-1e15,-1e15
local heroNames={}
local activityPushes={}
local activityPushSeq=0
local viewHeroRef,viewArmyRef,viewPushSeq
local now=clock():GetCurrentServerTime()*1000
heroRef=model:getTSLGGetHeroPubRsp()
armyRef=main._myActionState
speedRef=model._stTSLGBuildSpeedupRsp

-- Label only verified native phases; unknown codes remain visible and never imply eligibility.
local function armyLabel(army)
 local state,aim=army[4],army[5]
 if type(state)~='number' or type(aim)~='number' then return '行动中（状态不明）' end
 if state==7 then return '已返回（待确认）' end
 if state==9 then return '返城中' end
 if state==2 or ((aim==0 or aim==1 or aim==12) and state==3) then return '行军中' end
 if (aim==0 or aim==1 or aim==12) and state==6 then return '采集中' end
 if type(main.isGarrisonAimType)=='function' and main.isGarrisonAimType(aim) then return '驻守中' end
 if type(main.IsGatherArmType)=='function' and main.IsGatherArmType(aim) then return '集结中' end
 if type(main.isAttackAimType)=='function' and main.isAttackAimType(aim) then
  if state==3 then return '进入战斗' end
  if state==11 then return '等待战斗' end
  return '战斗中'
 end
 return '行动中（状态'..tostring(state)..'）'
end

-- Capture already-received own-army pushes for display only; spending freshness remains unchanged.
function api.note_army_push(army)
 if type(army)~='table' or type(army[15])~='table' or type(army[15][1])~='number' or
  type(army[4])~='number' or type(army[5])~='number' then return end
 activityPushes[army[15][1]]={label=armyLabel(army),seen=clock():GetCurrentServerTime()*1000}
 activityPushSeq=activityPushSeq+1
end

-- Read one requested hero and fresh-response generations, conservatively excluding any active army.
local function snapshot(heroId)
 heroId=heroId or 303
 assert(type(heroId)=='number' and heroId==math.floor(heroId) and heroId>0 and heroId<=10000000, 'Invalid hero identifier')
 assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==boundMap and main.mMapConfigID==boundConfig,
  'World map changed; reconnect the helper')
 now=clock():GetCurrentServerTime()*1000
 local rsp=model:getTSLGGetHeroPubRsp()
 local armies=main._myActionState
 local speed=model._stTSLGBuildSpeedupRsp
 if rsp~=heroRef then heroSeq=heroSeq+1;heroRef=rsp;heroSeen=now end
 if armies~=armyRef then armySeq=armySeq+1;armyRef=armies;armySeen=now;activityPushes={} end
 if speed~=speedRef then speedSeq=speedSeq+1;speedRef=speed end
 local hero
 if type(rsp)=='table' and rsp[1]==0 and type(rsp[2])=='table' and type(rsp[2][2])=='table' then
  local list=rsp[2][2][1]
  if type(list)=='table' and list.get_Count then
   for i=0,list:get_Count()-1 do
    local entry=list:get_Item(i)
    if type(entry)=='table' and type(entry[1])=='table' and entry[1][3]==heroId then
     assert(hero==nil, 'Duplicate hero identifier')
     hero=entry
    end
   end
  end
 end
 local busy=false
 local ownArmy
 local armyKnown=type(armies)=='table' and armies[1]==0
 -- Both army collections are processed by the game's all-army response handler.
 if armyKnown then
  for _,index in ipairs({2,3}) do
   local list=armies[index]
   if type(list)~='table' or not list.get_Count then armyKnown=false;break end
   for i=0,list:get_Count()-1 do
    local entry=list:get_Item(i)
    if type(entry)~='table' or type(entry[15])~='table' or type(entry[15][1])~='number' then
     armyKnown=false;break
    end
    if entry[15][1]==heroId then
     busy=true
     if index==2 then ownArmy=entry end
    end
   end
  end
 end
 local found=type(hero)=='table' and type(hero[2])=='number' and type(hero[3])=='number' and hero[3]>=0
 local age=math.max(now-heroSeen,now-armySeen)
 local fresh=heroSeq>0 and armySeq>0 and age>=0 and age<=3000
 local name=heroNames[heroId] or tostring(heroId)
 if found and not heroNames[heroId] then
  local config=CSLTypes.DBSearcher.sharedInstance():searchHeroInfoByStarAndGroup(1,heroId)
  if type(config)=='table' and type(config[7])=='string' then
   name=CSLTypes.YXSUtils.GBK2UTF8(config[7]);heroNames[heroId]=name
  end
 end
 local label='数据不明'
 local confirmed=0
 if found and armyKnown and heroSeq>0 and armySeq>0 then
  confirmed=math.min(heroSeen,armySeen)
  if ownArmy then
   local ok,value=pcall(armyLabel,ownArmy)
   label=ok and value or '行动中（状态不明）'
   confirmed=armySeen
  elseif hero[2]==20 then label='活动占用';confirmed=heroSeen
  elseif hero[2]~=0 then label='活动占用（状态'..hero[2]..'）';confirmed=heroSeen
  elseif busy then label='行动中（待确认）'
  elseif hero[3]>now then label='恢复中'
  else label='空闲' end
 end
 local push=activityPushes[heroId]
 if found and armyKnown and push and push.seen>=armySeen then label=push.label;confirmed=push.seen end
 return {hero_id=heroId,name=name,power=found and hero[4] or 0,
  activity_label=label,confirmed_ms=math.max(0,confirmed),
  found=found, fresh=fresh, army_known=armyKnown, busy=busy,
  hero_state=found and hero[2] or -1, finish_ms=found and hero[3] or 0,
  remaining_ms=found and math.max(0,hero[3]-now) or 0, items=items:getItemCount(70291),
  hero_seq=heroSeq,army_seq=armySeq,speed_seq=speedSeq,
  speed_ret=type(speed)=='table' and speed[1] or -999,
  speed_kind=type(speed)=='table' and speed[2] or -1,
  speed_type=type(speed)=='table' and speed[3] or -1,
  speed_target=type(speed)=='table' and speed[4] or -1}
end

-- Encode a bounded credential-free status with no dependency on a JSON module.
local function encode(state)
 local out={}
 for key,value in pairs(state) do
  local encoded
  if type(value)=='string' then
   encoded='"'..string.gsub(value,'[%z\1-\31\\"]',function(c) return string.format('\\u%04x',string.byte(c)) end)..'"'
  elseif type(value)=='boolean' then encoded=tostring(value)
  else encoded=string.format('%.0f',value) end
  out[#out+1]='"'..key..'":'..encoded
 end
 return '{'..table.concat(out,',')..'}'
end

-- Read any owned hero, including its name, activity and response generations.
function api.hero_status(heroId)
 return encode(snapshot(heroId))
end

-- Share the same final freshness/activity check with collection, avoiding an independent recovery path.
api.read_hero_state=snapshot
api.encode_flat_state=encode

-- Count the same aim0/aim1 own-army entries as the game's native collection-capacity check.
function api.read_collection_queue(world)
 world=world or snapshot()
 local used=0
 local known=world.army_known
 local armies=main._myActionState and main._myActionState[2]
 if type(armies)~='table' or not armies.get_Count then known=false
 else
  for i=0,armies:get_Count()-1 do
   local entry=armies:get_Item(i)
   if type(entry)~='table' or type(entry[5])~='number' then known=false
   elseif entry[5]==0 or entry[5]==1 then used=used+1 end
  end
 end
 local limit=type(main.getMaxCollectionArmyCount)=='function' and main:getMaxCollectionArmyCount() or -1
 known=known and type(limit)=='number' and limit>=0 and limit==math.floor(limit)
 local nativeKnown=type(main.checkMaxCollectionArmyCount)=='function'
 local blocked=nativeKnown and main:checkMaxCollectionArmyCount()==true
 -- An expired snapshot is not a full queue; keep counts visible while denying unverified departures.
 local reason='available'
 if not known or not nativeKnown then reason='unknown'
 elseif not world.fresh then reason='stale'
 elseif used>=limit then reason='full'
 elseif blocked then reason='native_blocked' end
 return {queue_used=known and used or -1,queue_limit=limit,queue_known=known,
  queue_free=reason=='available',queue_reason=reason}
end

-- Export the server roster; selection is caller-owned and new heroes are never auto-selected.
function api.hero_list()
 local base=snapshot()
 local rsp=model:getTSLGGetHeroPubRsp()
 local list=type(rsp)=='table' and rsp[1]==0 and rsp[2] and rsp[2][2] and rsp[2][2][1]
 local rows={}
 local ids={}
 if type(list)=='table' and list.get_Count then
  assert(list:get_Count()<=1000, 'Unexpected hero roster size')
  for i=0,list:get_Count()-1 do
   local hero=list:get_Item(i)
   local id=hero[1][3]
   assert(not ids[id], 'Duplicate roster hero')
   ids[id]=true
   rows[#rows+1]=encode(snapshot(id))
  end
 end
 local queue=api.read_collection_queue(base)
 return '{"heroes":['..table.concat(rows,',')..'],"hero_seq":'..base.hero_seq..
  ',"army_seq":'..base.army_seq..',"fresh":'..tostring(base.fresh)..',"items":'..base.items..
  ',"queue_used":'..queue.queue_used..',"queue_limit":'..queue.queue_limit..',"queue_known":'..tostring(queue.queue_known)..'}'
end

-- Publish roster changes already present in memory; no hero/army requests or periodic server reads.
function api.hero_view()
 local hero=model:getTSLGGetHeroPubRsp()
 local army=main._myActionState
 if hero==viewHeroRef and army==viewArmyRef and activityPushSeq==viewPushSeq then return '{"changed":false}' end
 viewHeroRef=hero;viewArmyRef=army;viewPushSeq=activityPushSeq
 return '{"changed":true,"roster":'..api.hero_list()..'}'
end

-- Query authoritative hero and activity data without opening a building or spending anything.
function api.hero_refresh()
 snapshot()
 controller:sendTSLGGetHeroPubReq()
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAllArmyReq()
 return 'hero_refresh_sent'
end

-- Recheck eligibility on UnityMain immediately before consuming one recovery-only item.
function api.hero_speed(heroId)
 assert(heroId~=nil, 'An explicit selected hero identifier is required')
 local state=snapshot(heroId)
 assert(state.found and state.fresh and state.army_known, 'Hero state unknown or stale')
 assert(state.hero_state==0 and not state.busy, 'Hero is busy; recovery skipped')
 assert(state.remaining_ms>0, 'Hero does not need recovery')
 assert(state.items>0, 'Five-minute hero recovery items exhausted')
 local vec=CSLNew(CSLTypes.CSLList)
 local item=CSLNew(itemType)
 item[1]=70291;item[2]=1
 vec:Add(item)
 controller:sendTSLGBuildSpeedupReq(3,500,state.hero_id,vec)
 return 'hero_speed_sent'
end
return 'hero_api_installed'
