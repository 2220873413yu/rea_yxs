-- Trace the actual GuoGuanZhanJiang feature, including entry/level configuration, without joining a room.
local out={};local u=require('jit.util')
for _,name in ipairs({'EliteLevelModel','EliteLevelController','EliteLevelScene'}) do
 local c=package.loaded[name];if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 local d=c and c.__instanceDict;out[#out+1]='CLASS '..name..' '..type(d)
 if d then for k,f in pairs(d) do if type(f)=='function' and u.funcinfo(f).bytecodes then
  local ks={};for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then ks[#ks+1]=v end end
  if #ks>0 and not tostring(k):find('LuaBehaviour') and not tostring(k):find('getLua') then
   out[#out+1]='METHOD '..name..'.'..k..' params='..u.funcinfo(f).params..' '..table.concat(ks,'|')
  end
 end end end
end
local mm=CSLTypes.ModelManager.sharedInstance();local m=mm:getModel(CSLTypes.EliteLevelModel)
for k,v in pairs(m) do if type(k)=='string' and (type(v)=='number' or type(v)=='table') then out[#out+1]='CACHE '..k..' '..type(v) end end
local ok,r=pcall(m.getProgressMsg,m)
out[#out+1]='PROGRESS '..tostring(ok)..' '..type(r)
if ok and type(r)=='table' then for k,v in pairs(r) do if type(k)=='number' and type(v)=='number' then out[#out+1]='P '..k..'='..tostring(v) end end end
return table.concat(out,'\n')
