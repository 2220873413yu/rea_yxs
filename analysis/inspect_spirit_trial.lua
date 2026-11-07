-- Read loaded declarations only; no selection, query, challenge, battle or reward function is called.
local out={}
local function related(s)
 s=tostring(s):lower()
 return s:find('trial') or s:find('tower') or s:find('lingtai') or s:find('shilian') or s:find('climb')
end
for name,cls in pairs(package.loaded) do
 if related(name) then
  out[#out+1]='MODULE '..name
  if type(cls)=='table' then for k,v in pairs(cls.__instanceDict or cls) do
   if type(k)=='string' then out[#out+1]='MEMBER '..name..'.'..k..' '..type(v) end
  end end
 end
end
local proto=package.loaded.ChatClientProtoDes or {}
for name,fields in pairs(proto) do
 if related(name) and type(fields)=='table' then
  out[#out+1]='PROTO '..name
  for _,f in ipairs(fields) do if type(f)=='table' then
   out[#out+1]='FIELD '..tostring(f.tag)..' '..tostring(f.name)
  end end
 end
end
return table.concat(out,'\n')
