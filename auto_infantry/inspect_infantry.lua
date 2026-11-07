local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGBuildingsModel)
local rsp=m:getTSLGGetBarrackRsp()
local out={}
local function dump(v,p,depth)
 if type(v)~="table" then out[#out+1]=p.."="..tostring(v);return end
 for k,x in pairs(v) do
  if type(k)=="number" then
   local q=p.."["..k.."]"
   if type(x)=="table" and depth>0 then dump(x,q,depth-1)
   elseif type(x)=="number" or type(x)=="boolean" then out[#out+1]=q.."="..tostring(x)
   else out[#out+1]=q..":"..type(x) end
  end
 end
end
local data=rsp[4]:get_Item(411)
dump(data,"infantry",4)
local u=require("jit.util")
local fn=package.loaded.UpgradeAccelerationNewDialog.__instanceDict.useButtonCallback
for i=1,10 do
 local name,v=debug.getupvalue(fn,i)
 if not name then break end
 out[#out+1]="upvalue="..i..":"..name..":"..type(v)..":"..(type(v)=="userdata" and tostring(v) or "")
end
for pc=1,46 do
 local bc=u.funcbc(fn,pc)
 if not bc then break end
 out[#out+1]=string.format("%d OP=%d A=%d B=%d C=%d D=%d",pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
end
return table.concat(out,"\n")
