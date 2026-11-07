-- Read the current game's trip request construction; do not send any request.
local util=require('jit.util')
local out={}
for _,t in ipairs({{'SLGChooseHeroLogicMonster','startTrip'},{'SLGChooseHeroLogicMonster','getTargetID2'},{'SLGChooseHeroScene','getSoldierInfoList'}}) do
 local f=package.loaded[t[1]].__instanceDict[t[2]]
 local info=util.funcinfo(f)
 out[#out+1]='FUNCTION '..t[1]..'.'..t[2]..' params='..info.params
 for i=-1,-90,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..'='..v elseif type(v)=='table' then local a={};for k,x in pairs(v) do if type(x)=='number' or type(x)=='string' then a[#a+1]=tostring(k)..'='..tostring(x) end end;out[#out+1]='KT '..(-i-1)..'='..table.concat(a,',') end end
 for i=0,50 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..'='..n..' '..type(v) end
 for pc=1,info.bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
return table.concat(out,'\n')
