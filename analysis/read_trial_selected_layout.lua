-- Read exact selected-hero identifiers before the first challenge; no action is sent.
local out={}
for _,name in ipairs({'THeroInfo','TQCTHeroInfo','TMakeArmyReq'})do
 out[#out+1]='PROTO '..name
 for i,f in ipairs(package.loaded.ChatClientProtoDes[name] or {})do if type(f)=='table'then out[#out+1]='FIELD lua='..i..' '..f.name end end
end
local r=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGTowerModel):getMainData()
for i=0,r[7]:get_Count()-1 do local h=r[7]:get_Item(i)
 for k=1,6 do if type(h[1][k])=='number'then out[#out+1]='hero_'..i..'_slot_'..k..'='..h[1][k]end end
end
return table.concat(out,'\n')
