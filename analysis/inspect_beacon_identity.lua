-- Identify the screenshot's beacon map events from native readers only; never send requests or actions.
local out={};local u=require('jit.util')
for _,name in ipairs({'FengHuoTaiDialog','FengHuoTaiDialogEventItem','SLGFengHuoTaiEventSmallDialog',
 'SLGFengHuoTaiTreasureDetailDialog','SLGFengHuoTaiSaveDialog','SLGFengHuoTaiResourceCommonDialog',
 'SLGFengHuoTaiMonsterDetailDialog','SLGMainModel','SLGMainController'}) do
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 local d=type(cls)=='table' and cls.__instanceDict
 out[#out+1]='MODULE '..name..' '..type(d)
 if d then for key,fn in pairs(d) do
  if type(key)=='string' and type(fn)=='function' and u.funcinfo(fn).bytecodes and
   (name~='SLGMainModel' and name~='SLGMainController' or key:find('BeaconTower') or key:find('FengHuoTai')) then
   local constants={}
   for i=-1,-120,-1 do local v=u.funck(fn,i);if v==nil then break end
    if type(v)=='string' and not v:find('[\128-\255]') then constants[#constants+1]=v end
   end
   out[#out+1]='METHOD '..name..'.'..key..' '..table.concat(constants,'|')
  end
 end end
end
for name,d in pairs(package.loaded.ChatClientProtoDes) do if type(name)=='string' and name:find('BeaconTower') and type(d)=='table' then
 out[#out+1]='TYPE '..name
 for slot,f in ipairs(d) do if type(f)=='table' then out[#out+1]='FIELD '..slot..' '..tostring(f.name)..' '..
  (type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or '') end end
end end
return table.concat(out,'\n')
