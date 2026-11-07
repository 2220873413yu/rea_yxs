-- Inspect the final elite-room serializer and response handling without invoking either sender.
local out={};local u=require('jit.util')
for _,key in ipairs({'sendEliteSitDownMsg','changeRoomIdAccordingEnv','sendSitDownMsg','sendTFiendStartGameReq'}) do
 local ok,f=pcall(function() return CSLTypes.HallMsgMgr[key] end)
 out[#out+1]='FUNCTION HallMsgMgr.'..key..' '..type(f)
 if ok and type(f)=='function' then
  local info=u.funcinfo(f);out[#out+1]='INFO params='..tostring(info.params)..' bytecodes='..tostring(info.bytecodes)
  if info.bytecodes then
   for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end
    if type(v)=='string' then out[#out+1]='K '..i..' '..v end
   end
   for i=1,15 do local n,v=debug.getupvalue(f,i);if not n then break end
    out[#out+1]='UP '..i..' '..n..' '..type(v)
    if type(v)=='table' and n=='T_ID' then for k,id in pairs(v) do
     if type(k)=='string' and (k:find('ELITE') or k:find('SIT_DOWN') or k:find('SITDOWN')) then out[#out+1]='PROTOCOL '..k..'='..tostring(id) end
    end end
   end
   for pc=1,info.bytecodes-1 do local bc=u.funcbc(f,pc)
    out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
     math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
   end
  end
 end
end
return table.concat(out,'\n')
