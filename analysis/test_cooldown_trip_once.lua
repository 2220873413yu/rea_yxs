-- User-authorized single server-validation attempt. No recovery, training, or repeated sends.
assert(REA_COOLDOWN_TRIP_TEST_SENT==nil, 'A cooldown trip test was already attempted; never retry automatically')
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local building=manager:getModel(CSLTypes.SLGBuildingsModel)
assert(main.mIsMapLoaded, 'World map not loaded')
local seen={}
local visited=0
local scenes={}
-- Locate only the observer-owned domain request context without changing UI selection.
local function find(node,depth)
 if type(node)~='table' or seen[node] or depth>8 or visited>8000 then return end
 seen[node]=true;visited=visited+1
 if type(rawget(node,'_content'))=='table' and type(rawget(node,'_chooseData'))=='table' then
  local logic=rawget(node,'_logic')
  if type(logic)=='table' and logic.class and logic.class.name=='SLGChooseHeroLogicMonster' then scenes[#scenes+1]=node end
 end
 for k,v in pairs(node) do if k~='__instanceDict' and k~='__c' and k~='class' and k~='super' then find(v,depth+1) end end
end
find(main.observers,0);find(main.tmpObservers,0)
assert(#scenes==1, 'Exactly one active monster request context is required')
local scene=scenes[1]
local content=scene._content
assert(content[2]==148532 and content[3]==3 and content[6]==100401 and content[11]==0,
 'The selected monster or request mode changed; no request sent')
assert(scene._currentSelectedHero==nil, 'A different hero was selected; no request sent')
local heroes=building:getTSLGGetHeroPubRsp()
assert(type(heroes)=='table' and heroes[1]==0, 'Hero response missing')
local _,clock=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
local now=clock():GetCurrentServerTime()*1000
assert(type(heroes[3])=='number' and math.abs(now-heroes[3])<15000, 'Hero server snapshot is too old')
local hero
local list=heroes[2][2][1]
for i=0,list:get_Count()-1 do local h=list:get_Item(i);if h[1][3]==303 then hero=h end end
assert(hero and hero[2]==0 and hero[3]-now>5000, 'Xishi is not idle-with-cooldown; no test sent')
assert(main:getMyArmyInfoByHeroGroupId(303)==nil, 'Xishi is already assigned to an active army')
local choice
for i=0,scene._chooseData:get_Count()-1 do
 local entry=scene._chooseData:get_Item(i)
 if entry.availHero[1][1][3]==303 then choice=entry end
end
assert(choice and choice.actionState==5, 'Xishi is not marked recovering in selection data')
local soldiers=scene:getSoldierInfoList()
assert(soldiers:get_Count()==0, 'Unexpected follower troops; no request sent')
assert(scene._heroCpList==nil or scene._heroCpList:get_Count()==0, 'Unexpected extra heroes; no request sent')
local fn=package.loaded.SLGChooseHeroLogicMonster.__instanceDict.startTrip2
local n1,tripType=debug.getupvalue(fn,1)
local n2,armyType=debug.getupvalue(fn,2)
assert(n1=='T_TSLGStartArmyTripReq' and n2=='T_TMakeArmyReq', 'Trip constructors changed')
local req=CSLNew(tripType)
local army=CSLNew(armyType)
army[1]=303;army[2]=soldiers
req[1]=army
req[2]=content[3]
req[3]=content[5]
req[4]=content[2]
req[5]=scene._logic:getTargetID2()
req[6]=scene._heroCpList
req[7]=0
assert(req[5]==0, 'Unexpected monster secondary target')
local stock=manager:getModel(CSLTypes.ItemsModel):getItemCount(70291)
-- Persist the at-most-once marker before submission, including if the sender subsequently throws.
REA_COOLDOWN_TRIP_TEST_SENT={hero=303,target=148532,server_ms=now,remaining_ms=hero[3]-now}
package.loaded.SLGMainController.__instanceDict.sendTSLGStartArmyTripReq(req)
return string.format('{"sent_once":true,"protocol":11010,"hero":303,"target":148532,"monster_config":100401,"cooldown_ms":%.0f,"recovery_items_before":%d,"followers":0}',hero[3]-now,stock)
