-- Read named dispatch request/response and hero-occupancy protocol descriptors only.
local out={}
local function dump(module,name,d)
 out[#out+1]='TYPE '..module..'.'..name
 for _,f in ipairs(d) do if type(f)=='table' then
  local path=type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or ''
  out[#out+1]=string.format('FIELD tag=%s name=%s type=%s struct=%s',tostring(f.tag),tostring(f.name),tostring(f.type),path)
  for k,v in pairs(f) do if type(v)=='table' and k~='struct_path' then
   local fs={};for x,y in pairs(v) do if type(y)=='string' or type(y)=='number' then fs[#fs+1]=tostring(x)..'='..tostring(y) elseif type(y)=='table' and x=='struct_path' then fs[#fs+1]='struct='..table.concat(y,'.') end end
   out[#out+1]='SUB '..tostring(k)..' '..table.concat(fs,'|')
  end end
 end end
end
for module,p in pairs(package.loaded) do
 if type(module)=='string' and module:find('ProtoDes') and type(p)=='table' then
  for name,d in pairs(p) do if type(name)=='string' and type(d)=='table' and
   (name:find('DuHuFuGetHeroList') or name:find('ActiveHeroInfo') or name:find('DuHuFuSelectHero')) then dump(module,name,d) end end
 end
end
return table.concat(out,'\n')
