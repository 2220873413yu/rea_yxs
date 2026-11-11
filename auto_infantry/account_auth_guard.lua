-- Scope identity-cache repair and response observation to one helper-requested authentication.
if not REA_ACCOUNT_LOGIN_GUARD then
 local G={}

 -- Restore only our own dispatcher and listener; credentials and saved account files are never changed.
 function G.close()
  local s=G.current
  if not s then return end
  s.active=false
  if s.sender.sendData==s.wrapper then s.sender.sendData=s.original end
  if s.handler then s.handlers:Remove(s.handler) end
  G.current=nil
 end

 -- Block native reconnect immediately, including calls made by the native logout routine itself.
 function G.stop()
  if G.current then G.current.stopped=true end
 end

 -- Return credential-free diagnostics only; request identity and token stay in the client closure.
 function G.status()
  local s=G.current
  return s and {sent=s.sent,ret=s.ret,error=s.error or '',matched=s.matched} or
   {sent=false,ret=-999,error='',matched=false}
 end

 -- Observe one native login response and validate identity immediately before its one original send.
 function G.install(expectedSdk)
  assert(not G.current,'An authentication guard is already active')
  assert(expectedSdk==1 or expectedSdk==2,'Unsupported SDK provider')
  CSLTypes.LoginManager.sharedInstance() -- Ensure its ordinary response handler exists before adding ours.
  local init=assert(package.loaded.LoginManager.__instanceDict.initialize,'Login handler unavailable')
  local loginId
  for i=1,20 do local name,v=debug.getupvalue(init,i);if name=='T_ID' then loginId=v.E_SVR_MSG_ID_LOGIN;break end end
  assert(loginId~=nil and tostring(loginId)=='2','Native login protocol changed')
  local sender=assert(package.loaded.MsgManager,'Native message dispatcher unavailable')
  sender=sender.__instanceDict or sender
  local original=assert(sender.sendData,'Native message sender unavailable')
  assert(original==CSLTypes.MsgManager.sendData,'Native message dispatcher differs')
  local proto=CSLTypes.ProtoController
  local handlers=assert(proto.recvSwitch:get(loginId),'Native login handlers unavailable')
  local s={active=true,sender=sender,original=original,handlers=handlers,sent=false,ret=-999,matched=false}

  -- Let the game's own handler process the same response; only remember the first attributed result.
  local function receive(self,rsp)
   if not self.active or not self.sent or self.ret~=-999 then return end
   local ret=rsp and tonumber(rsp[1])
   if not ret then self.error='invalid_login_response';self.stopped=true;return end
   self.ret=ret
   if ret~=0 then self.stopped=true end
  end

  -- A changed/mismatched SDK context must fail closed, never rewrite the request token or retry it.
  local function checkIdentity(body)
   local a=CSLTypes.ApolloLoginController.getInstance()
   local sdk=a:getAccountInfo()
   if not sdk or sdk.flag~=0 or sdk.platform~=expectedSdk or type(sdk.open_id)~='string' or sdk.open_id=='' then
    return false,'sdk_identity_unavailable'
   end
   local token=sdk:GetAccessToken()
   if type(token)~='string' or token=='' or not body or body[1]~=token then return false,'token_identity_mismatch' end
   -- New authorization is already complete. Invalidate both local identity caches before encoding the header.
   a:clearAccountInfoCache()
   local fresh=a:getAccountInfo()
   if not fresh or fresh.open_id~=sdk.open_id or fresh.platform~=sdk.platform or fresh:GetAccessToken()~=token then
    return false,'sdk_identity_changed'
   end
   local tickets=CSLTypes.TicketsProtocol.getInstance()
   tickets:Clear()
   if tickets:getOpenId()~=fresh.open_id or tickets:getAccessToken()~=token then return false,'token_identity_mismatch' end
   return true
  end

  s.wrapper=function(id,body,noEncrypt)
   if id~=loginId or not s.active then return original(id,body,noEncrypt) end
   if s.stopped or s.sent or s.error then return end -- Native retries are blocked, not just Python retries.
   local ok,matched,reason=pcall(checkIdentity,body)
   if not ok or not matched then s.error=ok and reason or 'identity_check_failed';s.stopped=true;return end
   s.matched=true;s.sent=true
   return original(id,body,noEncrypt)
  end
  G.current=s
  local ok=pcall(function()
   local before=handlers:get_Count()
   proto.addRecvCallback(loginId,CSLNewfunc(s,receive))
   s.handler=handlers:get_Item(before)
   assert(s.handler,'Login observer was not installed')
   sender.sendData=s.wrapper
  end)
  if not ok then G.close();error('Unable to install the authentication guard') end
 end

 REA_ACCOUNT_LOGIN_GUARD=G
end
