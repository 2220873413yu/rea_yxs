-- Read-only research: dump selected function metadata, not account/session data.
local out={}
local util=require("jit.util")
local targets={
 {"HeroPalaceItem","_Awake_b__27_0"},
 {"HeroPalaceItem","Update"},
 {"HeroPalaceUIData","initialize"},
 {"HeroPalaceDialog","initHeroList"},
 {"HeroPalaceDialog","updateSelf"},
 {"AccDlgUIData","initialize"},
 {"UpgradeAccelerationNewDialog","canUseAccItemFilter"},
 {"UpgradeAccelerationNewDialog","useButtonCallback"},
 {"SLGBuildingsController","parseTSLGBuildSpeedupRsp"},
 {"SLGBuildingsController","sendSpeedupAttackCDTimeReq"}
}
for _,target in ipairs(targets) do
 local class=package.loaded[target[1]]
 local dict=type(class)=="table" and rawget(class,"__instanceDict")
 local fn=dict and dict[target[2]]
 out[#out+1]="FUNCTION "..target[1].."."..target[2]..":"..type(fn)
 if type(fn)=="function" then
  local info=util.funcinfo(fn)
  out[#out+1]="INFO params="..tostring(info.params)..",bytecodes="..tostring(info.bytecodes)
  for i=-1,-100,-1 do
   local v=util.funck(fn,i)
   if v==nil then break end
   if type(v)=="string" or type(v)=="number" then out[#out+1]="K "..i.." "..tostring(v)
   elseif type(v)=="table" then
    local a={}
    for k,x in pairs(v) do if type(x)=="number" or type(x)=="string" or type(x)=="boolean" then a[#a+1]=tostring(k).."="..tostring(x) end end
    table.sort(a);out[#out+1]="KT "..i.." "..table.concat(a,",")
   end
  end
  if target[1]=="HeroPalaceItem" or target[1]=="AccDlgUIData" or target[2]=="canUseAccItemFilter" or target[2]=="sendSpeedupAttackCDTimeReq" then
   for pc=1,info.bytecodes-1 do
    local bc=util.funcbc(fn,pc)
    out[#out+1]=string.format("BC %d OP=%d A=%d B=%d C=%d D=%d",pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
   end
  end
 end
end
local main=package.loaded.SLGMainModel.__instanceDict
for k,v in pairs(main) do
 if type(k)=="string" and type(v)=="function" and (string.find(k,"Hero") or string.find(k,"Recover") or string.find(k,"AttackCD")) then
  local info=util.funcinfo(v)
  out[#out+1]="MAIN "..k.." params="..tostring(info.params)..",bytecodes="..tostring(info.bytecodes)
 end
end
return table.concat(out,"\n")
