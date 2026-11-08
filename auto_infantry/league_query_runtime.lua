-- Manual league browsing only. Installation never sends a request and identities remain in this session.
local api={};REA_LEAGUE_QUERY=api
local mm=CSLTypes.ModelManager.sharedInstance();local account=mm:getModel(CSLTypes.MainModel)
local login=account.mTLoginRsp;local main=mm:getModel(CSLTypes.SLGMainModel);local world=main.mTSLGLoginMapRsp
local model=mm:getModel(CSLTypes.SLGLeagueModel);local ctrl=CSLTypes.SLGLeagueController.getInstance()
local choices={};local members={};local serial=0;local pending,before,selected,activeMember

-- Encode only public league/member summaries, never internal TUserID objects.
local function json(v)
 local t=type(v)
 if t=='string'then return '"'..v:gsub('[%z\1-\31\\"]',function(c)return string.format('\\u%04x',c:byte())end)..'"'end
 if t=='number'then return string.format(v==math.floor(v)and'%.0f'or'%.17g',v)end
 if t=='boolean'then return tostring(v)end
 if t~='table'then return 'null'end
 local rows={};if next(v)==nil or v[1]~=nil then
  for _,x in ipairs(v)do rows[#rows+1]=json(x)end;return '['..table.concat(rows,',')..']'
 end
 for k,x in pairs(v)do rows[#rows+1]=json(k)..':'..json(x)end
 return '{'..table.concat(rows,',')..'}'
end
local function count(v)return v and v:get_Count()or 0 end
local function text(v)return v and CSLTypes.YXSUtils.GBK2UTF8(v)or''end
local function now()return CSLTypes.SLGMainModel.GetMapTimeNow()end

-- Account and map transitions invalidate every old roster handle before another request can be sent.
local function guard()
 assert(mm:getModel(CSLTypes.MainModel)==account and account.mTLoginRsp==login and
  main.mTSLGLoginMapRsp==world and main.mIsMapLoaded,'账号或地图已改变，请重新连接助手')
end

-- Obtain the native numeric message ID without inventing request formats.
local function code(method,key)
 local fn=package.loaded.SLGLeagueController.__instanceDict[method]
 for i=1,12 do local n,v=debug.getupvalue(fn,i);if not n then break end
  if n=='T_ID'then return assert(v[key],'联盟查询协议未确认')end
 end
 error('联盟查询协议未确认')
end

-- A click explicitly requests the current world's public league list; no member details are queried here.
function api.leagues()
 guard();pending='leagues';before=model:getTSLGGetLeagueListBriefInfoRsp();members={};activeMember=nil;selected=nil
 local map=main:getTMapGameDataID();assert(map,'当前地图信息未就绪')
 local msg=code('sendTSLGGetLeagueListBriefInfoReq','E_SVR_MSG_ID_SLG_GET_LEAGUE_LIST_BRIEF_INFO')
 ctrl:sendTSLGGetLeagueListBriefInfoReq()
 return json({code=msg,scope='map',map_id=map[1],zone_id=map[2]})
end

-- Show a fresh public league list and record only returned league IDs as selectable targets.
function api.league_snapshot()
 guard();assert(pending=='leagues','尚未发起联盟列表查询')
 local r=model:getTSLGGetLeagueListBriefInfoRsp()
 if not r or r==before then return json({ready=false})end
 assert(r[1]==0,'联盟列表查询失败')
 local rows={};choices={}
 for i=0,count(r[2])-1 do local l=r[2]:get_Item(i)
  choices[l[1]]={name=text(l[2]),total=l[4]}
  rows[#rows+1]={league_id=l[1],name=text(l[2]),member_count=l[4]}
 end
 pending=nil
 return json({ready=true,leagues=rows,own_league_id=main:getMyLeagueId(),confirmed_ms=now()})
end

-- Keep the own full-roster request separate from the native other-league public-brief request.
function api.roster(id)
 guard();local own=main:getMyLeagueId();if id==0 then id=own end
 assert(id and id>0,'当前账号尚未加入联盟')
 assert(id==own or choices[id],'请先加载联盟列表并选择联盟')
 selected=id;members={};activeMember=nil
 if id==own then
  pending='own';before=model:GetTSLGGetLeaguePlayerListInfoRsp()
  local msg=code('sendTSLGGetLeaguePlayerListInfoReq','E_SVR_MSG_ID_SLG_GET_LEAGUE_PLAYER_LIST_INFO')
  ctrl:sendTSLGGetLeaguePlayerListInfoReq(nil)
  return json({code=msg,scope='own',league_id=id})
 end
 pending='public';local dict=model._tSLGGetLeagueBriefInfoRspDic
 before=dict and dict:ContainsKey(id)and dict:get_Item(id)or nil
 local msg=code('sendTSLGGetLeagueBriefInfoReq','E_SVR_MSG_ID_SLG_GET_LEAGUE_BRIEF_INFO')
 ctrl:sendTSLGGetLeagueBriefInfoReq(id)
 return json({code=msg,scope='public',league_id=id})
end

-- Save session-local selection handles, keeping public member lists distinct from a full membership claim.
function api.roster_snapshot()
 guard();assert(pending=='own'or pending=='public','尚未发起成员查询')
 local own=pending=='own';local r
 if own then assert(main:getMyLeagueId()==selected,'当前联盟已改变，请重新加载');r=model:GetTSLGGetLeaguePlayerListInfoRsp()
 else local d=model._tSLGGetLeagueBriefInfoRspDic;r=d and d:ContainsKey(selected)and d:get_Item(selected)or nil end
 if not r or r==before then return json({ready=false})end
 assert(r[1]==0,'联盟成员查询失败')
 if not own then assert(r[2]and r[2][1]==selected,'联盟成员资料不匹配')end
 local rows={};local list=own and r[2]or r[3]
 for i=0,count(list)-1 do local row=list:get_Item(i);serial=serial+1
  members[serial]=row[1]
  rows[#rows+1]={member_key=serial,name=text(row[2])}
 end
 local label=own and'本盟'or text(r[2][2]);pending=nil
 return json({ready=true,league_id=selected,name=label,public=not own,members=rows,confirmed_ms=now()})
end

-- Only an explicitly selected member from the latest loaded roster can initiate a profile query.
function api.member_identity(key)
 guard();local u=assert(members[key],'成员名单已失效，请重新加载')
 return json({u[1],u[2],u[3],u[4]})
end

-- Only a cache miss calls the native selected-member profile request.
function api.member(key)
 guard();local identity=assert(members[key],'成员名单已失效，请重新加载')
 activeMember=key;REA_PLAYER_QUERY.bind_member(identity)
 return REA_PLAYER_QUERY.profile(0)
end

-- The player adapter requires a new profile with the selected member's exact platform identity.
function api.member_snapshot(key)
 guard();assert(activeMember==key and members[key],'成员选择已改变，请重新查询')
 return REA_PLAYER_QUERY.snapshot(0)
end
return 'league_query_api_installed'
