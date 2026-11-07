-- Inspect function signatures and cache layouts without sending network requests.
local util=require('jit.util')
local out={}
local targets={{'SLGMainModel','setMyActionState'},{'SLGBuildingsModel','updateTSLGBuildSpeedupRsp'}}
for _,t in ipairs(targets) do
 local f=package.loaded[t[1]].__instanceDict[t[2]]
 local info=util.funcinfo(f)
 out[#out+1]=t[1]..'.'..t[2]..' params='..info.params
 for i=-1,-40,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..'='..v end end
 for i=0,10 do local n,v=debug.getupvalue(f,i);if n then out[#out+1]='UP '..i..' '..n..' '..type(v);if type(v)=='function' then for k=-1,-15,-1 do local c=util.funck(v,k);if c==nil then break end;if type(c)=='string' then out[#out+1]='UPK '..(-k-1)..'='..c end end end end end
 for pc=1,info.bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
return table.concat(out,'\n')
