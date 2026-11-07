-- Locate loaded result consumers by static function constants, without calling them.
local out={};local u=require('jit.util')
for name,cls in pairs(package.loaded)do
 if type(cls)=='table' and not name:find('Tower') and not name:find('Proto') then
  local d=cls.__instanceDict or cls
  for k,v in pairs(d)do
   if type(k)=='string' and type(v)=='function' and u.funcinfo(v).bytecodes then
    for i=-1,-130,-1 do local s=u.funck(v,i);if s==nil then break end
     if type(s)=='string' and (s=='SLGTowerModel' or s=='setHeroState' or s:find('TSLGQCT'))then out[#out+1]=name..'.'..k..' '..s end
    end
   end
  end
 end
end
return table.concat(out,'\n')
