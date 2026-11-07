-- Inspect return/state handlers and protocol constants; never invoke a request or action.
local util=require('jit.util')
local out={}
for _,entry in ipairs({{'SLGMainModel','updateMyActionState'},{'SLGMainModel','setMyActionState'},
 {'SLGMainModel','updateMyArmyInActionState'},{'SLGMainController','parseTSLGArmyStatusNotify'},
 {'SLGMainController','parseTSLGRetreatArmyRsp'},{'SLGMainController','sendTSLGGetAllArmyReq'}}) do
 local fn=package.loaded[entry[1]].__instanceDict[entry[2]]
 out[#out+1]='FUNCTION '..entry[1]..'.'..entry[2]..' '..type(fn)
 if type(fn)=='function' then
  for i=-1,-90,-1 do
   local value=util.funck(fn,i);if value==nil then break end
   if type(value)=='string' then out[#out+1]='K '..(-i-1)..' '..value end
  end
  for i=1,15 do
   local key,value=debug.getupvalue(fn,i);if not key then break end
   out[#out+1]='UP '..i..' '..key..' '..type(value)
   if type(value)=='table' and (key=='T_ID' or key:find('STATE')) then
    for k,v in pairs(value) do if type(k)=='string' and k:find('ARMY') and type(v)=='number' then out[#out+1]=k..'='..v end end
   end
  end
  for pc=1,util.funcinfo(fn).bytecodes-1 do
   local bc=util.funcbc(fn,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end
return table.concat(out,'\n')
