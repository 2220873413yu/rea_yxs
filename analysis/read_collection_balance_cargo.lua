-- Inspect native carried goods and resource type mappings without sending requests.
local out={};local p=package.loaded.ChatClientProtoDes;local u=require('jit.util')
for _,name in ipairs({'TUserResource','TItemInfo','TArmyTripBaseInfo','TSLGGetAllArmyRsp'}) do
 out[#out+1]='TYPE '..name
 for slot,f in ipairs(p[name] or {}) do if type(f)=='table' then
  out[#out+1]=string.format('SLOT %d tag=%s name=%s',slot,tostring(f.tag),tostring(f.name))
 end end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
for _,idx in ipairs({2,3}) do local list=main._myActionState[idx]
 if list then for i=0,list:get_Count()-1 do local a=list:get_Item(i)
  out[#out+1]='ARMY '..a[1]..' aim='..a[5]..' state='..a[4]
  local items=a[12];out[#out+1]='ITEMS '..type(items)
  if items and items.get_Count then for j=0,items:get_Count()-1 do local item=items:get_Item(j)
   out[#out+1]='ITEM '..tostring(item[1])..' count='..tostring(item[2])
  end end
 end end
end
for _,key in ipairs({'UpdateResource'}) do local f=package.loaded.SLGMainModel.__instanceDict[key]
 for i=0,30 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='NUM '..i..' '..tostring(v) end
end
return table.concat(out,'\n')
