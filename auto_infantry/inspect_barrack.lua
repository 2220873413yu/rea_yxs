local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGBuildingsModel)
local rsp=m:getTSLGGetBarrackRsp()
local out={"rsp="..type(rsp),"same="..tostring(rsp==m._stTSLGGetBarrackRsp)}
local seen={}
local function dump(v,p,depth)
 if type(v)~="table" then out[#out+1]=p.."="..tostring(v);return end
 if seen[v] then out[#out+1]=p.."=<seen>";return end
 seen[v]=true
 local n=0
 for k,x in pairs(v) do
  n=n+1;if n>35 then break end
  local q=p.."."..tostring(k)
  if type(x)=="table" and depth>0 then dump(x,q,depth-1)
  elseif type(x)=="number" or type(x)=="boolean" then out[#out+1]=q.."="..tostring(x)
  else out[#out+1]=q..":"..type(x) end
 end
end
dump(rsp,"rsp",4)
return table.concat(out,"\n")
