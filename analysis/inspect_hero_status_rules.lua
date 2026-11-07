-- Read function metadata only; never invoke requests or acceleration.
local out={}
local util=require('jit.util')
for _,target in ipairs({{'HeroPalaceItem','initHeroStatus'},{'SLGMainModel','getMyArmyInfoByHeroGroupId'}}) do
 local fn=package.loaded[target[1]].__instanceDict[target[2]]
 out[#out+1]='FUNCTION '..target[1]..'.'..target[2]
 for i=-1,-120,-1 do
  local value=util.funck(fn,i)
  if value==nil then break end
  if type(value)=='string' then out[#out+1]='K '..(-i-1)..'='..value end
 end
 for i=0,100 do
  local value=util.funck(fn,i)
  if value==nil then break end
  out[#out+1]='N '..i..'='..tostring(value)
 end
 for pc=1,util.funcinfo(fn).bytecodes-1 do
  local bc=util.funcbc(fn,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
return table.concat(out,'\n')
