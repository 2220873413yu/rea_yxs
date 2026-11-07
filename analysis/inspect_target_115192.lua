-- Locate exactly the user-specified point and inspect fog ownership without changing visibility.
local out={};local u=require('jit.util');local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
local found=0
for i=0,chunks:get_Count()-1 do
 local c=chunks:get_Item(i).mViewDataCache
 if c:ContainsKey(3000) then
  local ps=c:get_Item(3000);local keys=ps:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local p=ps:get_Item(keys:get_Item(j));local pos=p[1][1];local d=CSLTypes.SLGMapUtils.logicToDisplay(pos)
   if d[1]==115 and d[2]==192 then
    found=found+1;out[#out+1]='TARGET id='..p[1][2]..' config='..p[2]..' logic='..pos[1]..','..pos[2]
   end
  end
 end
end
out[#out+1]='FOUND '..found
local center=map.screenCenter;out[#out+1]='CENTER '..center[1]..','..center[2]
for _,name in ipairs({'SLGWarFogModel','SLGMainController'}) do
 for key,f in pairs(package.loaded[name].__instanceDict) do
  if type(key)=='string' and type(f)=='function' and u.funcinfo(f).bytecodes and
   (name=='SLGWarFogModel' or key:find('Scout') or key:find('Fog')) then
   local keys={}
   for i=-1,-90,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' and not v:find('[\128-\255]') then keys[#keys+1]=v end end
   out[#out+1]='METHOD '..name..'.'..key..' params='..u.funcinfo(f).params..' '..table.concat(keys,'|')
  end
 end
end
local fog=manager:getModel(CSLTypes.SLGWarFogModel)
local ok,v=pcall(function() return fog:isCellVisible(115,58,0) end)
out[#out+1]='FOG_VISIBLE '..tostring(ok)..' '..tostring(v)
return table.concat(out,'\n')
