-- Read experiment army and the most recent native quick-combat result, without sending requests.
local out={};local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local a=m:getMyArmyInfoByHeroGroupId(427)
if a then for _,i in ipairs({1,4,5,6,10,11}) do out[#out+1]='ARMY '..i..'='..tostring(a[i]) end else out[#out+1]='ARMY absent' end
local r=m._lastSLGSitdown
out[#out+1]='SITDOWN '..type(r)
if type(r)=='table' then for k,v in pairs(r) do if type(v)=='number' or type(v)=='boolean' then out[#out+1]='RESULT '..k..'='..tostring(v) end end end
local util=require('jit.util');local f=package.loaded.SLGMainController.__instanceDict.parseTSLGSitDownClientRsp
for i=-1,-70,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..CSLTypes.YXSUtils.GBK2UTF8(v) end end
for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
return table.concat(out,'\n')
