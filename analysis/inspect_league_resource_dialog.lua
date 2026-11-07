-- Inspect league-mine permission/capacity/query rules and cached building lists without sending requests.
local out={};local u=require('jit.util')
for _,name in ipairs({'SLGLeagueResCommonDialog','SLGLeagueWorkShopDialog'}) do
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 if type(cls)~='table' then local ok,v=pcall(require,name);if ok then cls=v end end
 out[#out+1]='MODULE '..name..' '..type(cls)
 if type(cls)=='table' then for k,f in pairs(cls.__instanceDict) do
  if type(k)=='string' and type(f)=='function' and u.funcinfo(f).bytecodes and
   not (k:find('LuaBehaviour') or k:find('Coroutine') or k:find('Bindings') or k:find('__') or k:find('Stage') or k=='getDebugID' or k=='IsAlive') then
   local keys={};for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then keys[#keys+1]=v end end
   out[#out+1]='METHOD '..name..'.'..k..' params='..u.funcinfo(f).params..' '..table.concat(keys,'|')
  end
 end end
end
local manager=CSLTypes.ModelManager.sharedInstance();local league=manager:getModel(CSLTypes.SLGLeagueModel)
for _,method in ipairs({'getTSLGLeagueGetAllBuildRsp','getTSLGLeagueGetResourceRsp'}) do
 local ok,r=pcall(league[method],league);out[#out+1]='CACHE '..method..' '..tostring(ok)..' '..type(r)
 if ok and type(r)=='table' then for k,v in pairs(r) do
  if type(v)=='number' then out[#out+1]='SCALAR '..method..'.'..k..' '..v
  elseif type(v)=='table' then
   local n=v.get_Count and v:get_Count() or 0;out[#out+1]='CONTAINER '..method..'.'..k..' count='..n
   if v.get_Item then for i=0,math.min(n,6)-1 do
    local ok1,p=pcall(v.get_Item,v,i)
    if ok1 and type(p)=='table' then for a,b in pairs(p) do if type(b)=='number' then out[#out+1]='ENTRY '..method..'.'..k..'.'..i..'.'..a..' '..b end end end
   end end
  end
 end end
end
local map=manager:getModel(CSLTypes.SLGMapObjectModel);local chunks=map.mInViewDataChunkCacheManager:getAllViewData();local counts={}
for i=0,chunks:get_Count()-1 do
 local c=chunks:get_Item(i).mViewDataCache
 if c.GetDictKeys then
  local ks=c:GetDictKeys()
  for j=0,ks:get_Count()-1 do local k=ks:get_Item(j);local p=c:get_Item(k);counts[k]=(counts[k] or 0)+p:GetDictKeys():get_Count() end
 end
end
for k,v in pairs(counts) do out[#out+1]='MAP_TYPE '..k..' '..v end
return table.concat(out,'\n')
