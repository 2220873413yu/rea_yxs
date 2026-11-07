-- Inspect lazy type names only; resolving a declaration does not instantiate its scene or call an action.
local out={}
local function match(s)return type(s)=='string' and (s:lower():find('skip') or s:lower():find('surrender') or s:find('Result') or s:find('GameOver') or s:find('EndGame') or s:find('Fight'))end
for _,entry in ipairs({{'preload',package.preload},{'types',CSLTypes},{'globals',_G}})do
 if type(entry[2])=='table'then for k,v in pairs(entry[2])do if match(k)then out[#out+1]=entry[1]..' '..k..' '..type(v)end end end
end
for k,v in pairs(package.loaded.GameMsgMgr.__instanceDict or package.loaded.GameMsgMgr)do
 if type(k)=='string' and type(v)=='function'then out[#out+1]='MSG '..k end
end
local meta=getmetatable(CSLTypes)
if type(meta)=='table'then for k,v in pairs(meta)do
 out[#out+1]='META '..tostring(k)..' '..type(v)
 if type(v)=='function'then for i=1,15 do local name,x=debug.getupvalue(v,i);if not name then break end
  out[#out+1]='UP '..name..' '..type(x)
  if type(x)=='table'then for a,b in pairs(x)do if match(a)then out[#out+1]='TYPE '..a..' '..type(b)end end end
 end end
end end
return table.concat(out,'\n')
