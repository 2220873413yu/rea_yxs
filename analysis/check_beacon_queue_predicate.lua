-- Evaluate the native read-only predicate on synthetic lists; never alter the real model or send a request.
local out={};local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local original=m.mTSLGGetBeaconTowerInfoRsp
local predicate=package.loaded.SLGMainModel.__instanceDict.checkMaxFengHuoTaiArmyCount
for objectType=1010,1013 do
 local results={}
 for state=0,4 do
  local event={[1]={[3]=objectType},[3]=state}
  local rows={get_Count=function() return 1 end,get_Item=function() return event end}
  local fake={mTSLGGetBeaconTowerInfoRsp={[4]=rows,[6]=1}}
  results[#results+1]=state..':'..tostring(predicate(fake))
 end
 out[#out+1]='object_type='..objectType..' full_with_one_slot='..table.concat(results,',')
end
assert(m.mTSLGGetBeaconTowerInfoRsp==original,'Real beacon model unexpectedly changed')
out[#out+1]='real_beacon_cache_unchanged=true'
return table.concat(out,'\n')
