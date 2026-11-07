-- Read dispatch caches and native field/phase mappings only, without invoking query or business senders.
local out={};local u=require('jit.util');local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGDispatchModel)
for _,key in ipairs({'duhufuInfo','taskInfo','selectHeroList','selectHeros','TaskNeedPerson','refreshItemEnum'}) do
 local v=m[key];out[#out+1]='CACHE '..key..' '..type(v)
 if type(v)=='table' and v.get_Count then out[#out+1]='COUNT '..key..'='..tostring(v:get_Count())
 elseif type(v)=='table' then for k,x in pairs(v) do if type(k)=='number' and (type(x)=='number' or type(x)=='boolean') then out[#out+1]='FIELD '..key..'.'..k..'='..tostring(x) end end end
end
for _,pair in ipairs({{'SLGDispatchController','sendTSLGDuHuFuGetInfoReq'},
 {'SLGDispatchController','sendTSLGDuHuFuGetHeroListReq'},{'SLGDispatchModel','updateSLGDuHuFuGetInfo'},
 {'SLGDispatchModel','updateSLGDuHuFuGetHeroList'},{'SLGDispatchModel','GetHeroCanDispatch'},
 {'SLGDispatchModel','GetTaskConditionDesc'},{'SLGDispatchListTaskItem','SetData'},
 {'SLGDispatchListTaskItem','Update'},{'SLGDispatchChooseHeroScene','updateArmyInfo'}}) do
 local f=package.loaded[pair[1]].__instanceDict[pair[2]]
 out[#out+1]='FUNCTION '..pair[1]..'.'..pair[2]..' '..type(f)
 if type(f)=='function' and u.funcinfo(f).bytecodes then
  out[#out+1]='PARAMS '..tostring(u.funcinfo(f).params)
  for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
  for i=0,18 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
  for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
    math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
  for i=1,8 do local n,v=debug.getupvalue(f,i);if not n then break end
   if type(v)=='table' and n=='T_ID' then for k,id in pairs(v) do if type(k)=='string' and k:find('DUHUFU') then out[#out+1]='PROTOCOL '..k..'='..tostring(id) end end end
  end
 end
end
for _,name in ipairs({'SLGDispatchListTaskItem','SLGDispatchArmyInfo'}) do
 local c=package.loaded[name];local d=c and c.__instanceDict
 if d then for k,f in pairs(d) do if type(f)=='function' and u.funcinfo(f).bytecodes then
  local ks={};local relevant=false
  for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end
   if type(v)=='string' then ks[#ks+1]=v;if v=='GetSLGDuHuFuEvent' or v=='sendTSLGGetDuHuFuEventRewardReq' or v=='countDownTime' then relevant=true end end
  end
  if relevant then out[#out+1]='METHOD '..name..'.'..k..' '..table.concat(ks,'|') end
 end end end
end
return table.concat(out,'\n')
