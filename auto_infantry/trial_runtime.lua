-- Independent native trial adapter. It never schedules actions or buys/revives/claims anything.
if REA_TRIAL then REA_TRIAL.close() end
local api={};REA_TRIAL=api
local mm=CSLTypes.ModelManager.sharedInstance()
local account=mm:getModel(CSLTypes.MainModel)
local login=account.mTLoginRsp
local uid=assert(account.myUserId)
local identity={uid[1],uid[2],uid[3],uid[4]}
local baseGuard=REA_HELPER_SESSION_VALID
local owned=false
local state={profile_seq=0,available_seq=0,result_seq=0}
local profileRef,available,result,pending,battle,battleBefore,resultBefore,target,attemptedQuest,returnSent

-- Encode only the explicit public snapshots built below, never native account or protocol objects.
local function json(v)
 local t=type(v)
 if t=='nil'then return 'null'elseif t=='boolean'or t=='number'then return tostring(v)
 elseif t=='string'then return '"'..v:gsub('[%z\1-\31\\"]',function(c)return string.format('\\u%04x',string.byte(c))end)..'"' end
 assert(t=='table','Unsupported trial snapshot value')
 local rows={};local array=next(v)==nil or type(next(v))=='number'
 if array then for _,x in ipairs(v)do rows[#rows+1]=json(x)end;return '['..table.concat(rows,',')..']'end
 for k,x in pairs(v)do rows[#rows+1]=json(k)..':'..json(x)end
 return '{'..table.concat(rows,',')..'}'
end

-- Require the same live role throughout scene transitions; private identifiers never leave this closure.
local function accountValid()
 local a=mm:getModel(CSLTypes.MainModel);local u=a.myUserId
 return a==account and a.mTLoginRsp==login and u and u[1]==identity[1] and u[2]==identity[2] and u[3]==identity[3] and u[4]==identity[4]
end
local function check()assert(accountValid(),'Account session changed; reconnect the helper')end
local function model(name)return mm:getModel(CSLTypes[name])end
local function methods(name)
 local c=package.loaded[name]
 if not c then pcall(function()return CSLTypes[name]end);c=package.loaded[name]end
 return assert(c and c.__instanceDict,'Native trial module unavailable: '..name)
end
local tc=methods('SLGTowerController')
local ctrl=methods('SLGMainController')
local chooser=methods('SLGTowerChooseHeroScene')
local hall=methods('HallMsgMgr')
local ready=methods('SLGTowerReadyScene')
local item=methods('SLGChooseHeroItem')
local function count(x)return x and x.get_Count and x:get_Count()or 0 end
local function heroName(id)
 local c=CSLTypes.DBSearcher.sharedInstance():searchHeroInfoByStarAndGroup(1,id)
 return c and CSLTypes.YXSUtils.GBK2UTF8(c[7])or tostring(id)
end

-- World automation is suspended while the trial owns the connection; the original world fence is retained otherwise.
local function trialGuard()return owned and accountValid()or (baseGuard and baseGuard())end
local function worldReady()
 local m=model('SLGMainModel');local r=m.mTSLGLoginMapRsp;local u=r and r[5]and r[5][1]
 return not not(m.mIsMapLoaded and r and r[1]==0 and u and u[1]==identity[1]and u[2]==identity[2]and u[3]==identity[3]and u[4]==identity[4])
end

-- Resolve numeric message codes from the same native senders used by the game.
local function code(fn,needle)
 for i=1,15 do local n,v=debug.getupvalue(fn,i);if not n then break end
  if n=='T_ID'then
   if v['E_SVR_MSG_ID_'..needle]then return v['E_SVR_MSG_ID_'..needle]end
   for k,x in pairs(v)do if type(k)=='string'and k:find(needle,1,true)then return x end end
  end
 end
 error('Native trial protocol unavailable: '..needle)
end
local codes={profile=code(tc.sendTSLGGetQCTQuestProfileInfoReq,'QCT_GET_QUEST_PROFILE'),
 available=code(ctrl.sendTSLGGetAvailHeroListReq,'GET_AVAIL_HERO_LIST'),select=code(tc.sendTSLGQCTChooseTrialHeroReq,'QCT_CHOOSE_TRIAL_HERO'),
 challenge=code(ctrl.sendTSLGSitDownClientReq,'SLG_SITDOWN'),skip=code(ctrl.sendTSLGTimeoutSkipReq,'SLG_TIMEOUT_SKIP')}

-- Mark attempts before native calls; an unacknowledged mutation can never be retried by this adapter.
local function reserve(kind)
 check();assert(owned,'Trial has not been explicitly started');assert(not pending,'Previous trial request remains uncertain')
 pending={kind=kind,code=codes[kind],mutation=kind=='select'or kind=='challenge'or kind=='skip'}
end

-- Capture the trial-specific native response directly; other hero queries and UI callbacks are untouched.
local originalShow,originalContent,originalResult=chooser.show,chooser.setContent,hall.parseTPushPVEResult
local function capture(r)
 if owned and accountValid()and type(r)=='table'and r[2]==target and r[3]==16 and r~=available then
  available=r;state.available_seq=state.available_seq+1
 end
end
local showWrapper=function(r)capture(r);return originalShow(r)end
local contentWrapper=function(self,r)capture(r);return originalContent(self,r)end
chooser.show=showWrapper;chooser.setContent=contentWrapper

-- Bind a fresh battle response to the submitted quest, mode, role and unique room/table before accepting a result.
local function bindBattle()
 local r=model('SLGMainModel'):getTSLGSitDownRsp()
 if attemptedQuest and not battle and r and r~=battleBefore and r[1]==0 and r[11]and r[11][1]==attemptedQuest and r[11][6]==16 then
  battle=r;returnSent=false
 end
end
-- Native dispatchers can retain a pre-hook function; also accept a fresh model result with the same strict battle identity.
local function captureResult(r)
 if owned and accountValid()and r~=resultBefore then
  bindBattle()
  if battle and type(r)=='table'and r[18]==battle[5]and r[19]==battle[6]then
   local info=r[16]
   if not info or (info[9]==16 and (info[10]==0 or info[10]==battle[11][7]))then
    if not result then
     result={ret=r[1],win=r[2],room=r[18],table_id=r[19],quest=attemptedQuest,army_id=battle[11][7]}
     state.result_seq=state.result_seq+1
    end
   end
  end
 end
end
local resultWrapper=function(self,r)
 captureResult(r)
 return originalResult(self,r)
end
hall.parseTPushPVEResult=resultWrapper

-- Start only in the authenticated world. Existing trial selections are read rather than reset or revived.
function api.begin()
 check();assert(worldReady()and not model('GameModel'):isInGame(),'请先手动返回西游幻境地图')
 assert(not pending or not pending.mutation,'上次试炼动作结果不明，请核对游戏并重新连接')
 owned=true;REA_HELPER_SESSION_VALID=trialGuard
 pending=nil;available=nil;result=nil;battle=nil;battleBefore=nil;resultBefore=nil;target=nil;attemptedQuest=nil;returnSent=false
 state.attempts={};state.skip_sent=false
 return json({started=true})
end

-- Query only at explicit state-machine boundaries, never from a passive observer or local status read.
function api.query_profile()
 reserve('profile');tc.sendTSLGGetQCTQuestProfileInfoReq();return json({code=codes.profile})
end
function api.query_available()
 local r=model('SLGTowerModel'):getMainData()
 assert(r and r[1]==0 and count(r[7])==0 and r[5]>0,'无可开始的试炼或本轮已选将')
 reserve('available');target=r[12];available=nil
 ctrl.sendTSLGGetAvailHeroListReq(target,16,0,0)
 return json({code=codes.available,target=target})
end

-- Rank the server's trial-eligible heroes, respecting native action/limit flags and shared soldier stock.
local function candidates()
 assert(available and available[1]==0 and available[2]==target and available[3]==16,'试炼可用名单未确认')
 local rows={}
 for i=0,count(available[4])-1 do local h=available[4]:get_Item(i)
  if item.getActionState(h)==0 and h[9]==false and count(h[2])>0 then
   rows[#rows+1]={id=h[1][1][3],power=h[4],raw=h}
  end
 end
 table.sort(rows,function(a,b)return a.power>b.power or(a.power==b.power and a.id<b.id)end)
 return rows
end
function api.select()
 local r=model('SLGTowerModel'):getMainData()
 assert(r and r[1]==0 and r[12]==target and count(r[7])==0,'试炼名单发生变化')
 local need=CSLTypes.SLGTowerModel.getConsumeSoldierCount();local used,ids={},{}
 local list=CSLNew(CSLTypes.CSLList)
 for _,h in ipairs(candidates())do local s=h.raw[2]:get_Item(0)
  if s[2]-(used[s[1]]or 0)>=need then
   list:Add(h.id);ids[#ids+1]=h.id;used[s[1]]=(used[s[1]]or 0)+need
   if #ids==3 then break end
  end
 end
 assert(#ids==3,'可用英雄或原生所需小兵不足三人')
 reserve('select');tc.sendTSLGQCTChooseTrialHeroReq(list)
 return json({code=codes.select,target=target,heroes=ids})
end

-- Use the strongest available server-confirmed selected hero, once for this next-quest identity.
function api.challenge()
 local r=model('SLGTowerModel'):getMainData()
 assert(r and r[1]==0 and count(r[7])==3,'本轮三名英雄尚未确认')
 assert(worldReady()and not model('GameModel'):isInGame(),'当前尚未返回试炼准备状态')
 assert(type(r[12])=='number'and r[12]>0 and not state.attempts[r[12]],'本层已经尝试，不自动重试')
 assert(not attemptedQuest or(result and result.ret==0 and result.win==true and returnSent),'上一场尚未确认胜利并返回，不继续挑战')
 local best
 for i=0,count(r[7])-1 do local h=r[7]:get_Item(i)
  if h[2]==0 and(not best or h[4]>best[4])then best=h end
 end
 assert(best,'三名试炼英雄均不可出战，请手动处理')
 local _,armyType=debug.getupvalue(ready.onStartBtnClick,1)
 assert(armyType,'试炼原生编队声明已变化')
 local army=CSLNew(armyType);army[1]=best[1][1]
 reserve('challenge');target=r[12];attemptedQuest=target;state.attempts[target]=true;state.skip_sent=false
 battleBefore=model('SLGMainModel'):getTSLGSitDownRsp();resultBefore=model('PVEModel'):getTPushPVEResult()
 battle=nil;result=nil;returnSent=false
 ctrl.sendTSLGSitDownClientReq(target,0,16,army,false,-1)
 return json({code=codes.challenge,target=target,hero_id=army[1]})
end

-- Skip only this still-active owned battle after its native time or round gate; no win/lose value is submitted.
function api.skip()
 bindBattle();assert(battle and not result and not state.skip_sent,'本场不能再次跳过')
 assert(model('SLGMainModel'):getTSLGSitDownRsp()==battle and model('GameModel'):isInGame(),'当前战斗已变化')
 local m=model('SLGMainModel');local now=math.floor(CSLTypes.SLGMainModel.GetMapTimeNow()/1000)
 local at=m:getSkipTime()or 0
 assert((at>0 and now>=at)or model('GameModel'):getRoundCount()>2,'尚未满足原生跳过条件')
 reserve('skip');state.skip_sent=true;ctrl.sendTSLGTimeoutSkipReq()
 return json({code=codes.skip,army_id=battle[11][7],target=attemptedQuest})
end

-- A matching wire response clears only that request; neither a timeout nor an unrelated push can grant a retry.
function api.ack(codeValue,ret)
 check();assert(pending and pending.code==codeValue,'试炼响应无法归属')
 pending=nil;return 'trial_receipt_acknowledged'
end

-- Return through the core native navigation without sharing, opening reward cards or buying anything.
function api.return_after_win()
 check();assert(owned and result and result.ret==0 and result.win==true,'尚未确认本层胜利')
 assert(not returnSent and not model('GameModel'):isInGame(),'尚未完成结算或已经返回')
 returnSent=true;ctrl.backToSLGInResult();return json({returning=true,profile_seq=state.profile_seq})
end

-- Read already-received data only. The worker samples local state; this function never sends a server request.
function api.status()
 check();local m=model('SLGMainModel');local r=model('SLGTowerModel'):getMainData()
 if r and r~=profileRef then profileRef=r;state.profile_seq=state.profile_seq+1 end
 bindBattle()
 captureResult(model('PVEModel'):getTPushPVEResult())
 local heroes={}
 if r and r[1]==0 then for i=0,count(r[7])-1 do local h=r[7]:get_Item(i)
  heroes[#heroes+1]={id=h[1][1],name=heroName(h[1][1]),state=h[2],power=h[4],defeats=h[3]}
 end end
 local now=math.floor(CSLTypes.SLGMainModel.GetMapTimeNow()/1000);local at=m:getSkipTime()or 0
 local rounds=model('GameModel'):getRoundCount()or 0
 return json({profile_seq=state.profile_seq,profile_ret=r and r[1]or -999,available_seq=state.available_seq,
  available_ret=available and available[1]or -999,result_seq=state.result_seq,result=result,
  max_floor=r and r[2]or 0,today_floor=r and r[3]or 0,remaining=r and r[5]or 0,next_quest=r and r[12]or 0,total=r and r[13]or 0,
  heroes=heroes,world_ready=worldReady(),in_game=model('GameModel'):isInGame(),battle_ready=battle~=nil,
  army_id=battle and battle[11][7]or 0,room=battle and battle[5]or 0,table_id=battle and battle[6]or 0,
  server_now_ms=now*1000,skip_at_ms=at*1000,round=rounds,codes=codes,
  can_skip=battle~=nil and not result and model('GameModel'):isInGame()and((at>0 and now>=at)or rounds>2)})
end

-- Remove every native wrapper without querying or changing the game's current battle or interface.
function api.close()
 if chooser.show==showWrapper then chooser.show=originalShow end
 if chooser.setContent==contentWrapper then chooser.setContent=originalContent end
 if hall.parseTPushPVEResult==resultWrapper then hall.parseTPushPVEResult=originalResult end
 if REA_HELPER_SESSION_VALID==trialGuard then REA_HELPER_SESSION_VALID=baseGuard end
 owned=false;return 'trial_closed'
end
return 'trial_api_installed'
