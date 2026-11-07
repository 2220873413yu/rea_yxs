-- Read training time schemas and native notification handlers; no game request or action is sent.
local util=require('jit.util')
local out={}
local manager=CSLTypes.ModelManager.sharedInstance()
local model=manager:getModel(CSLTypes.SLGBuildingsModel)
local rsp=model:getTSLGGetBarrackRsp()
out[#out+1]='BARRACK_RET '..tostring(rsp and rsp[1])
if rsp and rsp[1]==0 then
 for _,id in ipairs({411,412,413}) do
  local a=rsp[4]:get_Item(id)
  out[#out+1]='UNIT '..id
  for k,v in pairs(a) do
   if type(v)=='number' then out[#out+1]='FIELD '..k..'='..string.format('%.0f',v)
   elseif k==3 and type(v)=='table' then for x,y in pairs(v) do if type(y)=='number' then out[#out+1]='TRAIN '..x..'='..string.format('%.0f',y) end end end
  end
 end
end
for _,name in ipairs({'SLGBuildingsController','SLGBuildingsModel','SLGBarrackDialog','SLGBarrackItem','SLGSoldierItem','SLGBarrackSoldierItem'}) do
 local cls=package.loaded[name]
 local methods=cls and cls.__instanceDict
 out[#out+1]='MODULE '..name..' '..type(methods)
 if methods then
  local keys={}
  for k,v in pairs(methods) do
   if type(k)=='string' and type(v)=='function' and (name~='SLGBuildingsController' and name~='SLGBuildingsModel' or
    k:lower():find('barrack') or k:lower():find('train') or k:lower():find('soldier') or k:lower():find('speedup')) then keys[#keys+1]=k end
  end
  table.sort(keys)
  for _,k in ipairs(keys) do
   local f=methods[k]
   out[#out+1]='FUNCTION '..name..'.'..k..' params='..util.funcinfo(f).params
   for i=-1,-100,-1 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='K '..(-i-1)..' '..tostring(v) end
   for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v)
    if type(v)=='table' and n=='T_ID' then for x,y in pairs(v) do if tostring(x):find('BARRACK') or tostring(x):find('TRAIN') or tostring(x):find('SOLDIER') then out[#out+1]='PROTOCOL '..x..'='..tostring(y) end end end
   end
  end
 end
end
for name,cls in pairs(package.loaded) do
 if type(name)=='string' and (name:lower():find('barrack') or name:lower():find('train')) then out[#out+1]='LOADED '..name end
end
return table.concat(out,'\n')
