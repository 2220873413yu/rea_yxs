-- Installed only for one clicked send, in a uniquely named temporary scope. No UI flags or hooks are changed.
local mm=CSLTypes.ModelManager.sharedInstance()
local account=mm:getModel(CSLTypes.MainModel);local login=account.mTLoginRsp
local game=mm:getModel(CSLTypes.GameModel)
local function stage()return package.loaded.HeroPalaceItem.__instanceDict.getCurrentStageName({})end
assert(login and login[1]==0 and stage()=='GameSceneStage','请先进入实际战斗，选将、结算和大厅不能发送')
assert(not game:isByStander(),'当前处于观战状态，未发送')
local room,tableId,gameId=game:getRoomId(),game:getTableId(),game:getGameID()
assert(room~=nil and tableId~=nil and gameId~=nil,'战斗房间信息未确认，未发送')
local uid=account:getMainParam().myUserInfo.stUID
assert(uid and type(uid[1])=='number'and uid[1]>0,'战斗聊天身份未确认，未发送')
local ownUin=uid[1];local identity={uid[1],uid[2],uid[3],uid[4]};local sent=false;local api={}

-- Fence queued work to the exact account and battle captured for this click, without changing either.
function api.check()
 assert(mm:getModel(CSLTypes.MainModel)==account and account.mTLoginRsp==login,'账号已变化，不再发送')
 local live=account:getMainParam().myUserInfo.stUID
 assert(live and live[1]==identity[1]and live[2]==identity[2]and live[3]==identity[3]and live[4]==identity[4],'账号身份已变化，不再发送')
 assert(stage()=='GameSceneStage'and mm:getModel(CSLTypes.GameModel)==game and
  game:getRoomId()==room and game:getTableId()==tableId and game:getGameID()==gameId,'战斗房间已变化，不再发送')
 assert(not game:isByStander(),'当前处于观战状态，不再发送')
 return 'same_battle'
end

-- One click owns at most one native call. Preserve native duplicate-message checks and all input restrictions.
function api.send(message)
 api.check();assert(not sent,'本次消息已经提交，不会重复发送')
 local native=CSLTypes.YXSUtils.UTF82GBK(message)
 local controller=CSLTypes.ChatController.getInstance()
 local now=math.floor(CSLTypes.RefreshTimer.getServerTimeNow())
 assert(not(controller.chatStringCache==native and type(controller.chatTimestamp)=='number'and
  now-controller.chatTimestamp<5),'原生规则：相同内容五秒内不重复发送，本次未发出')
 sent=true
 controller:sendChatMsg(native)
 return 'native_called_once'
end

__CHAT_API__=api
return string.format('{"own_uin":%.0f}',ownUin)
