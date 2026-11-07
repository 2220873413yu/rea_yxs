-- Discover the independent dispatch model/UI and protocol declarations without sending or claiming tasks.
local u=require('jit.util');local out={}
for _,name in ipairs({'SLGDispatchModel','SLGDispatchController','SLGDispatchDialog','SLGDispatchListTaskItem',
 'SLGDispatchChooseHeroScene','SLGDispatchChooseHeroItem','DispatchTaskConditionInfo','DispatchHeroInfo'}) do
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 local dict=type(cls)=='table' and cls.__instanceDict
 out[#out+1]='CLASS '..name..' '..type(dict)
 if dict then
  local keys={};for k,v in pairs(dict) do if type(k)=='string' and type(v)=='function' then keys[#keys+1]=k end end;table.sort(keys)
  for _,k in ipairs(keys) do local f=dict[k]
   if u.funcinfo(f).bytecodes and (k:match('^[gs]et') or k:match('^send') or k:match('^parse') or k:match('^update') or
    k:match('^check') or k:match('^init') or k:find('Task') or k:find('Hero') or k:find('Reward') or k:find('Dispatch')) then
    local constants={}
    for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then constants[#constants+1]=v end end
    out[#out+1]='METHOD '..name..'.'..k..' '..table.concat(constants,'|')
    for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end
     if type(v)=='table' and (n=='T_ID' or n:lower():find('msg')) then
      for key,id in pairs(v) do if type(key)=='string' and key:find('DISPATCH') then out[#out+1]='PROTOCOL '..key..'='..tostring(id) end end
     end
    end
   end
  end
 end
end
local ok,model=pcall(function() return CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGDispatchModel) end)
out[#out+1]='MODEL '..tostring(ok)..' '..type(model)
if ok and type(model)=='table' then
 for k,v in pairs(model) do if type(k)=='string' and k:sub(1,1)=='_' then out[#out+1]='CACHE '..k..' '..type(v) end end
end
return table.concat(out,'\n')
