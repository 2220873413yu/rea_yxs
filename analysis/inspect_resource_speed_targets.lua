-- Select equal-level comparison targets from existing cache only; do not query or dispatch.
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local home=map:getMyMainCityCoordinates()
local utils=CSLTypes.SLGMapUtils
local search=CSLTypes.DBSearcher.sharedInstance()
local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
local best={}
for i=0,chunks:get_Count()-1 do
 local cache=chunks:get_Item(i).mViewDataCache
 if cache:ContainsKey(1000) then
  local points=cache:get_Item(1000)
  local keys=points:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local posKey=keys:get_Item(j)
   local point=points:get_Item(posKey)
   local config=search:searchTNewPlay_Resource_Map(point[2])
   if config[2]==2 and (config[3]==1 or config[3]==2 or config[3]==3) then
    local pos=utils.keyToPos(posKey)
    local distance=utils.calMapP2PDistance(home,pos)
    if not best[config[3]] or distance<best[config[3]].distance then
     local display=utils.logicToDisplay(pos)
     best[config[3]]={id=point[1][2],x=display[1],y=display[2],kind=config[3],distance=distance,config=point[2]}
    end
   end
  end
 end
end
assert(best[3] and best[3].x==101 and best[3].y==191, 'Expected iron target changed')
local rows={}
for _,kind in ipairs({3,2,1}) do
 local p=assert(best[kind], 'Equal-level comparison target missing')
 rows[#rows+1]=string.format('{"id":%d,"kind":%d,"level":2,"x":%d,"y":%d,"config":%d}',p.id,p.kind,p.x,p.y,p.config)
end
return '['..table.concat(rows,',')..']'
