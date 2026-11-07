-- Inspect exact native field names and cached collection progress, without sending requests.
local out={};local p=package.loaded.ChatClientProtoDes
for _,name in ipairs({'TArmyInfo','TArmyTripDetailInfo','TSLGMyResource','TSLGResourceInfo','TSLGResource',
 'TSLGResourceCollectInfo','TArmyTripInfo','TSLGCollectInfo','TLeagueResourceCollectInfo'}) do
 out[#out+1]='TYPE '..name
 for _,f in ipairs(p[name] or {}) do if type(f)=='table' then
  out[#out+1]=string.format('FIELD %s %s %s',tostring(f.tag),tostring(f.name),
    type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or '')
 end end
end
for name,d in pairs(p) do if type(name)=='string' and type(d)=='table' and
 (name:find('SLG.*Res') or name:find('Collect') or name:find('Army')) then
 for _,f in ipairs(d) do if type(f)=='table' and type(f.name)=='string' and
  (f.name:lower():find('resource') or f.name:lower():find('collect') or f.name=='lFood' or f.name=='lWood' or f.name=='lMind') then
  out[#out+1]='MATCH '..name..' '..tostring(f.tag)..' '..f.name..' '..(type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or '')
 end end
end end
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local list=m._myActionState[2]
for i=0,list:get_Count()-1 do local a=list:get_Item(i)
 if a[5]==1 then
  out[#out+1]='ARMY '..a[1]
  for k,v in pairs(a) do if type(k)=='number' then
   if type(v)=='table' and k~=3 and k~=15 then
    for x,y in pairs(v) do if type(x)=='number' then out[#out+1]='F '..k..'.'..x..' '..type(y)..' '..(type(y)=='number' and tostring(y) or '') end end
   else out[#out+1]='F '..k..' '..type(v) end
  end end
 end
end
return table.concat(out,'\n')
