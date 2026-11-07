local u=require("jit.util")
local out={}
for _,name in ipairs({"sendTSLGTrainSoldierReq","sendTSLGBuildSpeedupReq"}) do
 local fn=package.loaded.SLGBuildingsController.__instanceDict[name]
 out[#out+1]=name
 local info=u.funcinfo(fn)
 for pc=1,info.bytecodes-1 do
  local bc=u.funcbc(fn,pc)
  local op=bc%256
  out[#out+1]=string.format("%d OP=%d A=%d B=%d C=%d D=%d",pc,op,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
for _, name in ipairs({"ModelManager","CSLTypes","MainModel","SLGBuildingsModel","ItemsModel"}) do
 local v=rawget(_G,name) or package.loaded[name]
 out[#out+1]=name..":"..type(v)
 if type(v)=="table" then
  local keys={}
  for k,x in pairs(rawget(v,"__instanceDict") or v) do
   if type(k)=="string" and (name~="CSLTypes" or string.find(k,"Model")) then keys[#keys+1]=k..":"..type(x) end
  end
  table.sort(keys);out[#out+1]=table.concat(keys,",")
 end
end
return table.concat(out,"\n")
