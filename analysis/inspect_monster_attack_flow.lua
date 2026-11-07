-- Inspect native combat continuation and queue checks without invoking them.
local out={};local util=require('jit.util')
for name,cls in pairs(package.loaded) do
 if type(name)=='string' and string.find(name,'SLG') and type(cls)=='table' and cls.__instanceDict then
  for key,f in pairs(cls.__instanceDict) do
   if type(key)=='string' and type(f)=='function' and util.funcinfo(f).bytecodes then
    local keys={};local wanted=false
    for i=-1,-100,-1 do
     local s=util.funck(f,i);if s==nil then break end
     if type(s)=='string' then
      if string.find(s,'Skip') or string.find(s,'skip') or string.find(s,'sendTSLG.*Fight') or string.find(s,'sendTSLG.*Battle') then wanted=true end
      if not string.find(s,'[\128-\255]') then keys[#keys+1]=s end
     end
    end
    if wanted or (name=='SLGMainModel' and (string.find(key,'Max.*Army') or string.find(key,'Army.*Count'))) then
     out[#out+1]=name..'.'..key..' '..table.concat(keys,'|')
    end
   end
  end
 end
end
return table.concat(out,'\n')
