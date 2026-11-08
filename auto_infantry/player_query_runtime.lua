-- On-demand public profile adapter. Installation never sends a request or changes an automation switch.
local api={};REA_PLAYER_QUERY=api
local mm=CSLTypes.ModelManager.sharedInstance();local account=mm:getModel(CSLTypes.MainModel)
local login=account.mTLoginRsp;local main=mm:getModel(CSLTypes.SLGMainModel);local world=main.mTSLGLoginMapRsp
local db=CSLTypes.DBSearcher.sharedInstance();local target,uid,before
local own=account.myUserId
local ownIdentity=own and {own[1],own[2],own[3],own[4]}

-- Serialize only explicit public hero fields; internal account identifiers never leave this adapter.
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

-- Public profiles belong to the logged-in account connection, independently of world-map readiness.
local function guard()
 if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.check()end
 assert(mm:getModel(CSLTypes.MainModel)==account and login and login[1]==0 and account.mTLoginRsp==login,
  '账号已改变或尚未登录，请重新读取账号')
 if ownIdentity then local live=account.myUserId
  assert(live and live[1]==ownIdentity[1]and live[2]==ownIdentity[2]and live[3]==ownIdentity[3]and live[4]==ownIdentity[4],'账号身份已改变')
 end
end

-- Return local login/cache scope only; never enter a map or request game data.
function api.login_context()
 guard();assert(account.myUserId,'当前账号尚未登录')
 local stage=package.loaded.HeroPalaceItem.__instanceDict.getCurrentStageName({})
 assert(stage~='LoginStage','请先登录游戏')
 local zone=CSLTypes.QQGameSystem.getSystemInstance():getCurZoneID();local mapId=0
 local owner=world and world[5]and world[5][1];local me=account.myUserId
 if owner and owner[1]==me[1]and owner[2]==me[2]and owner[3]==me[3]and owner[4]==me[4]then
  local scope=main:getTMapGameDataID();if scope then mapId=scope[1];zone=scope[2]end
 end
 return json({zone_id=zone,map_id=mapId})
end

-- Reuse only a successful profile's exact public-ID mapping; always fetch fresh details afterwards.
function api.resolve(id)
 guard();assert(type(id)=='number'and id>0 and id<=9007199254740991 and id==math.floor(id),'用户ID格式无效')
 if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.begin()end
 target=id;uid=nil;before=nil
 local r=account:getCurrUserProfileRsp()
 if r and r[1]==0 and r[17]==id and r[2]and r[2][1]then uid=r[2][1]end
 return json({known=uid~=nil})
end

-- Bind only an identity already returned by the league roster adapter; member details still require a fresh reply.
function api.bind_member(identity)
 guard();assert(main and main.mIsMapLoaded and main.mTSLGLoginMapRsp==world,'账号或地图已改变，请重新连接助手')
 assert(type(identity)=='table'and((type(identity[1])=='number'and identity[1]~=0)or
  (type(identity[2])=='string'and identity[2]~='')),'成员身份未返回')
 if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.begin()end
 target=0;uid=identity;before=nil
end

-- Use the native friend-ID lookup; no friendship request is sent and no nearby IDs are enumerated.
function api.lookup(id)
 guard();assert(type(id)=='number'and id>0 and id<=9007199254740991 and id==math.floor(id),'用户ID格式无效')
 target=id;uid=nil;before=nil
 local fn=package.loaded.FriendController.__instanceDict.sendTFindUserInfoReq;local code
 if REA_PLAYER_QUERY_UI then code=REA_PLAYER_QUERY_UI.lookup_code()end
 for i=1,12 do local n,v=debug.getupvalue(fn,i);if not n then break end;if n=='T_ID'then code=v.E_SVR_MSG_ID_FIND_GAME_USER_INFO end end
 assert(type(code)=='number','用户ID查询协议未确认')
 local ctrl=CSLTypes.FriendController.sharedInstance()
 if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.send(function()ctrl:sendTFindUserInfoReq(id)end)
 else ctrl:sendTFindUserInfoReq(id)end
 return json({code=code})
end

