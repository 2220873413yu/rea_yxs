-- Resolve the native enum values; challenge mode and army purpose are distinct protocol fields.
local out={}
local f=package.loaded.SLGTowerMainScene.__instanceDict.gotoChooseHeroScene
for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end
 if type(v)=='table' and v.E_SLG_ARMY_AIM_TYPE_PVE_QUEST_QCT then out[#out+1]='trial_army_aim='..v.E_SLG_ARMY_AIM_TYPE_PVE_QUEST_QCT end
end
local d=package.loaded.SLGMainController.__instanceDict
for k,v in pairs(d)do if type(k)=='string' and k:find('Avail')then out[#out+1]='ROSTER_METHOD '..k end end
for _,name in ipairs({'sendTSLGGetAvailHeroListReq','sendTSLGSitDownClientReq','sendTSLGTimeoutSkipReq'})do
 local f=d[name]
 out[#out+1]='FUNCTION '..name
 for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end
  if n=='T_ID'then for k,x in pairs(v)do if type(k)=='string' and type(x)=='number' and (k:find('SLG_SITDOWN') or k:find('SLG_TIMEOUT_SKIP') or k:find('SLG_GET_AVAIL_HERO'))then out[#out+1]=k..'='..x end end end
 end
end
return table.concat(out,'\n')
