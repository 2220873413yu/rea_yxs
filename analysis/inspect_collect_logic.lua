-- Read loaded collection/map methods and cache declarations only. No senders are invoked.
local util=require('jit.util')
local out={}
local names={'SLGChooseHeroLogicCollectResource','SLGChooseHeroLogicLeagueCollect','SLGMapObjectModel','SLGCityModel','SLGMainController','SLGMainModel','SLGChooseHeroScene'}
local function relevant(name,key)
 if name=='SLGChooseHeroLogicCollectResource' or name=='SLGChooseHeroLogicLeagueCollect' then return true end
 for _,part in ipairs({'Resource','Collect','Near','Pos','Distance','MainCity','Field','Grid','CostSecond','MoveSpeed','AvailHero','Search'}) do
  if string.find(key,part) then return true end
 end
 return false
end
for _,name in ipairs(names) do
 local cls=package.loaded[name]
 local methods=type(cls)=='table' and (cls.__instanceDict or cls)
 out[#out+1]='MODULE '..name..' '..type(methods)
 if methods then
  local keys={}
  for k,v in pairs(methods) do if type(k)=='string' and type(v)=='function' and relevant(name,k) then keys[#keys+1]=k end end
  table.sort(keys)
  for _,key in ipairs(keys) do
   local f=methods[key]
   local constants={}
   for i=-1,-90,-1 do
    local value=util.funck(f,i)
    if value==nil then break end
    if type(value)=='string' and not string.find(value,'[\128-\255]') then
     constants[#constants+1]=value
    end
   end
   out[#out+1]='METHOD '..key..' params='..util.funcinfo(f).params..' CONST '..table.concat(constants,'|')
  end
 end
end
local manager=CSLTypes.ModelManager.sharedInstance()
for _,name in ipairs({'SLGMapObjectModel','SLGCityModel'}) do
 local model=manager:getModel(CSLTypes[name])
 out[#out+1]='CACHE '..name
 for k,v in pairs(model) do if type(k)=='string' then out[#out+1]='FIELD '..k..' '..type(v) end end
end
return table.concat(out,'\n')
