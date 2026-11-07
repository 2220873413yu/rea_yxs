-- Read schema and static configuration, printing no mail descriptions, nicknames or player identities.
local out={}
for source,proto in pairs(package.loaded)do if type(source)=='string'and source:find('ProtoDes')and type(proto)=='table'then
 for name,fields in pairs(proto)do if type(name)=='string'and(name:find('Email')or name:find('MailInfo'))then
  out[#out+1]='SCHEMA '..source..'.'..name
  if name=='TSLGGetAllEmailRsp'or name=='TSLGEmail'or name=='TEmailInfo'then
   for i,f in ipairs(fields)do if type(f)=='table'then
    for k,v in pairs(f)do if type(v)=='string'or type(v)=='number'then out[#out+1]='FIELD '..i..'.'..tostring(k)..'='..tostring(v)
     elseif type(v)=='table'then for a,b in pairs(v)do if type(b)=='string'or type(b)=='number'then out[#out+1]='FIELD '..i..'.'..tostring(k)..'.'..tostring(a)..'='..tostring(b)end end end
    end
   end end
  end
 end end
end end
local db=CSLTypes.DBSearcher.sharedInstance()
for _,name in ipairs({'DBSearcher','GlobalVariable'})do
 pcall(function()return CSLTypes[name]end)
 local c=package.loaded[name];if c then for k,v in pairs(c.__instanceDict or c)do
  if type(k)=='string'and(name=='GlobalVariable'or k:lower():find('global'))then out[#out+1]='CONFIG_MEMBER '..name..'.'..k..' '..type(v)end
 end end
end
local d=package.loaded.DBSearcher
if d then local fn=(d.__instanceDict or d).searchGlobalVariable
 if type(fn)=='function'then for i=1,12 do local n,v=debug.getupvalue(fn,i);if not n then break end;out[#out+1]='GLOBAL_UP '..i..' '..n..' '..type(v)end end
end
return table.concat(out,'\n')
