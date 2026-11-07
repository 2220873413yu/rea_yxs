-- Inspect observation and collection eligibility code only; no observer registration or dispatch.
local out={}
local util=require('jit.util')
local targets={{'Observable','addObserver'},{'Observable','removeObserver'},{'Observable','notifyUpdateData'},
 {'SLGMainController','parseTSLGResourceInfoRsp'},{'SLGMainController','parseTSLGMonsterGetAvailHeroListRsp'},
 {'SLGMainModel','isEnemyResourceField'}}
for _,t in ipairs(targets) do
 local cls=package.loaded[t[1]]
 local f=type(cls)=='table' and (cls.__instanceDict or cls)[t[2]]
 out[#out+1]='FUNCTION '..t[1]..'.'..t[2]..' '..type(f)
 if type(f)=='function' then
  for i=-1,-100,-1 do local v=util.funck(f,i);if v==nil then break end
   if type(v)=='string' and not string.find(v,'[\128-\255]') then out[#out+1]='K '..(-i-1)..'='..v
   elseif type(v)=='table' then for k,x in pairs(v) do if type(x)=='number' or type(x)=='boolean' then out[#out+1]='KT '..tostring(k)..'='..tostring(x) end end end
  end
  for i=0,40 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
  for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
  for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
for _,name in ipairs({'isVisible','isInOtherRegion'}) do
 local source=package.loaded.SLGResourceCommonDialog.__instanceDict.canCollect
 for i=1,10 do local n,f=debug.getupvalue(source,i);if not n then break end
  if n==name then
   out[#out+1]='FUNCTION HELPER.'..name
   for k=-1,-50,-1 do local c=util.funck(f,k);if c==nil then break end;if type(c)=='string' and not string.find(c,'[\128-\255]') then out[#out+1]='K '..(-k-1)..'='..c end end
   for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
  end
 end
end
return table.concat(out,'\n')
