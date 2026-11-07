-- Read-only cached hero snapshot using the same name and clock lookup as the hero screen.
local out={}
local manager=CSLTypes.ModelManager.sharedInstance()
local model=manager:getModel(CSLTypes.SLGBuildingsModel)
local response=model:getTSLGGetHeroPubRsp()
local list=response[2][2][1]
local search=CSLTypes.DBSearcher.sharedInstance()
local _,provider=debug.getupvalue(package.loaded.HeroPalaceItem.__instanceDict.Update,1)
local nowMs=provider():GetCurrentServerTime()*1000
out[#out+1]="CLOCK now_ms="..string.format("%.0f",nowMs).." response_time_ms="..tostring(response[3])
for index=0,list:get_Count()-1 do
 local hero=list:get_Item(index)
 local brief=hero[1]
 local config=search:searchHeroInfoByStarAndGroup(1,brief[3])
 local name=type(config)=="table" and CSLTypes.YXSUtils.GBK2UTF8(config[7]) or "unknown"
 local remaining=math.max(0,math.ceil((hero[3]-nowMs)/1000))
 out[#out+1]=string.format("HERO name=%s item_id=%s level=%s stars=%s state=%s recover_remaining_s=%d power=%s",name,tostring(brief[3]),tostring(brief[1]),tostring(brief[2]),tostring(hero[2]),remaining,tostring(hero[4]))
end
return table.concat(out,"\n")
