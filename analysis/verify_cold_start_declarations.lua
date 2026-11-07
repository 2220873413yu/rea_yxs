-- Read declaration availability and captured types only; never construct UI or send requests.
local rows={}
for _,entry in ipairs({{'UpgradeAccelerationNewDialog','useButtonCallback',2},{'HeroPalaceItem','Update',1}}) do
 local name=entry[1]
 local cached=type(package.loaded[name])=='table'
 local cls=package.loaded[name]
 if type(cls)~='table' then
  local ok,value=pcall(function() return CSLTypes[name] end)
  cls=package.loaded[name] or (ok and value)
 end
 if type(cls)~='table' then local ok,value=pcall(require,name);if ok then cls=value end end
 local fn=type(cls)=='table' and cls.__instanceDict and cls.__instanceDict[entry[2]]
 local upname,value
 if type(fn)=='function' then upname,value=debug.getupvalue(fn,entry[3]) end
 rows[#rows+1]=string.format('%s cached=%s resolved=%s callback=%s capture=%s type=%s',
  name,tostring(cached),tostring(type(cls)=='table'),type(fn),tostring(upname),type(value))
end
return table.concat(rows,'\n')
