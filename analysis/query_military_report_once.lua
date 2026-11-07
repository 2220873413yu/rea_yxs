-- One read-only incremental list request through the game's native sender; never claim or delete an entry.
local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGBuildingsModel)
local main=mm:getModel(CSLTypes.SLGMainModel)
local r=m:getTSLGGetAllEmailRsp()
assert(main.mIsMapLoaded and m:getmapId4MilitaryNews()==math.floor(main:getCurrentMapId()),'Map changed; do not query')
assert(r and r[1]==0 and r[5]==0 and type(r[3])=='number'and r[3]>0,'No ground-mail cursor confirmed')
CSLTypes.SLGBuildingsController.getInstance():sendTSLGGetAllEmailReq(r[3],0)
return 'one_native_incremental_list_request_sent; no_claim_or_delete'
