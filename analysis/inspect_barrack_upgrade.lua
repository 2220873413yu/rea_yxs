-- Read native barrack upgrade predicates and cached timestamps without querying or spending.
local u=require('jit.util');local out={};local model=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGBuildingsModel)
for _,key in ipairs({'getBarrackFinishTime','getBuildingCommInfo','getUpgradeTimeCache1','getUpgradingBuildingVec'}) do
 local f=package.loaded.SLGBuildingsModel.__instanceDict[key]
 if f and u.funcinfo(f).bytecodes then
  local constants={};for i=-1,-80,-1 do local v=u.funck(f,i);if v==nil then break end;constants[#constants+1]=tostring(v) end
  out[#out+1]=key..' CONST '..table.concat(constants,'|')
 end
end
local ok,value=pcall(model.getBarrackFinishTime,model);out[#out+1]='finish='..tostring(ok)..':'..tostring(value)
local r=model:getTSLGGetBarrackRsp()
if r and type(r[2])=='table' then for k,v in pairs(r[2]) do if type(v)~='table' and type(v)~='function' then out[#out+1]='comm.'..tostring(k)..'='..tostring(v) end end end
for name,cls in pairs(package.loaded) do
 if type(name)=='string' and name:lower():find('barrack') and type(cls)=='table' and cls.__instanceDict then
  for key,f in pairs(cls.__instanceDict) do
   if type(f)=='function' and u.funcinfo(f).bytecodes then
    local constants={};local relevant=false
    for i=-1,-130,-1 do local v=u.funck(f,i);if v==nil then break end;constants[#constants+1]=tostring(v)
     if v=='checkIsForbidTrain' or v=='getBarrackFinishTime' then relevant=true end
    end
    if relevant then
     out[#out+1]=name..'.'..tostring(key)..' CONST '..table.concat(constants,'|')
     for i=1,12 do local n,up=debug.getupvalue(f,i);if not n then break end
      out[#out+1]='UP '..n..' '..type(up)
      if type(up)=='function' and u.funcinfo(up).bytecodes then
       local ks={};for j=-1,-70,-1 do local v=u.funck(up,j);if v==nil then break end;ks[#ks+1]=tostring(v) end
       out[#out+1]='UPCONST '..table.concat(ks,'|')
      if n=='checkIsUpdating' then
       out[#out+1]='PARAMS '..tostring(u.funcinfo(up).params)
       local good,result=pcall(up);out[#out+1]='NATIVE_UPGRADING='..tostring(good)..':'..tostring(result)
      end
      end
     end
    end
   end
  end
 end
end
return table.concat(out,'\n')
