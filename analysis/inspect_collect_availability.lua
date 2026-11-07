-- Read candidate travel-time query signatures and enum values, not their senders.
local util=require('jit.util')
local out={}
for _,key in ipairs({'sendTSLGGetAvailHeroListReq','sendTSLGGetAvailHeroListReq2','parseTSLGGetAvailHeroListRsp','parseTSLGResourceInfoRsp'}) do
 local fn=package.loaded.SLGMainController.__instanceDict[key]
 out[#out+1]='FUNCTION '..key..' '..type(fn)
 if type(fn)=='function' then
  for i=-1,-65,-1 do local c=util.funck(fn,i);if c==nil then break end;if type(c)=='string' and not string.find(c,'[\128-\255]') then out[#out+1]='K '..(-i-1)..'='..c end end
  for i=1,10 do local n,v=debug.getupvalue(fn,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v);if n=='T_ID' then out[#out+1]='AVAIL_HERO_PROTOCOL '..tostring(v.E_SVR_MSG_ID_SLG_GET_AVAIL_HERO_LIST) end end
  if string.find(key,'send') then
   for pc=1,util.funcinfo(fn).bytecodes-1 do local bc=util.funcbc(fn,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
  end
 end
end
local f=package.loaded.SLGResourceCommonDialog.__instanceDict.CollectPopupChooseHeroPanel
local n,e=debug.getupvalue(f,1)
out[#out+1]='ENUM_SOURCE '..tostring(n)..' '..type(e)
if type(e)=='table' then out[#out+1]='COLLECT_AIM '..tostring(e.E_SLG_ARMY_AIM_TYPE_COLLECT) end
return table.concat(out,'\n')
