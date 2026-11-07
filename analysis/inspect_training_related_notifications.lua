-- Identify consumers of generic change events and inspect training UI scheduling without mutation.
local util=require('jit.util');local out={}
for name,cls in pairs(package.loaded) do
 local methods=type(cls)=='table' and cls.__instanceDict
 if type(methods)=='table' then for k,f in pairs(methods) do
  if type(f)=='function' and type(k)=='string' and util.funcinfo(f).bytecodes then
   local match=false
   for i=0,50 do local n=util.funck(f,i);if n==nil then break end;if n==11003 or n==11089 then match=true end end
   if match or ((name=='BarracksArmItem' or name=='BarracksDialog' or name=='TrainSoldierUIData') and
     (k=='Update' or k=='Start' or k=='OnEnable' or k=='initUI' or k=='updateSelf' or k=='getTrainTimeLeft' or k=='initWithData')) then
    out[#out+1]='FUNCTION '..name..'.'..k
    for i=-1,-130,-1 do local v=util.funck(f,i);if v==nil then break end
     if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v
     elseif type(v)=='table' then for a,b in pairs(v) do if type(b)=='number' then out[#out+1]='KT '..tostring(a)..'='..b end end end
    end
    for i=0,50 do local n=util.funck(f,i);if n==nil then break end;out[#out+1]='N '..i..'='..tostring(n) end
   end
  end
 end end
end
return table.concat(out,'\n')
