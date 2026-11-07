-- Inspect current cached capacity, owned returns and error text; never query or dispatch.
local mm=CSLTypes.ModelManager.sharedInstance();local main=mm:getModel(CSLTypes.SLGMainModel)
local out={}
local fn=package.loaded.SLGMainController.__instanceDict.sendTSLGGetAllArmyReq
for i=1,12 do local name,value=debug.getupvalue(fn,i);if not name then break end
 if type(value)=='table' and value.E_SVR_MSG_ID_SLG_GET_ALL_ARMY then
  out[#out+1]='all_army_protocol='..tostring(value.E_SVR_MSG_ID_SLG_GET_ALL_ARMY)
 end
end
local error=CSLTypes.DBSearcher.sharedInstance():searchHallError(6395)
if error then for k,v in pairs(error) do if type(v)=='string' then
 out[#out+1]='error6395.'..tostring(k)..'='..CSLTypes.YXSUtils.GBK2UTF8(v)
end end end
out[#out+1]='server_now='..tostring(CSLTypes.RefreshTimer.getServerTimeNow())
out[#out+1]='server_nature_now='..tostring(CSLTypes.RefreshTimer.getServerNatureTimeNow())
local r=main:getTSLGGetBeaconTowerInfoRsp()
if r then
 out[#out+1]='cached_beacon_limit='..tostring(r[6])..' native_full='..tostring(main:checkMaxFengHuoTaiArmyCount())
 for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i)
  out[#out+1]='event='..e[1][2]..' state='..e[3]..' army='..e[4]..' end='..e[6]
 end
end
local armies=main._myActionState and main._myActionState[2]
if armies then for i=0,armies:get_Count()-1 do local a=armies:get_Item(i)
 if a[5]==45 then out[#out+1]='own_beacon_army='..a[1]..' state='..a[4]..' target='..a[6]..' end='..a[11] end
end end
local scouts=main._myScoutInfoList
if scouts then for i=0,scouts:get_Count()-1 do local s=scouts:get_Item(i)
 out[#out+1]='scout_start='..s[1]..' end='..s[2]
end end
return table.concat(out,'\n')
