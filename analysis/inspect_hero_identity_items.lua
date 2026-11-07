-- Read-only identities, cooldown records and public item configuration; no sending functions.
local out={}
local util=require("jit.util")
local fn=package.loaded.HeroPalaceItem.__instanceDict.initHeroName
out[#out+1]="FUNCTION initHeroName"
for pc=1,util.funcinfo(fn).bytecodes-1 do
 local bc=util.funcbc(fn,pc)
 out[#out+1]=string.format("BC %d OP=%d A=%d B=%d C=%d D=%d",pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
end
local mm=CSLTypes.ModelManager.sharedInstance()
local rsp=mm:getModel(CSLTypes.SLGBuildingsModel):getTSLGGetHeroPubRsp()
local list=rsp[2][2][1]
out[#out+1]="HERO_COUNT "..list:get_Count()
for i=0,math.min(list:get_Count()-1,39) do
 local hero=list:get_Item(i)
 local brief=hero[1]
 out[#out+1]=string.format("HERO index=%d brief1=%s brief2=%s item_id=%s status=%s recover_ms=%s power=%s",i,tostring(brief[1]),tostring(brief[2]),tostring(brief[3]),tostring(hero[2]),tostring(hero[3]),tostring(hero[4]))
end
local search=CSLTypes.DBSearcher.sharedInstance()
local items=mm:getModel(CSLTypes.ItemsModel)
for _,id in ipairs({70251,70271,70272,70273,70274,70291,70292,70293,70294,70295,70296}) do
 local cfg=search:searchItemInfo(id)
 local strings={}
 if type(cfg)=="table" then
  for k,v in pairs(cfg) do
   if type(k)=="number" and type(v)=="string" then
    local ok,decoded=pcall(function() return CSLTypes.YXSUtils.GBK2UTF8(v) end)
    if ok then strings[#strings+1]=k.."="..tostring(decoded) end
   end
  end
 end
 table.sort(strings)
 out[#out+1]="ITEM "..id.." count="..items:getItemCount(id).." fields="..table.concat(strings," | ")
end
return table.concat(out,"\n")
