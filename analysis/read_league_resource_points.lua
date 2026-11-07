-- Read cached league-mine positions/config and native collect button closure, without querying or dispatching.
local out={};local u=require('jit.util');local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel);local main=manager:getModel(CSLTypes.SLGMainModel)
local league=manager:getModel(CSLTypes.SLGLeagueModel);local search=CSLTypes.DBSearcher.sharedInstance()
local own=main:getMyLeagueId();out[#out+1]='HAS_LEAGUE '..tostring(own~=0)
local function nums(label,t)
 for k,v in pairs(t or {}) do
  if type(v)=='number' then out[#out+1]=label..'.'..k..'='..v
  elseif type(v)=='table' and type(k)=='number' then
   for a,b in pairs(v) do if type(b)=='number' then out[#out+1]=label..'.'..k..'.'..a..'='..b end end
  end
 end
end
local chunks=map.mInViewDataChunkCacheManager:getAllViewData();local seen={}
for i=0,chunks:get_Count()-1 do
 local c=chunks:get_Item(i).mViewDataCache
 if c:ContainsKey(1012) then
  local p=c:get_Item(1012);local keys=p:GetDictKeys()
  for j=0,keys:get_Count()-1 do local key=keys:get_Item(j)
   if not seen[key] then seen[key]=true;local row=p:get_Item(key);nums('RESOURCE '..key,row) end
  end
 end
end
local rsp=league:getTSLGLeagueGetAllBuildRsp()
if rsp and rsp[2] and rsp[2].GetDictKeys then
 local dict=rsp[2];local ks=dict:GetDictKeys()
 for i=0,ks:get_Count()-1 do local k=ks:get_Item(i);local v=dict:get_Item(k)
  out[#out+1]='BUILD_KEY '..k..' '..type(v)
  if type(v)=='table' and v.get_Count then
   out[#out+1]='BUILD_COUNT '..v:get_Count()
   for j=0,math.min(v:get_Count(),5)-1 do local p=v:get_Item(j);if type(p)=='table' then nums('BUILD '..k..'.'..j,p) end end
  elseif type(v)=='table' then nums('BUILD '..k,v) end
 end
end
local function dump(label,f)
 if type(f)~='function' or not u.funcinfo(f).bytecodes then return end
 out[#out+1]='FUNCTION '..label
 for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=0,20 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
local methods=package.loaded.SLGLeagueResCommonDialog.__instanceDict
for _,key in ipairs({'Start','initBaseInfo','initButtonArea','initUI'}) do
 local f=methods[key];dump(key,f)
 for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;if type(v)=='function' then dump(key..'.UP'..i..'.'..n,v) end end
end
return table.concat(out,'\n')
