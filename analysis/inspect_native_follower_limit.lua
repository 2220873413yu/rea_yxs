-- Read native formation construction and caps; do not submit any game action.
local out={};local u=require('jit.util')
for _,p in ipairs({{'SLGChooseHeroScene','updateSoldier'},{'SLGChooseHeroScene','createChosenSoldier'},
 {'SLGChosenSoldier','setMaxNum'},{'SLGChosenSoldier','setNum'},{'SLGChosenSoldier','setFreeNum'}}) do
 pcall(function() return CSLTypes[p[1]] end)
 local f=package.loaded[p[1]].__instanceDict[p[2]]
 out[#out+1]='FUNCTION '..table.concat(p,'.')
 for i=-1,-90,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=0,15 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
return table.concat(out,'\n')
