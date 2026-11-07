-- Confirm how the native quick-combat result selects its win/loss dialog.
local out={};local u=require('jit.util');local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local r=m._lastSLGSitdown
if r and r[2]==152468 and r[3]==154777 then
 for k,v in pairs(r) do
  if type(v)=='number' or type(v)=='boolean' then out[#out+1]='RESULT '..k..' '..tostring(v) end
 end
end
local f=package.loaded.SLGSitdownPromptDialog.__instanceDict.updateSelf
for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
for pc=1,math.min(130,u.funcinfo(f).bytecodes-1) do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
return table.concat(out,'\n')
