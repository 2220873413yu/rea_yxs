-- Dump only native relationship and slot-rendering functions; do not send requests.
local util=require('jit.util')
local out={}
local targets={
 {'SLGMainModel','getMyArmyId_InResourceField'}, {'SLGMainModel','isEnemyLeague'},
 {'SLGMainModel','IsSameLeague'}, {'SLGResourceCommonDialog','updateHeroList'},
 {'SLGResourceCommonDialog','isVisible'}, {'SLGResourceCommonDialog','isInOtherRegion'}
}
for _,t in ipairs(targets) do
 local fn=package.loaded[t[1]].__instanceDict[t[2]]
 out[#out+1]='FUNCTION '..table.concat(t,'.')..' '..type(fn)
 if type(fn)=='function' then
  for i=-1,-100,-1 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='K '..(-i-1)..' '..tostring(v) end
  for i=0,30 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
  for i=1,15 do local n,v=debug.getupvalue(fn,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
  for pc=1,util.funcinfo(fn).bytecodes-1 do
   local bc=util.funcbc(fn,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end
return table.concat(out,'\n')
