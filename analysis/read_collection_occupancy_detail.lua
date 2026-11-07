-- Read temporary query objects; do not modify models, predicates, inventory or requests.
local api=assert(REA_FOURTH_PROBE)
local detail
for i=1,30 do local n,v=debug.getupvalue(api.collect_status,i);if n=='detail' then detail=v;break end end
assert(detail,'Resource detail missing')
local point=detail[2][1]
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local search=CSLTypes.DBSearcher.sharedInstance()
local config=search:searchTNewPlay_Resource_Map(point[2])
local dialog=package.loaded.SLGResourceCommonDialog.__instanceDict
local native={mTSLGResourceInfoRsp=detail,mTNewPlay_Resource=config}
local rows={}
for i=0,detail[2][2]:get_Count()-1 do
 local army=detail[2][2]:get_Item(i)
 local actual=type(army[1])=='table' and army[1] or army
 local ok,own=pcall(main.checkIsMyArmy,actual)
 rows[#rows+1]=api.encode_flat_state({army_id=actual[1],own_check_known=ok,own=ok and own==true,state=actual[4],aim=actual[5]})
end
local ids={}
for i=0,point[4]:get_Count()-1 do ids[#ids+1]=tostring(point[4]:get_Item(i)) end
local base={capacity=config[9],occupied=detail[2][2]:get_Count(),point_armies=point[4]:get_Count(),
 own_present=main.isMyArmyExist_InResourceField(point),enemy_resource=main.isEnemyResourceField(point),
 owner_same_league=main.IsSameLeague(point[3]),owner_allied_league=main.IsAllyLeague(point[3]),
 owner_enemy_league=main.isEnemyLeague(point[3]),owner_league_id=point[3],can_collect=dialog.canCollect(native)}
-- Reevaluate this same native function using isolated copies with occupied-list sizes 0..capacity+1.
local matrix={}
for count=0,config[9]+1 do
 local copy={};for k,v in pairs(detail) do copy[k]=v end
 local field={};for k,v in pairs(detail[2]) do field[k]=v end
 local list=CSLNew(CSLTypes.CSLList)
 for j=1,count do list:Add({}) end
 field[2]=list;copy[2]=field
 matrix[#matrix+1]=api.encode_flat_state({occupied=count,can_collect=dialog.canCollect({mTSLGResourceInfoRsp=copy,mTNewPlay_Resource=config})})
end
local relations={}
local map=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMapObjectModel)
local myLeague=map:getMyMainCityDetailInfo()[2][5]
local nonOwnId=1
local myArmyIds={}
for _,index in ipairs({2,3}) do
 local armies=main._myActionState[index]
 for i=0,armies:get_Count()-1 do myArmyIds[armies:get_Item(i)[1]]=true end
end
while myArmyIds[nonOwnId] do nonOwnId=nonOwnId+1 end
-- Supply only isolated copies to pure eligibility predicates; no sender sees these objects.
for _,case in ipairs({{label='same_league',league=myLeague},{label='different_league',league=myLeague+1},
 {label='unclaimed',league=-1}}) do
 for count=0,config[9] do
  local copy={};for k,v in pairs(detail) do copy[k]=v end
  local field={};for k,v in pairs(detail[2]) do field[k]=v end
  local p={};for k,v in pairs(point) do p[k]=v end
  local list=CSLNew(CSLTypes.CSLList)
  local armyIds=CSLNew(CSLTypes.CSLList)
  for j=1,count do list:Add({});armyIds:Add(nonOwnId) end
  p[3]=case.league;p[4]=armyIds;field[1]=p;field[2]=list;copy[2]=field
  relations[#relations+1]=api.encode_flat_state({relation=case.label,occupied=count,
   same_league=main.IsSameLeague(p[3]),allied_league=main.IsAllyLeague(p[3]),
   enemy_resource=main.isEnemyResourceField(p),can_collect=dialog.canCollect({mTSLGResourceInfoRsp=copy,mTNewPlay_Resource=config})})
 end
end
return '{"facts":'..api.encode_flat_state(base)..',"occupying_armies":['..table.concat(rows,',')..
 '],"point_army_ids":['..table.concat(ids,',')..'],"isolated_capacity_matrix":['..table.concat(matrix,',')..
 '],"isolated_relation_matrix":['..table.concat(relations,',')..']}'
