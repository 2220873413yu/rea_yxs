-- Inspect native collection predicates and configuration only; no request or departure is sent.
local util=require('jit.util')
local out={}
local targets={
 {'SLGResourceCommonDialog','canCollect'},
 {'SLGResourceCommonDialog','updateButtonsState'},
 {'SLGResourceCommonDialog','SetData'},
 {'SLGMainModel','isMyArmyExist_InResourceField'},
 {'SLGMainModel','isEnemyResourceField'},
 {'SLGMainModel','IsAllyLeague'}
}
for _,target in ipairs(targets) do
 local cls=package.loaded[target[1]]
 local fn=cls and cls.__instanceDict and cls.__instanceDict[target[2]]
 out[#out+1]='FUNCTION '..table.concat(target,'.')..' '..type(fn)
 if type(fn)=='function' then
  for i=-1,-200,-1 do
   local v=util.funck(fn,i);if v==nil then break end
   out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v)
  end
  for i=0,60 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
  for i=1,20 do
   local n,v=debug.getupvalue(fn,i);if not n then break end
   out[#out+1]='UP '..i..' '..n..' '..type(v)
   if type(v)=='number' or type(v)=='string' then out[#out+1]='UPVAL '..tostring(v) end
  end
  for pc=1,util.funcinfo(fn).bytecodes-1 do
   local bc,mode=util.funcbc(fn,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d MODE=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536,mode)
  end
 end
end
local search=CSLTypes.DBSearcher.sharedInstance()
for _,kind in ipairs({30000,31000,32000}) do
 for level=1,7 do
  local row=search:searchTNewPlay_Resource_Map(kind+level)
  out[#out+1]='CONFIG '..(kind+level)
  if type(row)=='table' then for k,v in pairs(row) do
   if type(v)=='number' then out[#out+1]='FIELD '..tostring(k)..'='..v end
  end end
 end
end
return table.concat(out,'\n')
