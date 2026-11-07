-- Read the native trial chooser's received response; never select a hero or submit the dialog.
local p=CSLTypes.PopUtils.findPopLayout(CSLTypes.SLGTowerChooseHeroScene)
local out={'popup_type='..type(p)}
if type(p)=='table'then
 for k,v in pairs(p)do out[#out+1]='popup_field '..tostring(k)..' '..type(v)end
 local view=p.multiChooseHeroScene and p or p.popLayout
 if type(view)=='table'then
  for k,v in pairs(view)do if type(k)=='string'then out[#out+1]='view_field '..k..' '..type(v)end end
  local multi=view.multiChooseHeroScene
  if type(multi)=='table'then
   for k,v in pairs(multi)do if type(k)=='string'then out[#out+1]='multi_field '..k..' '..type(v)end end
   local data=multi._chooseData
   if type(data)=='table'then for k,v in pairs(data)do
    out[#out+1]='data_field '..tostring(k)..' '..type(v)..((type(v)=='number' or type(v)=='boolean') and (' '..tostring(v)) or '')
   end
   if data.availHero then out[#out+1]='avail_count '..data.availHero:get_Count()end
   end
  end
 end
end
return table.concat(out,'\n')
