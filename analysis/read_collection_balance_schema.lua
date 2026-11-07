-- Read protocol descriptors and cached resource quantities; no network requests or actions.
local out={};local wanted={}
for module,p in pairs(package.loaded) do
 if type(module)=='string' and module:find('ProtoDes') and type(p)=='table' then
  for name,d in pairs(p) do if type(name)=='string' and type(d)=='table' and
   (name=='TSLGArmyInfo' or name=='TSLGResourceCollectInfo' or name=='TSLGResource' or
    name:find('SLG.*Resource') or name=='TSLGArmyTripInfo') then
   out[#out+1]='TYPE '..module..'.'..name
   for _,f in ipairs(d) do if type(f)=='table' then
    out[#out+1]=string.format('FIELD %s %s %s',tostring(f.tag),tostring(f.name),
     type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or '')
   end end
  end end
 end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local r=main:getMySLGResource()
for k,v in pairs(r or {}) do if type(k)=='number' and type(v)=='number' then out[#out+1]='STOCK '..k..' '..string.format('%.0f',v) end end
local u=require('jit.util')
for _,pair in ipairs({{'SLGMainModel','UpdateResource'},{'SLGMainModel','updateMySLGResource'},
 {'SLGResourceHeroItem','getArmyEstimateTime'}}) do
 local f=package.loaded[pair[1]].__instanceDict[pair[2]]
 out[#out+1]='FUNCTION '..table.concat(pair,'.')
 for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='K '..(-i-1)..' '..tostring(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
return table.concat(out,'\n')
