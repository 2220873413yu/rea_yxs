-- Discover local Hall error definitions and serializer field names without invoking a sender.
local out={};local u=require('jit.util');local s=CSLTypes.DBSearcher.sharedInstance()
local f=s.searchHallError
for i=-1,-60,-1 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='ERROR_K '..i..' '..tostring(v) end
for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
 out[#out+1]=string.format('ERROR_BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
end
local _,hall=debug.getupvalue(CSLTypes.HallMsgMgr.sendSitDownMsg,1)
for k,v in pairs(hall) do if type(k)=='string' then out[#out+1]='HALL_KEY '..k..' '..type(v) end end
local meta=getmetatable(hall)
if type(meta)=='table' then for k,v in pairs(meta) do out[#out+1]='HALL_META '..tostring(k)..' '..type(v) end end
local _,ctor=debug.getupvalue(CSLTypes.HallMsgMgr.sendSitDownMsg,5)
local req=CSLNew(ctor)
for k,v in pairs(req) do if type(k)=='string' then out[#out+1]='REQ_KEY '..k..' '..type(v) end end
return table.concat(out,'\n')
