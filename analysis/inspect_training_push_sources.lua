-- Locate incoming world-change handlers and soldier notifications; do not call them.
local util=require('jit.util');local out={}
for name,cls in pairs(package.loaded) do
 local methods=type(cls)=='table' and cls.__instanceDict
 if type(methods)=='table' then for k,f in pairs(methods) do
  if type(f)=='function' and type(k)=='string' and util.funcinfo(f).bytecodes then
   local constants={};local match=false
   for i=-1,-150,-1 do
    local v=util.funck(f,i);if v==nil then break end
    if type(v)=='string' then
     constants[#constants+1]=v
     if v=='_stTSLGGetBarrackRsp' or v:find('SoldierNum') or
       (v:lower():find('notify') and (v:lower():find('train') or v:lower():find('soldier') or v:lower():find('barrack'))) then match=true end
    end
   end
   if (name=='SLGMainController' and (k:lower():find('notify') or k:lower():find('change'))) or match then
    out[#out+1]='FUNCTION '..name..'.'..k..' CONST '..table.concat(constants,'|')
   end
  end
 end end
end
local f=package.loaded.SLGBuildingsController.__instanceDict.initialize
for i=1,80 do local n,v=debug.getupvalue(f,i);if not n then break end
 if n=='T_ID' then for k,x in pairs(v) do if type(k)=='string' and
  (x==11003 or x==11089 or (k:find('SLG') and (k:find('NOTIFY') or k:find('CHANGE') or k:find('SOLDIER')))) then out[#out+1]='ID '..k..'='..x end end end
end
out[#out+1]='DELAY_FINISH_SECONDS '..tostring(CSLTypes.SLGBuildingsModel.DELAY_FINISH_SECONDS)
return table.concat(out,'\n')
