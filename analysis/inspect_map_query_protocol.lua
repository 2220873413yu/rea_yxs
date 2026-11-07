-- Inspect native view-query construction and cache consumers; do not send requests or move the camera.
local util=require('jit.util');local out={}
local function dump(name,f,full)
 out[#out+1]='FUNCTION '..name..' params='..tostring(util.funcinfo(f).params)
 for i=-1,-160,-1 do local v=util.funck(f,i);if v==nil then break end
  out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v)
 end
 for i=0,25 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,20 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v)
  if n=='T_ID' then for k,x in pairs(v) do if tostring(k):find('VIEW') then out[#out+1]='ID '..k..'='..x end end end
 end
 if full then for pc=1,math.min(350,util.funcinfo(f).bytecodes-1) do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end end
end
for name,cls in pairs(package.loaded) do
 local m=type(cls)=='table' and cls.__instanceDict
 if type(m)=='table' then for k,f in pairs(m) do
  if type(f)=='function' and util.funcinfo(f).bytecodes then
   local matched,caller=false,false
   for i=-1,-130,-1 do local v=util.funck(f,i);if v==nil then break end
    if v=='sendTSLGViewInfoReq' or v=='parseTSLGViewInfoRsp' or v=='mInViewDataChunkCacheManager' then matched=true end
    if v=='sendTSLGViewInfoReq' then caller=true end
   end
   if matched or (name=='SLGMainController' and (k=='sendTSLGViewInfoReq' or k=='parseTSLGViewInfoRspCoroutine')) or name=='InViewDataChunkCacheManager' then
    dump(name..'.'..k,f,k=='sendTSLGViewInfoReq' or (caller and k~='initialize') or k=='parseTSLGViewInfoRsp')
   end
  end
 end end
end
return table.concat(out,'\n')
