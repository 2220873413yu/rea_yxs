-- Inspect native default formation helpers and UI-only callbacks; never execute a sender.
local out={};local u=require('jit.util')
local function dump(name,f)
 out[#out+1]='FUNCTION '..name..' params='..u.funcinfo(f).params
 for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=0,15 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
for _,p in ipairs({{'SLGChosenSoldier','initialize'},{'SLGChosenSoldier','setPosition'},{'SLGChosenSoldier','setSodierId'}}) do dump(table.concat(p,'.'),package.loaded[p[1]].__instanceDict[p[2]]) end
local f=package.loaded.SLGChooseHeroScene.__instanceDict.updateSoldier
for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end;if type(v)=='function' then dump('updateSoldier.UP'..i..'.'..n,v) end end
return table.concat(out,'\n')
