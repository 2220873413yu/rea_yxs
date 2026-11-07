-- Inspect native login/packet assembly functions; no callbacks or senders are executed.
local out={};local u=require('jit.util');local seen={}
local function dump(label,fn,depth)
 if type(fn)~='function' or seen[fn] then return end;seen[fn]=true
 local info=u.funcinfo(fn);if not info.bytecodes then return end
 out[#out+1]='FUNCTION '..label..' params='..info.params
 for i=-1,-160,-1 do local v=u.funck(fn,i);if v==nil then break end
  if type(v)=='string' and (v=='' or v:match('^[%a_][%w_%.]*$')) then out[#out+1]='K '..i..' '..v end
 end
 for i=0,30 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 local nested={}
 for i=1,30 do local name,value=debug.getupvalue(fn,i);if not name then break end
  out[#out+1]='UP '..i..' '..name..' '..type(value)
  if type(value)=='function' then nested[#nested+1]={name,value} end
 end
 for pc=1,info.bytecodes-1 do local bc=u.funcbc(fn,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 if depth>0 then for _,v in ipairs(nested) do dump(label..'.UP.'..v[1],v[2],depth-1) end end
end

for name,cls in pairs(package.loaded)do
 if type(cls)=='table' and (name:find('SLG') or name=='CommonClientFunc')then
  local dict=cls.__instanceDict or cls
  for k,fn in pairs(dict)do if type(fn)=='function' and u.funcinfo(fn).bytecodes then
   local match=false
   for i=-1,-90,-1 do local v=u.funck(fn,i);if v==nil then break end
    if type(v)=='string' and (v:find('SLGTower') or v:find('QCT') or v:find('MultiChooseHero'))then match=true;break end
   end
   if match then out[#out+1]='LINK '..name..'.'..k end
  end end
 end
end
for _,name in ipairs({'SLGTowerChooseHeroScene','SLGMultiChooseHeroScene','MultiChooseHeroScene'})do
 local cls=package.loaded[name]
 if not cls then pcall(function()return CSLTypes[name]end);cls=package.loaded[name]end
 if cls then for k,v in pairs(cls.__instanceDict or cls)do
  if type(v)=='table' and tostring(k):find('__c') then for a,b in pairs(v.__instanceDict or v)do if type(b)=='function' and a=='_show_b__0' then dump(name..'.'..k..'.'..a,b,1)end end end
  if type(v)=='function' and (k:lower():find('sort') or k:find('Content') or k:find('Select'))then dump(name..'.'..k,v,1)end
 end end
end
return table.concat(out,'\n')
