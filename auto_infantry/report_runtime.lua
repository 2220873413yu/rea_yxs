-- Native ground-world military report adapter. Installation and local snapshots never send requests.
local api={};REA_REPORT=api
local mm=CSLTypes.ModelManager.sharedInstance()
local account=mm:getModel(CSLTypes.MainModel);local login=account.mTLoginRsp
local main=mm:getModel(CSLTypes.SLGMainModel);local world=main.mTSLGLoginMapRsp
local buildings=mm:getModel(CSLTypes.SLGBuildingsModel)
local db=CSLTypes.DBSearcher.sharedInstance()
local controller=CSLTypes.SLGBuildingsController.getInstance()
local before,approved,approvedAt
local refreshing=false

-- Require this same authenticated world even when a timer expires after scene/account changes.
local function guard()
 assert(mm:getModel(CSLTypes.MainModel)==account and account.mTLoginRsp==login and
  main.mTSLGLoginMapRsp==world and main.mIsMapLoaded,'Account session changed; reconnect the helper')
end
local function now()return CSLTypes.SLGMainModel.GetMapTimeNow()end

-- Count native reward eligibility, not merely unclaimed flags: informational entries may have no reward.
local function counts(r)
 local total={0,0,0};local pending={0,0,0};local eligible=0
 for i=0,r[2]:get_Count()-1 do local row=r[2]:get_Item(i);local cfg=db:searchMilitaryNewsItemInfo(row[2])
  assert(cfg,'军报分类配置未确认，未领取')
  local category=cfg[2]
  assert(category==1 or category==2 or category==3,'军报分类未知，未领取')
  total[category]=total[category]+1
  if (cfg[4]==3 or cfg[4]==5 or cfg[4]==6)and row[5]==0 and row[4]and row[4]:get_Count()>0 then
   eligible=eligible+1;pending[category]=pending[category]+1
  end
 end
 return string.format('{"ready":true,"total":%d,"claimable":%d,"military":%d,"internal":%d,"event":%d,"military_pending":%d,"internal_pending":%d,"event_pending":%d,"confirmed_ms":%.0f}',
  r[2]:get_Count(),eligible,total[1],total[2],total[3],pending[1],pending[2],pending[3],now()),eligible
end

-- Obtain a full authoritative list once per authorized timer, avoiding cumulative incremental cache counts.
function api.refresh()
 guard();approved=nil;approvedAt=nil;before=buildings:getTSLGGetAllEmailRsp();refreshing=true
 controller:sendTSLGGetAllEmailReq(0,0)
 return '{"code":11045}'
end

-- Called only after the attributed wire response; local waiting never sends another list request.
function api.confirm()
 guard();assert(refreshing,'尚未发起本轮军报查询，未领取');local r=buildings:getTSLGGetAllEmailRsp()
 if not r or r==before then return '{"ready":false}'end
 assert(buildings:getmapId4MilitaryNews()==math.floor(main:getCurrentMapId()),'军报地图已改变，未领取')
 assert(r[1]==0 and r[5]==0,'军报列表未成功确认，未领取')
 local text=counts(r);approved=r;approvedAt=now();refreshing=false;return text
end

-- Submit the native one-key receive arguments (id=0, mailType=0, getAll=1) exactly once per fresh list.
function api.claim()
 guard();local r=buildings:getTSLGGetAllEmailRsp()
 assert(buildings:getmapId4MilitaryNews()==math.floor(main:getCurrentMapId()),'军报地图已改变，未领取')
 assert(approved and r==approved and approvedAt and now()>=approvedAt and now()-approvedAt<=10000,'军报数据已过期，未领取')
 local _,pending=counts(r);assert(pending>0,'没有可领取军报，未发送')
 approved=nil;approvedAt=nil
 controller:sendTSLGGetEmailRewardReq(0,0,1)
 return '{"code":11046}'
end
return 'report_api_installed'
