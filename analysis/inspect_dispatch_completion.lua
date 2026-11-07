-- Trace only native completion and eligibility readers; no native UI, task or reward method is called.
local u=require('jit.util');local out={}
for _,pair in ipairs({{'SLGDispatchListTaskItem','UpdateTime'},
 {'SLGDispatchModel','updateSLGDuHuFuSelectHero'},{'SLGDispatchModel','updateSLGGetDuHuFuEventReward'},
 {'SLGDispatchChooseHeroScene','AutoDispatch'},{'SLGDispatchChooseHeroScene','Dispatch'},
 {'SLGDispatchChooseHeroScene','_AutoDispatch_b__0'}}) do
 local fn=package.loaded[pair[1]].__instanceDict[pair[2]]
 out[#out+1]='FUNCTION '..table.concat(pair,'.')..' '..type(fn)
 if type(fn)=='function' and u.funcinfo(fn).bytecodes then
  for i=-1,-100,-1 do local v=u.funck(fn,i);if v==nil then break end
   if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..(-i-1)..' '..v end
  end
  for i=0,24 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
  for pc=1,u.funcinfo(fn).bytecodes-1 do local bc=u.funcbc(fn,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
    math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end
for name,cls in pairs(package.loaded) do
 if type(name)=='string' and name:find('SLG') and type(cls)=='table' then
  local d=cls.__instanceDict
  if d then for key,fn in pairs(d) do if type(key)=='string' and (key:find('Push') or key:find('Notify')) and type(fn)=='function' then
   local info=u.funcinfo(fn)
   if info.bytecodes then for i=-1,-100,-1 do local v=u.funck(fn,i);if v==nil then break end
    if type(v)=='string' and (v:find('DuHuFu') or v:find('Dispatch')) then out[#out+1]='PUSH_REFERENCE '..name..'.'..key..' '..v end
   end end
  end end end
 end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local ok,privilege=pcall(main.isSLGMonthCardEnabled,main)
out[#out+1]='NATIVE_AUTO_PRIVILEGE '..tostring(ok)..' '..tostring(privilege)
return table.concat(out,'\n')
