-- List report-related native model methods, schemas and already cached counts without sending a query.
local out={}
for _,name in ipairs({'SLGBuildingsModel','SLGBuildingsController'})do
 local c=package.loaded[name];local d=c and(c.__instanceDict or c)
 if d then for k,v in pairs(d)do if type(k)=='string'and(k:lower():find('email')or k:lower():find('military'))then out[#out+1]='METHOD '..name..'.'..k..' '..type(v)end end end
end
for source,proto in pairs(package.loaded)do if type(source)=='string'and source:find('ProtoDes')and type(proto)=='table'then
 for name,fields in pairs(package.loaded[source]or{})do
  if type(name)=='string'and(name:find('SLG')and name:find('Email')or name:find('MilitaryNewspaper'))and type(fields)=='table'then
   out[#out+1]='PROTO '..name
   for i,f in ipairs(fields)do if type(f)=='table'then out[#out+1]='FIELD lua='..i..' tag='..tostring(f.tag)..' '..tostring(f.name)..' '..tostring(f.struct_path and table.concat(f.struct_path,'.')or'')end end
  end
 end
end end
local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGBuildingsModel)
for k,v in pairs(m)do if type(k)=='string'and(k:lower():find('email')or k:lower():find('military'))then
 out[#out+1]='CACHE '..k..' '..type(v)
 if type(v)=='number'or type(v)=='boolean'then out[#out+1]='VALUE '..k..'='..tostring(v)end
end end
local r=m:getTSLGGetAllEmailRsp()
if r then for i=1,12 do local v=r[i]
 if type(v)=='number'or type(v)=='boolean'then out[#out+1]='RESPONSE ['..i..']='..tostring(v)
 elseif type(v)=='table'and v.get_Count then out[#out+1]='RESPONSE ['..i..'] count='..v:get_Count()end
end else out[#out+1]='RESPONSE absent'end
if r and r[2]then
 local states={};local templates={}
 for i=0,r[2]:get_Count()-1 do local row=r[2]:get_Item(i)
  local key=tostring(row[3]);states[key]=(states[key]or 0)+1
  templates[row[2]]=(templates[row[2]]or 0)+1
 end
 for k,v in pairs(states)do out[#out+1]='ROW_STATE '..k..' count='..v end
 for k,v in pairs(templates)do out[#out+1]='TEMPLATE '..tostring(k)..' count='..v end
 local row=r[2]:get_Item(0)
 for i=1,10 do local v=row and row[i];if type(v)=='number'or type(v)=='boolean'then out[#out+1]='FIRST_ROW ['..i..']='..tostring(v)
 elseif type(v)=='table'and v.get_Count then out[#out+1]='FIRST_ROW ['..i..'] count='..v:get_Count()end end
end
return table.concat(out,'\n')