-- Follow the native chat player-detail arguments, rather than the separate ranking-list visibility gate.
function api.profile(id)
 guard();assert(id==target,'查询目标已改变')
 if not uid then
  local list=mm:getModel(CSLTypes.FriendSystemModel):GetVecFindUserInfo()
  for i=0,count(list)-1 do local row=list:get_Item(i)
   if row.lFriendSequence==id and row.iRet==0 and row.stUserSimpleProfile then uid=row.stUserSimpleProfile[1];break end
  end
 end
 if not uid then return json({ready=false})end
 before=account:getCurrUserProfileRsp()
 local zone=CSLTypes.QQGameSystem.getSystemInstance():getCurZoneID()
 local ctrl=CSLTypes.HallMsgMgr.sharedInstance()
 if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.send(function()ctrl:sendTUserProfileReq(uid,zone,true,false,true,true)end)
 else ctrl:sendTUserProfileReq(uid,zone,true,false,true,true)end
 return json({ready=true,code=754})
end

-- Resolve equipped gem records by their actual instance IDs, rather than by another hero's template ID.
local function hero(h,role,gems)
 local cfg=db:searchHeroInfo(h[5]);local row={role=role,name=cfg and text(cfg[7])or tostring(h[5]),
  hero_id=h[5],group_id=h[1],star=h[2],level=h[3],power=h[7],gems={},equipment={}}
 local records={}
 for i=0,count(gems)-1 do local g=gems:get_Item(i);records[g[1]]=g end
 for i=0,count(h[6])-1 do local slot=h[6]:get_Item(i);local g=records[slot[4]]
  local gem={slot=slot[3],unlocked=slot[1],record_id=slot[4],name=slot[1]and'空槽'or'未解锁'}
  if slot[4]and slot[4]>0 then
   gem.name='资料未返回'
   if g and g[5]==h[5]then local c=db:searchGemInfo(g[2]);gem.name=c and text(c[6])or tostring(g[2]);gem.level=g[4];gem.config_id=g[2]end
  end
  row.gems[#row.gems+1]=gem
 end
 for i=0,count(h[8])-1 do local e=h[8]:get_Item(i);local c=e[4]>0 and db:searchTNewPlay_Equip(e[4])or nil
  row.equipment[#row.equipment+1]={slot=e[2],name=c and text(c[2])or(e[4]>0 and'配置未知'or'空槽'),config_id=e[4]}
 end
 return row
end

-- Saved UID arrays do not retain native TUserID metadata; compare all four actual protocol fields exactly.
local function sameIdentity(a,b)
 if type(a)~='table'or type(b)~='table'then return false end
 if type(a[1])~='number'or type(a[2])~='string'or type(a[3])~='number'or type(a[4])~='number'then return false end
 if a[1]==0 and a[2]==''then return false end
 return a[1]==b[1]and a[2]==b[2]and a[3]==b[3]and a[4]==b[4]
end

-- Return the already resolved identity to the private cache layer only; no network request or UI projection.
function api.identity(id)
 guard();assert(id==target and uid,'尚未查询该玩家资料')
 local r=account:getCurrUserProfileRsp()
 assert(r and r[1]==0 and r[2]and sameIdentity(uid,r[2][1]),'缓存身份未能确认')
 return json({uid[1],uid[2],uid[3],uid[4]})
end

-- Expose only a newly returned, identity-matched profile, retaining strongest and showcase as distinct roles.
function api.snapshot(id)
 guard();assert(id==target and uid,'尚未查询该玩家资料')
 local r=account:getCurrUserProfileRsp()
 if not r or r==before or r[1]~=0 or not sameIdentity(uid,r[2][1])then return json({ready=false})end
 local p=r[2];local rows={}
 if p[10]and p[10][5]and p[10][5]>0 then rows[#rows+1]=hero(p[10],'最强武将',p[11])end
 for i=0,count(p[25])-1 do rows[#rows+1]=hero(p[25]:get_Item(i),'展示武将'..(i+1),p[26])end
 local now=CSLTypes.RefreshTimer and math.floor(CSLTypes.RefreshTimer.getServerTimeNow()*1000)or CSLTypes.SLGMainModel.GetMapTimeNow()
 return json({ready=true,display_id=id>0 and id or r[17],nickname=text(r[5]),heroes=rows,confirmed_ms=now})
end
return 'player_query_api_installed'
