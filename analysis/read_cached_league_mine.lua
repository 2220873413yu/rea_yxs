-- Read the verified5002 league-mine cache and native ownership fields, not the unrelated1012 map objects.
local out={};local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel);local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local own=main:getMyLeagueId()
local function walk(prefix,t,depth)
 if depth>3 then return end
 for k,v in pairs(t) do
  if type(k)=='number' then
   if type(v)=='number' then out[#out+1]=prefix..'.'..k..'='..v
   elseif type(v)=='table' and not v.get_Count then walk(prefix..'.'..k,v,depth+1)
   elseif type(v)=='table' and v.get_Count then out[#out+1]=prefix..'.'..k..' COUNT='..v:get_Count() end
  end
 end
end
local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
for i=0,chunks:get_Count()-1 do
 local c=chunks:get_Item(i).mViewDataCache
 if c:ContainsKey(5002) then
  local points=c:get_Item(5002);local keys=points:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local key=keys:get_Item(j);local p=points:get_Item(key)
   walk('POINT '..key,p,0)
  end
 end
end
return table.concat(out,'\n')
