-- Inspect native soldier-capacity predicates and mappings without training or mutation.
local util=require('jit.util');local out={}
for _,name in ipairs({'TrainSoldierUIData','SoldierTrainingNewDialog','BarracksArmItem'}) do
 local methods=package.loaded[name].__instanceDict
 for k,f in pairs(methods) do
  if type(f)=='function' and util.funcinfo(f).bytecodes then
   local keys={};for i=-1,-100,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then keys[#keys+1]=v end end
   out[#out+1]='METHOD '..name..'.'..tostring(k)..' '..table.concat(keys,'|')
   if name=='TrainSoldierUIData' or k:lower():find('train') or k=='updateUI' then
    for i=0,30 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
    for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
   end
  end
 end
end
return table.concat(out,'\n')
