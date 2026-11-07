-- Read module/member names and report protocol descriptors only; never call senders or UI actions.
local out={}
local function related(name)
 name=tostring(name):lower()
 return name:find('militarynews')or name:find('slgnews')
end
for name,c in pairs(package.loaded)do
 if related(name)and type(c)=='table'then
  out[#out+1]='MODULE '..name
  for k,v in pairs(c.__instanceDict or c)do if type(k)=='string'then out[#out+1]='MEMBER '..name..'.'..k..' '..type(v)end end
 end
end
for _,source in ipairs({'ChatClientProtoDes','RoomClientProtoDes'})do
 for name,fields in pairs(package.loaded[source]or{})do
  if related(name)and type(fields)=='table'then
   out[#out+1]='PROTO '..source..'.'..name
   for _,f in ipairs(fields)do if type(f)=='table'then out[#out+1]='FIELD '..tostring(f.tag)..' '..tostring(f.name)end end
  end
 end
end
for _,name in ipairs({'SLGMilitaryNewsDialog','SLGMilitaryNewsItem','SLGMilitaryNewsItemData'})do
 pcall(function()return CSLTypes[name]end)
 local c=package.loaded[name]
 if c then for k,v in pairs(c.__instanceDict or c)do if type(k)=='string'then out[#out+1]='NATIVE '..name..'.'..k..' '..type(v)end end end
end
for _,name in ipairs({'SLGMainController','SLGMainModel'})do
 local c=package.loaded[name]
 if c then for k,v in pairs(c.__instanceDict or c)do if type(k)=='string'and(k:lower():find('news')or k:lower():find('military'))then out[#out+1]='NATIVE '..name..'.'..k..' '..type(v)end end end
end
return table.concat(out,'\n')
