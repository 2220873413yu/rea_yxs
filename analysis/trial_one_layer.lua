-- Explicitly authorized one-layer experiment. Each spending operation has a permanent one-shot marker.
if REA_TRIAL_ONE_LAYER then
 assert(not REA_TRIAL_ONE_LAYER.selectSent and not REA_TRIAL_ONE_LAYER.challengeSent,'Trial spending already attempted; do not reset')
 REA_TRIAL_ONE_LAYER.close();REA_TRIAL_ONE_LAYER=nil
end
local mm=CSLTypes.ModelManager.sharedInstance()
local main=mm:getModel(CSLTypes.SLGMainModel)
local account=mm:getModel(CSLTypes.MainModel)
local tower=mm:getModel(CSLTypes.SLGTowerModel)
local pve=mm:getModel(CSLTypes.PVEModel)
local game=mm:getModel(CSLTypes.GameModel)
local scene=CSLTypes.SceneNotifier.getInstance()
local login,world=account.mTLoginRsp,main.mTSLGLoginMapRsp
local ctrl=package.loaded.SLGMainController.__instanceDict
local tc=package.loaded.SLGTowerController.__instanceDict
local api={};REA_TRIAL_ONE_LAYER=api
local available,profileBefore,battleBefore,resultBefore,target,chosen,battle
local observer={class={name='REAOneLayerTrialObserver'}}
local registered=false
local function bound()
 assert(account.mTLoginRsp==login and main.mTSLGLoginMapRsp==world and main.mIsMapLoaded,'Account/world changed; stop')
end
local function count(list)return list and list.get_Count and list:get_Count() or 0 end
local function hex(s)return tostring(s or ''):gsub('.',function(c)return string.format('%02x',string.byte(c))end)end
local function boolean(x)return x and 'true' or 'false'end
local function name(id)
 local c=CSLTypes.DBSearcher.sharedInstance():searchHeroInfoByStarAndGroup(1,id)
 return hex(c and CSLTypes.YXSUtils.GBK2UTF8(c[7]) or '')
end
function observer:updateSelf(param)
 local p=param and param.updateData
 if param and param.id==1060 and type(p)=='table' and p[2]==target and p[3]==16 then available=p end
end
scene:addObserver(observer);registered=true
function api.query_profile()
 bound();assert(not api.profileSent,'Profile query already sent')
 api.profileSent=true;profileBefore=tower:getMainData()
 tc.sendTSLGGetQCTQuestProfileInfoReq()
 return 'profile_query_sent'
end
function api.query_available()
 bound();local r=tower:getMainData()
 assert(r and r~=profileBefore and r[1]==0 and r[5]>0,'No fresh successful trial profile')
 assert(count(r[7])==0,'Trial already has selected heroes; do not overwrite')
 assert(not api.availableSent,'Availability query already sent')
 target=r[12];assert(type(target)=='number' and target>0,'Invalid next quest')
 api.availableSent=true;ctrl.sendTSLGGetAvailHeroListReq(target,16,0,0)
 return 'availability_query_sent'
