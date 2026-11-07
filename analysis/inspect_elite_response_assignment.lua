-- Trace the assignment from server response to EliteLevelModel and inspect protocol schema declarations.
local out={};local u=require('jit.util')
local _,hall=debug.getupvalue(CSLTypes.HallMsgMgr.sendSitDownMsg,1)
for _,key in ipairs({'handleEliteSitdown','parseSitDownRsp','handleSitDownRsp'}) do
 local f=hall.__instanceDict[key];out[#out+1]='FUNCTION '..key..' '..type(f)
 if type(f)=='function' and u.funcinfo(f).bytecodes then
  for i=-1,-140,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
  for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end
local _,ctor=debug.getupvalue(CSLTypes.HallMsgMgr.sendSitDownMsg,2)
local p=CSLNew(ctor)
for k,v in pairs(p) do if type(k)=='number' then out[#out+1]='PVE_FIELD '..k..' '..type(v)..(type(v)=='number' and ('='..v) or '') end end
local d=package.loaded.DBSearcher.__instanceDict
for k,f in pairs(d) do if type(k)=='string' and type(f)=='function' and k:lower():find('elite') then out[#out+1]='DB_METHOD '..k end end
local proto=package.loaded.RoomClientProtoDes
out[#out+1]='PROTO '..type(proto)
if type(proto)=='table' then
 local count=0;for k,v in pairs(proto) do if count<20 then out[#out+1]='PROTO_KEY '..tostring(k)..' '..type(v);count=count+1 end end
end
return table.concat(out,'\n')
