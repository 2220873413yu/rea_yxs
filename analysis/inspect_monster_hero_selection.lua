-- Read selection and recovery checks; do not invoke scene actions or network senders.
local out={}
local util=require('jit.util')
for _,name in ipairs({'SLGChooseHeroScene','SLGChooseHeroItem','SLGChooseHeroLogicMonster','SLGChooseHeroLogicBase','SLGChooseHeroCommon'}) do
 local cls=package.loaded[name]
 local methods=type(cls)=='table' and cls.__instanceDict
 out[#out+1]='MODULE '..name..' '..type(methods)
 if methods then
  for k,v in pairs(methods) do
   if type(v)=='function' then
    local keys={}
    for i=-1,-90,-1 do local c=util.funck(v,i);if c==nil then break end;if type(c)=='string' then keys[#keys+1]=c end end
    out[#out+1]='METHOD '..k..' params='..util.funcinfo(v).params..' CONST '..table.concat(keys,'|')
   elseif type(v)=='table' then
    out[#out+1]='TABLE '..tostring(k)
   end
  end
 end
end
return table.concat(out,'\n')
