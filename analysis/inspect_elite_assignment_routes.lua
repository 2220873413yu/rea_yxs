-- Discover functions which assign elite PVE info and declaration storage, without invoking any handler.
local out={};local u=require('jit.util')
local function scan(label,d)
 if type(d)~='table' then return end
 for k,v in pairs(d) do
  if type(v)=='function' and u.funcinfo(v).bytecodes then
   local ks={};local relevant=false
   for i=-1,-190,-1 do local x=u.funck(v,i);if x==nil then break end
    if type(x)=='string' then ks[#ks+1]=x
     if x=='setPveInfo' or x=='E_SVR_MSG_ID_SITDOWN' or x=='PVEElite' or x=='iCurEliteID' then relevant=true end
    end
   end
   if relevant then out[#out+1]='ROUTE '..label..'.'..tostring(k)..' '..table.concat(ks,'|') end
  end
 end
end
for name,c in pairs(package.loaded) do
 if type(name)=='string' and type(c)=='table' then
  scan(name,c);scan(name..'.instance',c.__instanceDict);scan(name..'.static',c.static)
 end
end
local _,hall=debug.getupvalue(CSLTypes.HallMsgMgr.sendSitDownMsg,1)
for _,key in ipairs({'__instanceDict','__declaredMethods','static'}) do
 local d=hall[key];out[#out+1]='HALL_STORE '..key..' '..type(d)
 if type(d)=='table' then
  local count=0
  for k,v in pairs(d) do
   if count<20 then out[#out+1]='STORE_KEY '..tostring(k)..' '..type(v);count=count+1 end
  end
  local meta=getmetatable(d)
  if type(meta)=='table' then for k,v in pairs(meta) do out[#out+1]='STORE_META '..tostring(k)..' '..type(v);if type(v)=='table' then scan('hall.'..key..'.meta.'..tostring(k),v) end end end
  scan('hall.'..key,d)
 end
end
return table.concat(out,'\n')
