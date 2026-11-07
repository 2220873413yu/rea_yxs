-- Dump collection/data lookup signatures and bytecode, without calling any request function.
local util=require('jit.util')
local out={}
local targets={
 {'SLGChooseHeroLogicCollectResource','startTrip2'}, {'SLGChooseHeroLogicCollectResource','getTargetID2'},
 {'SLGChooseHeroScene','getCostSecond'}, {'SLGChooseHeroScene','getCollectMax'}, {'SLGChooseHeroScene','getCollectSpeed'},
 {'SLGMapObjectModel','getResourceField'}, {'SLGMapObjectModel','getMyMainCityCoordinates'},
 {'SLGMainController','sendTSLGResourceInfo'}, {'SLGMainModel','getMaxCollectionArmyCount'}, {'SLGMainModel','checkMaxCollectionArmyCount'}
}
for _,target in ipairs(targets) do
 local fn=package.loaded[target[1]].__instanceDict[target[2]]
 out[#out+1]='FUNCTION '..target[1]..'.'..target[2]
 for i=-1,-70,-1 do local v=util.funck(fn,i);if v==nil then break end;if type(v)=='string' and not string.find(v,'[\128-\255]') then out[#out+1]='K '..(-i-1)..'='..v end end
 for i=0,30 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,15 do
  local n,v=debug.getupvalue(fn,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if type(v)=='function' then
   for k=-1,-30,-1 do local c=util.funck(v,k);if c==nil then break end;if type(c)=='string' and not string.find(c,'[\128-\255]') then out[#out+1]='UPK '..(-k-1)..'='..c end end
  elseif n=='T_ID' then for k,x in pairs(v) do if string.find(k,'RESOURCE') then out[#out+1]='PROTOCOL '..k..'='..tostring(x) end end end
 end
 for pc=1,util.funcinfo(fn).bytecodes-1 do local bc=util.funcbc(fn,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
return table.concat(out,'\n')
