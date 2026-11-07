-- Inspect native status translation helpers, without calling UI lifecycle or game actions.
local out={};local util=require('jit.util')
for _,module in ipairs({'HeroPalaceItem','HeroPalaceUIData','SLGChooseHeroItem'}) do
 local dict=package.loaded[module].__instanceDict
 for _,key in ipairs({'UpdateItem','updateActionState'}) do
  local fn=dict[key]
  if type(fn)=='function' then
   out[#out+1]='FUNCTION '..module..'.'..key
   for i=1,18 do
    local name,value=debug.getupvalue(fn,i);if not name then break end
    out[#out+1]='UP '..i..' '..name..' '..type(value)
    if type(value)=='function' and name:find('fill') then
     for j=-1,-100,-1 do local v=util.funck(value,j);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-j-1)..' '..v end end
     for j=0,40 do local v=util.funck(value,j);if v==nil then break end;out[#out+1]='N '..j..' '..tostring(v) end
     for pc=1,util.funcinfo(value).bytecodes-1 do local bc=util.funcbc(value,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
    end
   end
   if key=='updateActionState' then
    for i=-1,-70,-1 do local v=util.funck(fn,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
    for i=0,25 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
    for pc=1,util.funcinfo(fn).bytecodes-1 do local bc=util.funcbc(fn,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
   end
  end
 end
end
return table.concat(out,'\n')
