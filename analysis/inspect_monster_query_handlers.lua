-- Inspect response routing and local data fields to scope read-only query capture safely.
local util=require('jit.util');local out={}
for _,p in ipairs({{'SLGMainController','parseTSLGGetMonsterDetailRsp'}, {'SLGMainController','parseTSLGGetAvailHeroListRsp'},
 {'SLGMainController','parseTSLGMonsterGetAvailHeroListRsp'}, {'SLGMainModel','getMaxSoldierForFight'},
 {'SLGMonsterDetailDialog','updateBtnAreaStatus'}}) do
 local f=package.loaded[p[1]].__instanceDict[p[2]]
 if type(f)=='function' and util.funcinfo(f).bytecodes then
 out[#out+1]='FUNCTION '..table.concat(p,'.')..' params='..util.funcinfo(f).params
 for i=-1,-100,-1 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='K '..(-i-1)..' '..tostring(v) end
 for i=0,30 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for pc=1,math.min(350,util.funcinfo(f).bytecodes-1) do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
return table.concat(out,'\n')
