-- Inspect cached room identity, progress gates and client error handling; no read/request sender is called.
local out={};local u=require('jit.util');local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.EliteLevelModel);local p=m:getProgressMsg()
for _,i in ipairs({1,5,6,7,9,10}) do out[#out+1]='PROGRESS '..i..'='..tostring(p[i]) end
local r=m:getPveInfo()
if type(r)=='table' then
 for _,i in ipairs({1,2,3}) do if type(r[i])=='number' then out[#out+1]='CACHED_PVE '..i..'='..tostring(r[i]) end end
end
local methods=package.loaded.EliteLevelModel.__instanceDict
for _,k in ipairs({'setProgressMsg','checkOpenState','handleEliteOpenTime','updateMeHeroList'}) do
 local f=methods[k];out[#out+1]='FUNCTION '..k
 for i=-1,-90,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
local f=CSLTypes.HallMsgMgr.sendSitDownMsg
local name,hall=debug.getupvalue(f,1)
out[#out+1]='HALL '..tostring(name)..' '..type(hall)
if type(hall)=='table' then for k,fn in pairs(hall) do if type(fn)=='function' and u.funcinfo(fn).bytecodes then
 local ks={};local relevant=false
 for i=-1,-140,-1 do local v=u.funck(fn,i);if v==nil then break end;if type(v)=='string' then ks[#ks+1]=v
  if v:lower():find('sitdown') or v:find('ELITE') or v:find('精英') then relevant=true end
 end end
 if relevant then out[#out+1]='HALL_FN '..tostring(k)..' '..table.concat(ks,'|') end
end end end
return table.concat(out,'\n')
