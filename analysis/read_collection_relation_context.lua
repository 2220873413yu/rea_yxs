-- Read local map relationship context without network requests or model changes.
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local mine=map:getMyMainCityDetailInfo()[2][5]
local encode=REA_AUTO_INFANTRY.encode_flat_state
local out={}
local seen={}
local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
for i=0,chunks:get_Count()-1 do
 local chunk=chunks:get_Item(i).mViewDataCache
 if chunk:ContainsKey(1000) then
  local points=chunk:get_Item(1000);local keys=points:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local p=points:get_Item(keys:get_Item(j));local league=p[3]
   if type(league)=='number' and not seen[league] then
    seen[league]=true
    out[#out+1]=encode({same=main.IsSameLeague(league),allied=main.IsAllyLeague(league),enemy=main.isEnemyLeague(league)})
   end
  end
 end
end
return '{"signed_map_type":'..tostring(main:getSignedMapTypeID())..',"loaded_owner_relationships":['..table.concat(out,',')..']}'
