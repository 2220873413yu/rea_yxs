local out={}
local function keys(label,t)
 local a={}
 if type(t)=="table" then for k,v in pairs(t) do if type(k)=="string" then a[#a+1]=k..":"..type(v) end end end
 table.sort(a);while #a>100 do a[#a]=nil end;out[#out+1]=label.."="..table.concat(a,",")
end
local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGBuildingsModel)
local items=mm:getModel(CSLTypes.ItemsModel)
keys("model",m)
local rsp=m:getTSLGGetBarrackRsp()
keys("barrack",rsp)
keys("item-model",items)
local ok,n=pcall(function() return items:getItemCount(70251) end)
out[#out+1]="item_count="..tostring(ok)..":"..tostring(n)
for _,name in ipairs({"sendTSLGTrainSoldierReq","sendTSLGBuildSpeedupReq"}) do
 local fn=package.loaded.SLGBuildingsController.__instanceDict[name]
 for i=1,8 do
  local name,value=debug.getupvalue(fn,i)
  if not name then break end
  out[#out+1]="upvalue:"..name..":"..type(value)
 end
end
return table.concat(out,"\n")
