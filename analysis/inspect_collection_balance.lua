-- Inspect native resource readers and army schemas without sending game requests.
local out={};local u=require('jit.util')
local function constants(label,f)
 if type(f)~='function' then return end
 local info=u.funcinfo(f);if not info.bytecodes then return end
 local ks={}
 for i=-1,-120,-1 do local v=u.funck(f,i);if v==nil then break end
  if type(v)=='string' then ks[#ks+1]=v end
 end
 out[#out+1]='METHOD '..label..' '..table.concat(ks,'|')
end
for _,name in ipairs({'SLGMainModel','SLGMyMapArmyInfo','SLGMapArmyInfo','SLGStateItemArmyLogic',
 'SLGResourceHeroItem','SLGTopResourceItem','SLGMainScene','SLGMapMainScene','SLGBuildingsModel'}) do
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 local d=type(cls)=='table' and cls.__instanceDict
 if d then for k,f in pairs(d) do
  if type(k)=='string' and (k:lower():find('res') or k:lower():find('collect') or k:lower():find('army') or k:lower():find('load')) then constants(name..'.'..k,f) end
 end end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local armies=main._myActionState and main._myActionState[2]
if armies then for i=0,armies:get_Count()-1 do
 local a=armies:get_Item(i)
 out[#out+1]='ARMY '..tostring(a[1])..' aim='..tostring(a[5])..' state='..tostring(a[4])
 for k,v in pairs(a) do if type(k)=='string' then out[#out+1]='ARMY_META '..k..' '..type(v)
  elseif type(v)=='number' then out[#out+1]='FIELD '..k..' '..string.format('%.0f',v)
  elseif type(v)=='table' and k~=3 then for x,y in pairs(v) do
   if type(x)=='number' and type(y)=='number' then out[#out+1]='NEST '..k..'.'..x..' '..string.format('%.0f',y) end
  end end
 end
end end
return table.concat(out,'\n')
