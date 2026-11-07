-- Load type declarations only, without constructing UI or invoking any gameplay methods.
local out={}
for _,name in ipairs({'SLGButtonSkip','SLGGameScene','SLGGameResultStage','SLGPVEResultWinScene','SLGResultLostScene'})do
 local cls=package.loaded[name]
 if not cls then pcall(function()return CSLTypes[name]end);cls=package.loaded[name]end
 out[#out+1]='MODULE '..name..' '..type(cls)
 if type(cls)=='table'then for k,v in pairs(cls.__instanceDict or cls)do
  if type(k)=='string' and type(v)=='function'then out[#out+1]='METHOD '..name..'.'..k end
 end end
end
for name in pairs(package.loaded)do if name:find('Proto')then out[#out+1]='DESCRIPTOR '..name end end
return table.concat(out,'\n')
