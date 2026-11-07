-- Read local server-error text and native response handlers, never send or simulate a room request.
local out={};local u=require('jit.util')
local db=CSLTypes.DataCenter.sharedDataCenter().allLocalData[31]
local keys=db:GetDictKeys()
for i=0,keys:get_Count()-1 do local key=keys:get_Item(i);local row=db:get_Item(key)
 if type(row)=='table' then for k,v in pairs(row) do if type(v)=='string' then local text=CSLTypes.YXSUtils.GBK2UTF8(v)
  if text:find('精英') or text:find('关卡') or text:find('军令') or text:find('房间') or text:find('闯关') or text:find('过关斩将') then
   out[#out+1]='ERROR '..tostring(key)..' '..text
  end
 end end end
end
local _,hall=debug.getupvalue(CSLTypes.HallMsgMgr.sendSitDownMsg,1)
for k,f in pairs(hall.static) do
 if type(f)=='function' and u.funcinfo(f).bytecodes then
  local ks={};local relevant=false
  for i=-1,-200,-1 do local v=u.funck(f,i);if v==nil then break end
   if type(v)=='string' then ks[#ks+1]=v
    if v:lower():find('sitdown') or v:find('ELITE') or v:find('精英') then relevant=true end
   end
  end
  if relevant then out[#out+1]='HANDLER '..tostring(k)..' '..table.concat(ks,'|') end
 end
end
return table.concat(out,'\n')
