-- Read the current trip context and model declarations; do not send game requests.
local out={}
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
for k,v in pairs(main) do
 if type(k)=='string' then out[#out+1]='FIELD '..k..' '..type(v) end
end
local methods=package.loaded.SLGMainModel.__instanceDict
for k,v in pairs(methods) do
 if type(k)=='string' and type(v)=='function' and (string.find(k,'Avail') or string.find(k,'Monster') or string.find(k,'Trip') or string.find(k,'Army')) then
  out[#out+1]='METHOD '..k
 end
end
local stage=package.loaded.SLGChooseHeroScene.__instanceDict.getCurrentStage()
out[#out+1]='STAGE '..type(stage)
if type(stage)=='table' then
 for k,v in pairs(stage) do if type(k)=='string' then out[#out+1]='STAGE_FIELD '..k..' '..type(v) end end
end
local ctrl=package.loaded.SLGMainController.__instanceDict
local util=require('jit.util')
for _,key in ipairs({'parseTSLGStartArmyTripRsp','sendTSLGStartArmyTripReq'}) do
 local f=ctrl[key]
 out[#out+1]='FUNCTION '..key
 for i=-1,-65,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v);if n=='T_ID' then out[#out+1]='TRIP_PROTOCOL '..tostring(v.E_SVR_MSG_ID_SLG_START_ARMY_TRIP) end end
end
return table.concat(out,'\n')
