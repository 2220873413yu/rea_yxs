-- Identify result and tower status consumers by declarations/constants, never invoke handlers.
local out={};local u=require('jit.util')
for name,cls in pairs(package.loaded)do
 if type(cls)=='table' and (name=='SLGMainController' or name=='SLGMainModel' or name=='GameMsgMgr' or name=='SLGResultLostScene' or name:find('ResultWin') or name=='SLGTowerModel')then
  for k,v in pairs(cls.__instanceDict or cls)do
   if type(k)=='string' and type(v)=='function'then
    if k:find('Result') or k:find('End') or k:find('Battle') or k:find('Over') or k:find('SkipTime')then out[#out+1]='METHOD '..name..'.'..k end
    if u.funcinfo(v).bytecodes then
     for i=-1,-150,-1 do local s=u.funck(v,i);if s==nil then break end
      if type(s)=='string' and (s:find('SLGTower') or s:find('TSLGPVEResult') or s:find('QCT') or s:find('bWin'))then out[#out+1]='LINK '..name..'.'..k..' '..s end
     end
    end
   end
  end
 end
end
return table.concat(out,'\n')
