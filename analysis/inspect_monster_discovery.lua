-- Inspect monster model schemas and combat recommendation predicates; never query or dispatch armies.
local util=require('jit.util');local out={}
for name,cls in pairs(package.loaded) do
 local methods=type(cls)=='table' and cls.__instanceDict
 if type(methods)=='table' then
  for k,f in pairs(methods) do
   if type(f)=='function' and util.funcinfo(f).bytecodes then
    local hit=false;local constants={}
    for i=-1,-150,-1 do local v=util.funck(f,i);if v==nil then break end
     if type(v)=='string' then
      constants[#constants+1]=v
      if v:find('胜券') or v:find('我方超强') or v:find('势均') or v:find('vecWildMonster') or
       v:find('CombatValueExceed') then hit=true end
     end
    end
    local core=(name=='SLGWildMonsterModel' or name=='SLGChooseHeroLogicMonster' or name=='SLGMonsterCommonDialog' or
     (name=='SLGMapObjectModel' and k:lower():find('monster')) or
     (name=='SLGMainController' and k:lower():find('monster')))
    if hit or core then
     out[#out+1]='FUNCTION '..name..'.'..k..' params='..util.funcinfo(f).params
     out[#out+1]='CONST '..table.concat(constants,'|')
     for i=0,24 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
     for i=1,15 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v)
      if n=='T_ID' then for a,b in pairs(v) do if tostring(a):find('MONSTER') then out[#out+1]='ID '..a..'='..b end end end
     end
    end
   end
  end
 end
end
for name in pairs(package.loaded) do if type(name)=='string' and (name:find('Monster') or name:find('Combat')) then out[#out+1]='LOADED '..name end end
return table.concat(out,'\n')
