-- Inspect cached server timestamps and native countdown readers without any game requests.
local out={}
local util=require('jit.util')
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local _,clock=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
out[#out+1]='SERVER_NOW_MS '..string.format('%.0f',clock():GetCurrentServerTime()*1000)
local function fields(label,row,depth)
 local keys={}
 for k,v in pairs(row) do if type(k)=='number' then keys[#keys+1]=k end end
 table.sort(keys)
 for _,k in ipairs(keys) do
  local v=row[k]
  if type(v)=='number' then out[#out+1]=label..'['..k..']='..string.format('%.0f',v)
  elseif type(v)=='table' and depth>0 and not v.get_Count then fields(label..'['..k..']',v,depth-1) end
 end
end
local list=main._myActionState[2]
for i=0,list:get_Count()-1 do fields('ARMY'..i,list:get_Item(i),2) end
for _,name in ipairs({'SLGMyMapArmyInfo','SLGMapArmyInfo','SLGStateItemArmyLogic','SLGArmyTripModel',
 'SLGResourceHeroItem','SLGResourceCommonDialog','SLGMonsterArmyItem','SLGMapArmy'}) do
 local cls=package.loaded[name]
 local methods=type(cls)=='table' and cls.__instanceDict
 out[#out+1]='MODULE '..name..' '..type(methods)
 if methods then
  local keys={}
  for key,fn in pairs(methods) do
   if type(key)=='string' and type(fn)=='function' and (key:find('Time') or key:find('Update') or key:find('update') or key:find('Collect') or key:find('initialize')) then keys[#keys+1]=key end
  end
  table.sort(keys)
  for _,key in ipairs(keys) do
   local fn=methods[key];local constants={}
   for j=-1,-120,-1 do
    local value=util.funck(fn,j);if value==nil then break end
    if type(value)=='string' then constants[#constants+1]=value end
   end
   out[#out+1]='METHOD '..name..'.'..key..' '..table.concat(constants,'|')
  end
 end
end
return table.concat(out,'\n')
