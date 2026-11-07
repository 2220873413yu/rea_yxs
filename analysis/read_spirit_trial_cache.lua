-- Read cached tower profile and already-loaded hero strengths; do not refresh, select, fight or claim.
local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGTowerModel)
local r=m:getMainData()
local out={}
if not r then return 'tower_profile_not_cached' end
for _,k in ipairs({1,2,3,4,5,7,9,11,12,13,14}) do out[#out+1]='profile_slot_'..k..'='..tostring(r[k]) end
local selected=r[7]
out[#out+1]='selected_count='..tostring(selected and selected.get_Count and selected:get_Count())
if selected and selected.get_Count then for i=0,selected:get_Count()-1 do
 local h=selected:get_Item(i)
 out[#out+1]='selected; group='..tostring(h[1] and h[1][3])..'; state='..tostring(h[2])..'; defeats='..tostring(h[3])..'; total_power='..tostring(h[4])
end end
local consume=CSLTypes.SLGTowerModel.getConsumeSoldierCount()
out[#out+1]='soldiers_per_hero='..tostring(consume)
local quest=CSLTypes.DBSearcher.sharedInstance():searchGenerateTowerQuest(r[2]+1)
if quest then for k,v in pairs(quest)do if type(k)=='number' and type(v)=='number'then out[#out+1]='next_floor_config_slot_'..k..'='..v end end end
local pub=mm:getModel(CSLTypes.SLGBuildingsModel):getTSLGGetHeroPubRsp()
local list=pub and pub[2] and pub[2][2] and pub[2][2][1]
local heroes={}
if list and list.get_Count then for i=0,list:get_Count()-1 do
 local h=list:get_Item(i)
 if h[1] and type(h[4])=='number' then heroes[#heroes+1]={group=h[1][3],power=h[4]} end
end end
table.sort(heroes,function(a,b)return a.power>b.power end)
for i=1,math.min(6,#heroes)do
 local c=CSLTypes.DBSearcher.sharedInstance():searchHeroInfoByStarAndGroup(1,heroes[i].group)
 local name=c and CSLTypes.YXSUtils.GBK2UTF8(c[7]) or 'unknown'
 out[#out+1]='cached_hero; name='..name..'; group='..tostring(heroes[i].group)..'; power='..heroes[i].power
end
for name in pairs(package.loaded)do if name:find('ChooseHero') or name:find('FightResult') then out[#out+1]='related_module '..name end end
return table.concat(out,'\n')
