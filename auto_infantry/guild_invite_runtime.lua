-- Reuse the game's invite handlers without constructing or displaying a game dialog.
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.MainModel)
local guild=manager:getModel(CSLTypes.GuildModel)
local login=assert(main.mTLoginRsp,'当前账号未登录')
local uid=assert(main.myUserId,'无法核对当前账号')
local identity={uid[1],uid[2],uid[3],uid[4]}
local info=assert(guild:getTGuildInfoRsp(),'当前公会资料未加载')
local function guildId(rsp)
 local entry=rsp and rsp[2] and rsp[2][1]
 return entry and entry[2]
end
local id=assert(guildId(info),'当前公会未确认')
assert(tostring(id)~='' and tostring(id)~='0','当前公会未确认')
local memberType=assert(package.loaded.GuildMemberDialog or CSLTypes.GuildMemberDialog,'无法读取游戏的公会权限定义')
local inviteType=CSLTypes.GuildInviteDialog
local inviteMethods=assert((package.loaded.GuildInviteDialog or inviteType).__instanceDict,'游戏邀请处理程序不可用')
local lookup=assert(inviteMethods.OnPlayerIdInputChanged,'游戏玩家查询不可用')
local submit=assert(inviteMethods.OnInviteClick,'游戏邀请处理程序不可用')
local types
for i=1,24 do
 local k,v=debug.getupvalue(memberType.__instanceDict.Start,i)
 if k=='T_TYPE' then types=v;break end
end
local authority=assert(types and types.E_GUILD_AUTH_TYPE_INVITE,'未找到游戏邀请权限')
local api={}
local target,attempted
local requiredScope=('__GUILD_INVITE_SCOPE__'):match('^_REA_GUILD_INVITE_[0-9a-f]+$')

-- Recheck both the account and current guild, including changes while the user reviews the ID.
function api.check()
 if requiredScope then assert(_G[requiredScope],'网页接单的账号会话已结束').check() end
 local current=manager:getModel(CSLTypes.MainModel)
 local u=current and current.myUserId
 assert(login[1]==0 and current==main and current.mTLoginRsp==login and u,'游戏账号会话已变化')
 for i=1,4 do assert(u[i]==identity[i],'游戏账号已变化') end
 assert(manager:getModel(CSLTypes.GuildModel)==guild and guildId(guild:getTGuildInfoRsp())==id,'当前公会已变化')
 return 'same'
end

-- The native handlers can run without a member dialog. Use the live connection and the game's role permission.
local function checkAvailability()
 api.check()
 local stage=memberType.__instanceDict.getCurrentStageName({})
 assert(stage and stage~='' and stage~='LoginStage','请先登录游戏')
 assert(TKLua.LuaGameSystem.Instance:IsConnected() and
  not CSLTypes.LoginManager.sharedInstance():isReplayLogining(),'游戏未连接或正在重连')
 assert(CSLTypes.GuildModel.HasAuthority(authority,guild:getTGuildInfoRsp()[4]),'当前角色没有公会邀请权限')
end

-- Check availability without looking up a player or sending a game request.
function api.ready()
 checkAvailability()
 return 'ready'
end

-- Supply the original handlers only the validated text they read from an input field.
local function inviteInput(value)
 return {mPlayerIdInput={text=value}}
end

-- Stage a single ID and perform the ordinary lookup without altering the game's current UI.
function api.prepare(value)
 checkAvailability()
 assert(not target and value:match('^%d+$') and #value==12 and value:find('[1-9]'),'玩家 ID 无效')
 target=value
 lookup(inviteInput(target),target)
 return 'prepared'
end

-- Consume confirmation before handing the same ID to the original invite handler.
function api.confirm()
 local ok,reason=pcall(function()
  checkAvailability()
  assert(not attempted and target,'没有可确认的邀请，请重新准备')
 end)
 if not ok then return 'not_sent:'..tostring(reason) end
 attempted=true
 submit(inviteInput(target))
 return 'submitted'
end

__GUILD_INVITE_API__=api
return 'guild_invite_ready'
