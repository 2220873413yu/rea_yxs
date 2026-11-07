-- Entering the authorized fight unloads the world view; retain the account fence without requiring that view to stay loaded.
local api=assert(REA_TRIAL_ONE_LAYER)
assert(api.challengeSent and not api.skipSent,'Unexpected phase; no skip sent')
local old,index
for i=1,40 do local n,v=debug.getupvalue(api.status,i);if not n then break end;if n=='bound'then old,index=v,i end end
assert(old,'Original account fence missing')
local values={}
for i=1,20 do local n,v=debug.getupvalue(old,i);if not n then break end;values[n]=v end
local account,login,main=values.account,values.login,values.main
assert(account and account.mTLoginRsp==login,'Account changed')
local sit=assert(main:getTSLGSitDownRsp())
assert(sit[1]==0 and sit[11] and sit[11][1]==10010010 and sit[11][6]==16,'Not the authorized first trial battle')
local uid=account.myUserId
assert(uid,'Current identity missing')
local id={uid[1],uid[2],uid[3],uid[4]}
local function battleAccountFence()
 local live=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.MainModel)
 local u=live.myUserId
 assert(live==account and live.mTLoginRsp==login and u and u[1]==id[1] and u[2]==id[2] and u[3]==id[3] and u[4]==id[4],'Account changed; stop')
end
debug.setupvalue(api.status,index,battleAccountFence)
return 'battle_account_fence_preserved; world_view_may_unload'
