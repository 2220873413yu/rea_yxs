-- Read the beacon screen's existing event cache and native type branches, without sending any request.
local out={};local mm=CSLTypes.ModelManager.sharedInstance();local m=mm:getModel(CSLTypes.SLGMainModel)
local rsp=m:getTSLGGetBeaconTowerInfoRsp();local search=CSLTypes.DBSearcher.sharedInstance()
if rsp then
 out[#out+1]=string.format('BEACON ret=%s level=%s completed=%s refresh=%s queues=%s',tostring(rsp[1]),
  tostring(rsp[2]),tostring(rsp[3]),tostring(rsp[5]),tostring(rsp[6]))
 local list=rsp[4]
 for i=0,list:get_Count()-1 do local e=list:get_Item(i);local c=search:searchTMapIntelStation_Event_Map(e[2])
  local fields={}
  for k=1,20 do local v=c[k]
   if type(v)=='number' then fields[#fields+1]=k..'='..v
   elseif type(v)=='string' and not v:find('[\128-\255]') then fields[#fields+1]=k..'='..v end
  end
  out[#out+1]='EVENT config='..tostring(e[2])..' state='..tostring(e[3])..' '..table.concat(fields,'|')
 end
else out[#out+1]='NO_BEACON_CACHE' end
local u=require('jit.util')
for _,pair in ipairs({{'FengHuoTaiDialogEventItem','setIcon'},{'SLGFengHuoTaiEventSmallDialog','initUI'}}) do
 local fn=package.loaded[pair[1]].__instanceDict[pair[2]]
 out[#out+1]='FUNCTION '..table.concat(pair,'.')..' '..type(fn)
 if type(fn)=='function' then
  for i=-1,-90,-1 do local v=u.funck(fn,i);if v==nil then break end
   if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..(-i-1)..' '..v end
  end
  for i=0,20 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
  for pc=1,u.funcinfo(fn).bytecodes-1 do local bc=u.funcbc(fn,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
    math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end
return table.concat(out,'\n')
