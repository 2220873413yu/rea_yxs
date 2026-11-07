-- Read soldier request constructors only; never assign troops or send requests.
local out={}
local util=require('jit.util')
for _,name in ipairs({'SLGChooseHeroScene','SLGChosenSoldier'}) do
 for key,f in pairs(package.loaded[name].__instanceDict) do
  if type(f)=='function' then
   for i=1,20 do local n,v=debug.getupvalue(f,i);if not n then break end
    if string.find(n,'Soldier') then out[#out+1]='CONSTRUCTOR '..name..'.'..key..' UP '..i..' '..n..' '..type(v) end
   end
  end
 end
end
for name,cls in pairs(package.loaded) do
 if type(name)=='string' and string.find(name,'Soldier') and type(cls)=='table' then
  local dict=cls.__instanceDict or cls
  local f=dict.getSoldierInfo
  if type(f)=='function' then
   out[#out+1]='FUNCTION '..name..'.getSoldierInfo'
   for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
   for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
  end
 end
end
return table.concat(out,'\n')
