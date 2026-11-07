-- Trace native training timers and notification consumers without executing senders or UI callbacks.
local util=require('jit.util');local out={}
local function dump(name,f,bytecode)
 out[#out+1]='FUNCTION '..name..' params='..util.funcinfo(f).params
 for i=-1,-160,-1 do
  local v=util.funck(f,i);if v==nil then break end
  out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v)
  if type(v)=='table' then for k,x in pairs(v) do if type(x)=='number' or type(x)=='string' then out[#out+1]='KT '..tostring(k)..'='..tostring(x) end end end
 end
 for i=0,25 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,15 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 if bytecode then for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end end
end
for _,pair in ipairs({{'SLGBuildingsModel','setLeftTrainTimeCacheMap1'}, {'SLGBuildingsModel','updateTSLGGetBarrackRsp'},
 {'SLGBuildingsModel','updateTSLGTrainSoldierRsp'}, {'SLGBuildingsModel','updateTSLGGetSoldierNumRsp'}}) do
 dump(table.concat(pair,'.'),package.loaded[pair[1]].__instanceDict[pair[2]],true)
end
for name,cls in pairs(package.loaded) do
 local methods=type(cls)=='table' and cls.__instanceDict
 if type(methods)=='table' then
  for k,f in pairs(methods) do
   if type(f)=='function' and type(k)=='string' and util.funcinfo(f).bytecodes then
    local matched=false
    for i=-1,-120,-1 do
     local v=util.funck(f,i);if v==nil then break end
     if v=='sendTSLGGetBarrackReq' or v=='getTrainLeftTimeCacheMap1' or v=='setLeftTrainTimeCacheMap1' or
       v=='parseTSLGGetSoldierNumRsp' or v=='E_SVR_MSG_ID_SLG_GET_SOLDIER_NUM' or
       (type(v)=='string' and (v:find('TRAIN_FINISH') or v:find('BARRACK_CHANGE'))) then matched=true end
    end
    if matched and not (name=='SLGBuildingsModel' and k=='updateTSLGGetBarrackRsp') then dump(name..'.'..k,f,true) end
   end
  end
 end
end
return table.concat(out,'\n')
