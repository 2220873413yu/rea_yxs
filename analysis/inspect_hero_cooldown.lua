-- Research only: inspect loaded declarations and constants without sending game commands.
local out={}
local util=require("jit.util")
local names={"HeroPalaceItem","HeroPalaceDialog","HeroPalaceUIData","SLGHeroItem","SLGBuildingsController","SLGHeroModel","SLGArmyModel","SLGArmyTripModel"}
for _,name in ipairs(names) do
 local class=package.loaded[name]
 out[#out+1]="MODULE "..name.."="..type(class)
 if type(class)=="table" then
  local methods=rawget(class,"__instanceDict") or class
  local keys={}
  for key,value in pairs(methods) do
   if type(key)=="string" and type(value)=="function" then
    if name~="SLGBuildingsController" or string.find(key,"Speed") or string.find(key,"Hero") then keys[#keys+1]=key end
   end
  end
  table.sort(keys)
  for _,key in ipairs(keys) do
   local fn=methods[key]
   local info=util.funcinfo(fn)
   out[#out+1]="METHOD "..key.." params="..tostring(info.params).." bc="..tostring(info.bytecodes)
   if name=="HeroPalaceItem" or string.find(key,"Speed") then
    local constants={}
    for i=-1,-65,-1 do
     local value=util.funck(fn,i)
     if value==nil then break end
     if type(value)=="string" then constants[#constants+1]=i.."="..value end
    end
    out[#out+1]="CONST "..table.concat(constants," | ")
   end
  end
 end
end
return table.concat(out,"\n")
