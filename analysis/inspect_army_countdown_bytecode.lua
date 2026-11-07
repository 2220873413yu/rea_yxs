-- Read native countdown field accesses without instantiating UI or sending requests.
local util=require('jit.util');local out={}
for _,pair in ipairs({{'SLGStateItemArmyLogic','updateEndTime'},{'SLGStateItemArmyLogic','initialize'},
 {'SLGStateItemArmyLogic','onTimeout'},{'SLGResourceHeroItem','getArmyEstimateTime'},
 {'SLGResourceHeroItem','updateCollectInfo'},{'SLGResourceHeroItem','setFriendCollectInfoVisible'},
 {'SLGArmyModel','isArmyInIdle'},{'SLGResourceCommonDialog','updateFallBackUI'}}) do
 local fn=package.loaded[pair[1]].__instanceDict[pair[2]]
 out[#out+1]='FUNCTION '..pair[1]..'.'..pair[2]
 for i=-1,-120,-1 do local v=util.funck(fn,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=0,20 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='NUM '..i..' '..tostring(v) end
 for pc=1,util.funcinfo(fn).bytecodes-1 do local bc=util.funcbc(fn,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
return table.concat(out,'\n')
