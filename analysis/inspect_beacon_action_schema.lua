-- Read protocol declarations only; do not send any request.
local out={}
for name,d in pairs(package.loaded.ChatClientProtoDes) do
 if type(name)=='string' and (name:find('Scout') or name:find('TSLGGetSoldierNum')) and type(d)=='table' then
  out[#out+1]='TYPE '..name
  for slot,f in ipairs(d) do if type(f)=='table' then out[#out+1]='FIELD '..slot..' '..tostring(f.name)..' '..
   (type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or '') end end
 end
end
return table.concat(out,'\n')
