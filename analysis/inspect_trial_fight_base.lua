-- Resolve base game/UI declarations and enumerate skip-related names; never construct a scene or send a command.
local out={};local util=require('jit.util')
for _,name in ipairs({'FightGameScene'})do
 local cls=package.loaded[name]
 if not cls then pcall(function()return CSLTypes[name]end);cls=package.loaded[name]end
 if cls then for k,v in pairs(cls.__instanceDict or cls)do
  if type(k)=='string' and type(v)=='function'then
   if k:lower():find('skip') or k:lower():find('roll') or k:find('Result') or k=='Start' then out[#out+1]='METHOD '..name..'.'..k end
   if util.funcinfo(v).bytecodes then
    for i=-1,-130,-1 do local s=util.funck(v,i);if s==nil then break end
     if type(s)=='string' and (s:lower():find('skip') or s:lower():find('roll') or s=='SLGTowerModel')then
      out[#out+1]='LINK '..name..'.'..k..' '..s
     end
    end
   end
  end
 end end
end
return table.concat(out,'\n')
