-- Read cached resource objects only; no view refresh, resource query or dispatch is sent.
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local cache=map.mInViewDataChunkCacheManager
local out={}
local list=cache:getAllViewData()
out[#out+1]='CHUNK_LIST_COUNT '..list:get_Count()
out[#out+1]='CHUNK_LIMIT '..tostring(cache.CACHE_CHUNK_NUM)
out[#out+1]='DICT_COUNT '..tostring(cache.mDataChunkDic:get_Count())
local resources={}
for i=0,list:get_Count()-1 do
 local chunk=list:get_Item(i)
 local views=chunk.mViewDataCache
 out[#out+1]='CHUNK '..tostring(chunk.chunkIndexPosKey)..' TYPES '..views:get_Count()..' GET_KEYS '..type(views.GetDictKeys)
 if views:ContainsKey(1000) then
  local points=views:get_Item(1000)
  local keys=points:GetDictKeys()
  out[#out+1]='RESOURCE_POINTS '..points:get_Count()..' KEYS '..keys:get_Count()
  for j=0,keys:get_Count()-1 do
   local pos=keys:get_Item(j)
   local point=points:get_Item(pos)
   resources[#resources+1]={key=pos,data=point}
  end
 end
end
out[#out+1]='TOTAL_CACHED_RESOURCE_POINTS '..#resources
for i=1,math.min(#resources,3) do
 local row=resources[i]
 out[#out+1]='POINT key='..tostring(row.key)..' x='..CSLTypes.SLGMapUtils.keyToPosX(row.key)..' y='..CSLTypes.SLGMapUtils.keyToPosY(row.key)
 for k,v in pairs(row.data) do
  if type(k)=='number' then
   if type(v)=='number' or type(v)=='string' then out[#out+1]='FIELD '..k..'='..tostring(v)
   elseif type(v)=='table' then
    out[#out+1]='FIELD '..k..' table'
    for n=1,12 do local x=rawget(v,n);if type(x)=='number' then out[#out+1]='FIELD '..k..'.'..n..'='..tostring(x) end end
    if v.get_Count then out[#out+1]='LIST '..k..' count='..v:get_Count() end
   end
  end
 end
end
return table.concat(out,'\n')
