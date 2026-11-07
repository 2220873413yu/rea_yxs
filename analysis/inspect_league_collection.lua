-- Read native league-resource classes, query identifiers and cached structures; never invoke a sender.
local out={};local u=require('jit.util')
for _,name in ipairs({'SLGChooseHeroLogicLeagueCollect','SLGChooseHeroLogicLeagueWorkShopCollect',
 'SLGLeagueModel','SLGLeagueController','LeagueResourceBuildingDialog'}) do
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 if type(cls)~='table' then local ok,v=pcall(require,name);if ok then cls=v end end
 out[#out+1]='MODULE '..name..' '..type(cls)
 local methods=type(cls)=='table' and cls.__instanceDict
 if type(methods)=='table' then
  for key,f in pairs(methods) do
   if type(key)=='string' and type(f)=='function' and u.funcinfo(f).bytecodes and
    (name:find('ChooseHero') or name=='LeagueResourceBuildingDialog' or key:lower():find('resource') or key:lower():find('collect')) then
    local keys={}
    for i=-1,-110,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then keys[#keys+1]=v end end
    out[#out+1]='METHOD '..name..'.'..key..' params='..u.funcinfo(f).params..' '..table.concat(keys,'|')
    for j=1,12 do
     local n,v=debug.getupvalue(f,j);if not n then break end
     if n=='T_ID' then for a,b in pairs(v) do if tostring(a):find('RESOURCE') or tostring(a):find('COLLECT') then out[#out+1]='PROTOCOL '..a..' '..tostring(b) end end end
    end
   end
  end
 end
end
for name in pairs(package.loaded) do
 if type(name)=='string' and (name:find('LeagueResource') or name:find('LeagueCollect')) then out[#out+1]='LOADED '..name end
end
local manager=CSLTypes.ModelManager.sharedInstance()
local m=manager:getModel(CSLTypes.SLGLeagueModel)
for k,v in pairs(m) do if type(k)=='string' and (k:lower():find('resource') or k:lower():find('collect')) then
 out[#out+1]='CACHE '..k..' '..type(v)
 if type(v)=='table' and v.get_Count then out[#out+1]='COUNT '..k..' '..v:get_Count() end
end end
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local chunks=map.mInViewDataChunkCacheManager:getAllViewData();local counts={}
for i=0,chunks:get_Count()-1 do
 local c=chunks:get_Item(i).mViewDataCache
 for _,kind in ipairs({1000,3000,5000,6000,7000,8000,9000,10000,11000,12000,13000,14000,15000,16000,20000}) do
  if c:ContainsKey(kind) then local p=c:get_Item(kind);counts[kind]=(counts[kind] or 0)+p:GetDictKeys():get_Count() end
 end
end
for k,v in pairs(counts) do out[#out+1]='MAP_TYPE '..k..' '..v end
return table.concat(out,'\n')
