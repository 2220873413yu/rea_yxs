local out = {}
local ok, util = pcall(require, "jit.util")
out[#out+1] = "jit.util=" .. tostring(ok)
local targets = {
 {"SLGBuildingsController", "sendTSLGTrainSoldierReq"},
 {"SLGBuildingsController", "sendTSLGGetBarrackReq"},
 {"SLGBuildingsController", "sendTSLGBuildSpeedupReq"},
 {"SLGBuildingsController", "getInstance"},
 {"SLGBuildingsModel", "getTSLGGetBarrackRsp"},
 {"SLGBuildingsModel", "getTrainLeftTimeCacheMap1"},
 {"ItemsModel", "getItemCount"},
 {"UpgradeAccelerationNewDialog", "useButtonCallback"}
}
for _, t in ipairs(targets) do
 local fn = package.loaded[t[1]].__instanceDict[t[2]]
 out[#out+1] = t[1] .. "." .. t[2]
 if ok then
  local info = util.funcinfo(fn)
  out[#out+1] = "params="..tostring(info.params)..",slots="..tostring(info.stackslots)..",bytecodes="..tostring(info.bytecodes)
  local constants = {}
  for i=-1,-80,-1 do
   local v = util.funck(fn,i)
   if v == nil then break end
   if type(v) == "string" or type(v) == "number" then constants[#constants+1] = i.."="..tostring(v) end
  end
  out[#out+1] = table.concat(constants, ",")
 end
 local instance = package.loaded[t[1]].__instanceDict._instance
 if type(instance) == "table" then
  local keys={}
  for k,v in pairs(instance) do if type(k)=="string" then keys[#keys+1]=k..":"..type(v) end end
  table.sort(keys)
  out[#out+1]="instance="..table.concat(keys,",")
 end
end
return table.concat(out,"\n")
