-- Inspect map cache structures, resource details and distance helpers without network or UI actions.
local util=require('jit.util')
local out={}
for _,name in ipairs({'InViewDataChunkCacheManager','InViewDataChunkCache','SLGMapResource','SLGMapResourceInfo','SLGResourceCommonDialog','SLGMapUtils'}) do
 local cls=package.loaded[name]
 local methods=type(cls)=='table' and (cls.__instanceDict or cls)
 out[#out+1]='MODULE '..name..' '..type(methods)
 if methods then
  local keys={};for k,v in pairs(methods) do if type(k)=='string' and type(v)=='function' then keys[#keys+1]=k end end;table.sort(keys)
  for _,key in ipairs(keys) do
   local f=methods[key]
   local constants={}
   for i=-1,-80,-1 do local c=util.funck(f,i);if c==nil then break end;if type(c)=='string' and not string.find(c,'[\128-\255]') then constants[#constants+1]=c end end
   out[#out+1]='METHOD '..key..' params='..util.funcinfo(f).params..' CONST '..table.concat(constants,'|')
  end
 end
end
local ctrl=package.loaded.SLGMainController.__instanceDict
for key,f in pairs(ctrl) do
 if type(key)=='string' and type(f)=='function' and (string.find(key,'View') or string.find(key,'Near') or string.find(key,'Map') or string.find(key,'Search')) then
  out[#out+1]='MAIN_METHOD '..key..' params='..util.funcinfo(f).params
 end
end
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local home=map:getMyMainCityCoordinates()
out[#out+1]='HOME x='..tostring(home[1])..' y='..tostring(home[2])
local cache=map.mInViewDataChunkCacheManager
for k,v in pairs(cache) do if type(k)=='string' then out[#out+1]='MANAGER_FIELD '..k..' '..type(v) end end
local chunks=cache.mDataChunkDic
if type(chunks)=='table' then
 local keys={}
 if chunks.get_Count then
  local set=chunks:get_Keys()
  if set.get_Count then for i=0,set:get_Count()-1 do keys[#keys+1]=set:get_Item(i) end
  else for _,key in pairs(set) do if type(key)=='number' or type(key)=='string' then keys[#keys+1]=key end end end
 else for key in pairs(chunks) do keys[#keys+1]=key end end
 out[#out+1]='CHUNKS '..#keys
 for i=1,math.min(#keys,2) do
  local chunk=chunks.get_Item and chunks:get_Item(keys[i]) or chunks[keys[i]]
  out[#out+1]='CHUNK '..tostring(keys[i])
  if type(chunk)=='table' then for k,v in pairs(chunk) do if type(k)=='string' then out[#out+1]='CHUNK_FIELD '..k..' '..type(v) end end end
 end
end
return table.concat(out,'\n')
