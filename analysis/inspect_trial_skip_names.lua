-- Enumerate loaded names and protocol layouts only. No battle, skip or selection callbacks are invoked.
local out={}
for name,cls in pairs(package.loaded)do
 if type(cls)=='table' and (name:find('Game') or name:find('SLG') or name:find('Fight') or name:find('Battle') or name:find('Match')) then
  for k,v in pairs(cls.__instanceDict or cls)do
   if type(k)=='string' and type(v)=='function' and (k:lower():find('skip') or k:find('EndGame') or k:find('GameOver') or k:find('GameResult') or k:find('FightResult') or k:find('SLGTower'))then
    out[#out+1]='METHOD '..name..'.'..k
   end
  end
 end
end
for name,fields in pairs(package.loaded.ChatClientProtoDes or {})do
 if type(name)=='string' and (name:find('Skip') or name:find('QuickFight') or name:find('EndGame') or name:find('GameOver') or name:find('Roll'))and type(fields)=='table'then
  out[#out+1]='PROTO '..name
  for _,f in ipairs(fields)do if type(f)=='table'then out[#out+1]='FIELD '..tostring(f.tag)..' '..tostring(f.name)end end
 end
end
return table.concat(out,'\n')