end
local function candidates()
 assert(available and available[1]==0 and available[2]==target and available[3]==16,'No successful matching trial roster')
 local rows={}
 for i=0,count(available[4])-1 do
  local h=available[4]:get_Item(i)
  local id=h[1][1][3]
  local state=package.loaded.SLGChooseHeroItem.__instanceDict.getActionState(h)
  rows[#rows+1]={id=id,power=h[4],soldier_power=h[7],state=state,limited=h[9],source=h}
 end
 table.sort(rows,function(a,b)if a.power==b.power then return a.id<b.id end;return a.power>b.power end)
 return rows
end
function api.status()
 bound();local r=tower:getMainData();local rows={};local selected={}
 if available and available[1]==0 then for _,h in ipairs(candidates())do
  rows[#rows+1]=string.format('{"id":%d,"name_hex":"%s","power":%d,"soldier_power":%d,"state":%d,"limited":%s}',h.id,name(h.id),h.power,h.soldier_power,h.state,boolean(h.limited))
 end end
 if r then for i=0,count(r[7])-1 do local h=r[7]:get_Item(i)
  selected[#selected+1]=string.format('{"id":%d,"name_hex":"%s","state":%d,"power":%d}',h[1][1],name(h[1][1]),h[2],h[4])
 end end
 local sit=main:getTSLGSitDownRsp();local same=sit and sit~=battleBefore and sit[1]==0 and sit[11] and sit[11][1]==target and sit[11][6]==16
 if api.challengeSent and same and not battle then battle=sit end
 local raw=pve:getTPushPVEResult()
 local result='null'
 if battle and raw and raw~=resultBefore and raw[18]==battle[5] and raw[19]==battle[6] then
  result=string.format('{"ret":%d,"win":%s,"room":%d,"table":%d}',raw[1],boolean(raw[2]),raw[18],raw[19])
  api.finished=true
 end
 local now=math.floor(CSLTypes.SLGMainModel.GetMapTimeNow()/1000)
 local skipAt=main:getSkipTime() or 0;local round=game:getRoundCount() or 0
 return string.format('{"profile_fresh":%s,"profile_ret":%d,"remaining":%d,"today_floor":%d,"next_quest":%d,"candidate_ready":%s,"candidates":[%s],"selected":[%s],"battle_ready":%s,"army":%d,"room":%d,"table":%d,"round":%d,"server_now":%d,"skip_at":%d,"can_skip":%s,"result":%s}',
  boolean(r and r~=profileBefore),r and r[1] or -999,r and r[5] or -1,r and r[3] or -1,r and r[12] or -1,boolean(available~=nil),table.concat(rows,','),table.concat(selected,','),boolean(battle~=nil),battle and battle[11][7] or 0,battle and battle[5] or 0,battle and battle[6] or 0,round,now,skipAt,boolean(battle and game:isInGame() and ((skipAt>0 and now>=skipAt) or round>2)),result)
end
function api.select_three()
 bound();assert(not api.selectSent and not api.challengeSent,'Selection already submitted; do not retry')
 local r=tower:getMainData();assert(r and r[1]==0 and r[12]==target and count(r[7])==0,'Trial profile changed')
 local need=CSLTypes.SLGTowerModel.getConsumeSoldierCount()
 local used={};chosen={};local list=CSLNew(CSLTypes.CSLList)
 for _,h in ipairs(candidates())do
  if h.state==0 and not h.limited and count(h.source[2])>0 then
   local s=h.source[2]:get_Item(0)
   if s[2]-(used[s[1]] or 0)>=need then
    chosen[h.id]=true;list:Add(h.id);used[s[1]]=(used[s[1]] or 0)+need
    if list:get_Count()==3 then break end
   end
  end
 end
 assert(list:get_Count()==3,'Fewer than three eligible heroes with sufficient troops')
 api.selectSent=true;tc.sendTSLGQCTChooseTrialHeroReq(list)
 return 'selection_submitted_once'
end
function api.challenge_once()
 bound();assert(api.selectSent and not api.challengeSent and not api.finished,'Challenge already attempted or not selected')
 local r=tower:getMainData();assert(r and r[1]==0 and r[12]==target and count(r[7])==3,'Confirmed three-hero trial roster unavailable')
 local best
 for i=0,r[7]:get_Count()-1 do local h=r[7]:get_Item(i)
  assert(chosen[h[1][1]],'Server returned a different selected hero')
  if h[2]==0 and (not best or h[4]>best[4]) then best=h end
 end
 assert(best,'No available chosen hero')
 local _,armyType=debug.getupvalue(package.loaded.SLGTowerReadyScene.__instanceDict.onStartBtnClick,1)
 assert(armyType,'Native trial formation declaration missing')
 local army=CSLNew(armyType);army[1]=best[1][1]
 battleBefore=main:getTSLGSitDownRsp();resultBefore=pve:getTPushPVEResult()
 api.challengeSent=true;api.hero=army[1]
 ctrl.sendTSLGSitDownClientReq(target,0,16,army,false,-1)
 return 'one_layer_challenge_submitted'
end
function api.skip_once()
 bound();assert(api.challengeSent and not api.skipSent and not api.finished,'Skip already attempted or battle finished')
 local status=api.status()
 assert(battle and main:getTSLGSitDownRsp()==battle and game:isInGame(),'Current trial battle not active')
 local now=math.floor(CSLTypes.SLGMainModel.GetMapTimeNow()/1000)
 local at=main:getSkipTime() or 0
 assert((at>0 and now>=at) or game:getRoundCount()>2,'Native skip conditions not satisfied')
 api.skipSent=true;ctrl.sendTSLGTimeoutSkipReq()
 return 'native_skip_submitted_once'
end
function api.close()
 if registered then scene:removeObserver(observer);registered=false end
 -- Leave one-shot receipt flags intact to prevent accidental repeat runs; no timers or autonomous actions exist.
 return 'trial_observer_removed; no_retry_or_revive'
end
return 'one_layer_trial_installed'
