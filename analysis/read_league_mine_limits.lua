-- Inspect current mine ownership, server member deadlines and native membership/own-army gating without sending requests.
local out={};local manager=CSLTypes.ModelManager.sharedInstance();local main=manager:getModel(CSLTypes.SLGMainModel)
local league=manager:getModel(CSLTypes.SLGLeagueModel);local search=CSLTypes.DBSearcher.sharedInstance()
local r=assert(league:getTSLGLeagueGetResourceRsp());local b=league:getTSLGLeagueGetAllBuildRsp()
for i=3,9 do local v=b and b[i]
 if type(v)=='table' then
  out[#out+1]='BUILD_FIELD '..i..' target='..tostring(type(v[2])=='number' and v[2] or 'none')..' config='..tostring(type(v[3])=='number' and v[3] or 'none')
 end
end
local mine=r[2];local config=search:searchTLeagueResource(mine[3])
out[#out+1]='MINE slot_config='..config[11]..' bonus_percent='..config[6]..' same_league='..tostring(mine[9]==main:getMyLeagueId())
for i=0,r[3]:get_Count()-1 do
 local a=r[3]:get_Item(i);local record=league:getLeagueCollectDataByArmyId(a[1])
 out[#out+1]='MEMBER army='..a[1]..' own='..tostring(main.checkIsMyArmy(a))..' state='..a[4]..' army_end='..tostring(a[11])
 if record then for k,v in pairs(record) do if type(k)=='number' and type(v)=='number' then out[#out+1]='COLLECT '..a[1]..'.'..k..'='..v end end end
end
local u=require('jit.util');local f=package.loaded.SLGResourceHeroItem.__instanceDict.updateLeagueCollectInfo
out[#out+1]='FUNCTION updateLeagueCollectInfo'
for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
return table.concat(out,'\n')
