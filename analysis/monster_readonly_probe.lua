-- Temporary exact-target response capture. Only monster/detail and hero-list queries are available.
local api=assert(REA_MONSTER_READONLY)
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local scene=CSLTypes.SceneNotifier.getInstance()
local bound=main.mTSLGLoginMapRsp
local detail,available,target
local rawScene,rawMain,rawState=rawget(scene,'notifyUpdateData'),rawget(main,'notifyUpdateData'),rawget(main,'notifyStateChange')
local originalScene,originalMain,originalState=scene.notifyUpdateData,main.notifyUpdateData,main.notifyStateChange
local sw,mw,tw
local suppress=false
sw=function(self,id,payload,...)
 if type(payload)=='table' and payload[1]==0 and payload[2]==target then
  if id==1058 or id==1223 then detail=payload;return end
  if payload[3]==3 and type(payload[4])=='table' and payload[4].get_Count then available=payload;suppress=true;return end
 end
 return originalScene(self,id,payload,...)
end
mw=function(self,id,payload,...)
 if id==-9956 and type(payload)=='table' and payload[1]==0 and payload[2]==target then return end
 return originalMain(self,id,payload,...)
end
tw=function(self,id,...)
 if id==-9991 and suppress then suppress=false;return end
 return originalState(self,id,...)
end
rawset(scene,'notifyUpdateData',sw);rawset(main,'notifyUpdateData',mw);rawset(main,'notifyStateChange',tw)

-- Send only two read requests for one exact monster; no spending sender is exposed here.
function api.monster_query(id)
 assert(main.mTSLGLoginMapRsp==bound and main.mIsMapLoaded,'World changed')
 target=id;detail=nil;available=nil
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetMonsterDetailReq(id)
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq(id,3,0,0)
 return 'queries_sent'
end

-- Read native power/description for the actual server hero candidates and a specified follower count.
function api.monster_result()
 if not detail or not available then return '{"ready":false}' end
 local enc=api.encode_flat_state
 local _,update=debug.getupvalue(package.loaded.SLGChooseHeroArmyInfo.__instanceDict.setCombatValue,1)
 local _,tips=debug.getupvalue(update,1)
 local enemy=main.getQuestCombatValue(tonumber(detail[5]))
 local monsterFields={};for k,v in pairs(detail) do if type(v)=='number' then monsterFields['field_'..k]=v end end
 local search=CSLTypes.DBSearcher.sharedInstance()
 local config=search:searchTWildMonster_Map(detail[3])
 if not config then
  local shape={}
  for k,v in pairs(detail) do
   if type(v)=='table' then
    for a,b in pairs(v) do if type(b)=='number' then shape['d_'..k..'_'..a]=b end end
   elseif type(v)=='number' then shape['d_'..k]=v end
  end
  return '{"ready":true,"detail":'..enc(shape)..',"quest_strings":{},"heroes":[]}'
 end
 monsterFields.level=config[3]
 monsterFields.quest_id=config[5]
 monsterFields.enemy_power=enemy
 local pos=CSLTypes.SLGMapUtils.logicToDisplay(detail[6]);monsterFields.x=pos[1];monsterFields.y=pos[2]
 local q=search:searchTNewPlayQuest(tonumber(config[5]))
 local strings={}
 for k,v in pairs(q or {}) do if type(v)=='string' and #v<200 then strings['quest_'..k]=CSLTypes.YXSUtils.GBK2UTF8(v) end end
 local rows={}
 for i=0,available[4]:get_Count()-1 do
  local h=available[4]:get_Item(i)
  local id=h[1][1][3]
  local base=api.read_hero_state(id)
  local options=h[2]
  if options:get_Count()>0 then
   local follower=options:get_Item(0)
   local totalCap=main.getMaxSoldierForFight(follower[1])
   local total=math.min(totalCap,follower[2])
   for n=0,total do
    local fake={_currentSelectedHero=h,_soldierLeft={getNum=function() return math.floor(n/2) end},
      _soldierRight={getNum=function() return n-math.floor(n/2) end}}
    local power=package.loaded.SLGChooseHeroScene.__instanceDict.getMyCombatValue(fake)
    local text=tips(power,enemy)
    local side=power>=enemy and 0 or 1
    rows[#rows+1]=enc({hero_id=id,name=base.name,hero_state=base.hero_state,busy=base.busy,remaining_ms=base.remaining_ms,
     followers=n,follower_id=follower[1],max_total=totalCap,available_followers=follower[2],base_power=h[4],
     per_follower_power=h[7],power=power,enemy_power=enemy,recommendation=CSLArrayGet(text,side)})
   end
  end
 end
 return '{"ready":true,"detail":'..enc(monsterFields)..',"quest_strings":'..enc(strings)..',"heroes":['..table.concat(rows,',')..']}'
end

-- Restore precisely the original callbacks without removing other helpers' observers or APIs.
function api.monster_close()
 if rawget(scene,'notifyUpdateData')==sw then rawset(scene,'notifyUpdateData',rawScene) end
 if rawget(main,'notifyUpdateData')==mw then rawset(main,'notifyUpdateData',rawMain) end
 if rawget(main,'notifyStateChange')==tw then rawset(main,'notifyStateChange',rawState) end
 return 'closed'
end
return 'readonly_monster_probe_installed'
