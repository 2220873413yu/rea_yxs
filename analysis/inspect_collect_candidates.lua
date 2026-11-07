-- Rank cached resource candidates with the game's own hex distance; do not issue queries or trips.
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local main=manager:getModel(CSLTypes.SLGMainModel)
local cache=map.mInViewDataChunkCacheManager
local search=CSLTypes.DBSearcher.sharedInstance()
local home=map:getMyMainCityCoordinates()
local util=CSLTypes.SLGMapUtils
local points={}
local unique={}
local chunks=cache:getAllViewData()
for i=0,chunks:get_Count()-1 do
 local data=chunks:get_Item(i).mViewDataCache
 if data:ContainsKey(1000) then
  local dict=data:get_Item(1000)
  local keys=dict:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local key=keys:get_Item(j)
   if not unique[key] then
    unique[key]=true
    local obj=dict:get_Item(key)
    local config=search:searchTNewPlay_Resource_Map(obj[2])
    local pos=util.keyToPos(key)
    local display=util.logicToDisplay(pos)
    points[#points+1]={x=pos[1],y=pos[2],kind=config[3],level=config[2],
     display_x=display[1] or display.x,display_y=display[2] or display.y,
     name=CSLTypes.YXSUtils.GBK2UTF8(config[4]),id=obj[1][2],config=obj[2],
     qty=obj[6],armies=obj[4]:get_Count(),distance=util.calMapP2PDistance(home,pos)}
   end
  end
 end
end
table.sort(points,function(a,b) if a.distance==b.distance then return a.id<b.id end;return a.distance<b.distance end)
local displayHome=util.logicToDisplay(home)
local out={'HOME '..home[1]..','..home[2]..' CACHE_POINTS '..#points,
 'DISPLAY_HOME '..tostring(displayHome[1] or displayHome.x)..','..tostring(displayHome[2] or displayHome.y),
 'COLLECTION_ARMY_LIMIT '..main:getMaxCollectionArmyCount(),
 'VIEW_RANGE '..tostring(CSLTypes.SLGMapObjectModel.RANGE_X)..','..tostring(CSLTypes.SLGMapObjectModel.RANGE_Y),
 'HOME_DISTANCE_VALUE '..util.calMapP2PDistance(home,home)}
local shown={}
local minX,maxX,minY,maxY=1e9,-1e9,1e9,-1e9
for _,p in ipairs(points) do minX=math.min(minX,p.x);maxX=math.max(maxX,p.x);minY=math.min(minY,p.y);maxY=math.max(maxY,p.y) end
out[#out+1]='CACHED_RESOURCE_BOUNDS_LOGIC '..minX..','..minY..' to '..maxX..','..maxY
for _,point in ipairs(points) do
 local count=shown[point.kind] or 0
 if count<3 then
  shown[point.kind]=count+1
  out[#out+1]=string.format('CANDIDATE %s level=%s logic=%s,%s display=%s,%s game_distance=%s id=%s cached_qty=%s cached_armies=%s config=%s',point.name,point.level,point.x,point.y,tostring(point.display_x),tostring(point.display_y),point.distance,point.id,point.qty,point.armies,point.config)
 end
end
local info=map:GetMapInfo()
for k,v in pairs(info) do if type(k)=='number' and type(v)=='number' then out[#out+1]='MAPCFG '..k..'='..v end end
return table.concat(out,'\n')
