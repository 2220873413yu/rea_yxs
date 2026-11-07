-- Locate all existing elite-entry call sites and inspect whether they pass host/child selection data.
local u=require('jit.util');local out={}
for _,name in ipairs({'EliteFriendListItem','FriendsEliteListItem','PVEChooseHeroInviteFriend','FriendInvitationDialog'}) do
 pcall(function() return CSLTypes[name] end)
end
for name,c in pairs(package.loaded) do if type(name)=='string' and type(c)=='table' then
 local d=c.__instanceDict
 if type(d)=='table' then for k,f in pairs(d) do if type(f)=='function' and u.funcinfo(f).bytecodes then
  local ks={};local found=false
  for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end
   if type(v)=='string' then ks[#ks+1]=v;if v=='sendEliteSitDownMsg' then found=true end end
  end
  if found then
   out[#out+1]='ENTRY '..name..'.'..tostring(k)..' '..table.concat(ks,'|')
   for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
    out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
   end
  end
 end end end
end end
return table.concat(out,'\n')
