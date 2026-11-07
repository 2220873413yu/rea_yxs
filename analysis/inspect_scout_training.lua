-- Inspect cached barrack/scout schemas and native senders; no requests, training or item use.
local out={};local util=require('jit.util')
local mm=CSLTypes.ModelManager.sharedInstance();local b=mm:getModel(CSLTypes.SLGBuildingsModel)
local r=b:getTSLGGetBarrackRsp();out[#out+1]='BARRACK_RET '..tostring(r and r[1])
if r and r[1]==0 then
 local keys=r[4]:GetDictKeys()
 for i=0,keys:get_Count()-1 do local id=keys:get_Item(i);local a=r[4]:get_Item(id)
  out[#out+1]='UNIT '..tostring(id)
  for k,v in pairs(a) do
   if type(v)=='number' then out[#out+1]='FIELD '..tostring(k)..'='..tostring(v)
   elseif k==3 and type(v)=='table' then
    for x,y in pairs(v) do if type(y)=='number' then out[#out+1]='QUEUE '..tostring(x)..'='..tostring(y) end end
   end
  end
  local ok,q=pcall(function() return b:getTrainLeftTimeCacheMap1():get_Item(id) end)
  out[#out+1]='TRAIN_CACHE '..tostring(ok)..' '..tostring(ok and q and q:get_Count())
 end
end
for _,entry in ipairs({{'SoldierTrainingNewDialog','setContentInfo'},{'SoldierTrainingNewDialog','setResCostInfo'},
 {'BarracksArmItem','initSodierNameAndNum'},{'SLGBuildingsController','sendTSLGTrainSoldierReq'},
 {'SLGBuildingsController','sendTSLGBuildSpeedupReq'},{'BarracksArmItem','countDown'}}) do
 local c=package.loaded[entry[1]];local f=c and c.__instanceDict and c.__instanceDict[entry[2]]
 if type(f)=='function' and util.funcinfo(f).bytecodes then
  out[#out+1]='METHOD '..entry[1]..'.'..entry[2]..' PARAMS '..tostring(util.funcinfo(f).params)
  for i=-1,-100,-1 do local v=util.funck(f,i);if v==nil then break end
   if type(v)=='string' then out[#out+1]='K '..tostring(i)..' '..v end
  end
  for i=0,30 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..tostring(i)..' '..tostring(v) end
  if entry[2]=='setContentInfo' or entry[2]=='sendTSLGTrainSoldierReq' or entry[2]=='sendTSLGBuildSpeedupReq' then
   for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc)
    out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
     math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
   end
  end
 end
end
return table.concat(out,'\n')
