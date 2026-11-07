-- Read original string constant bytes, avoiding mixed-encoding assumptions and any game commands.
local util=require('jit.util')
local f=package.loaded.SLGChooseHeroLogicCollectResource.__instanceDict.getAmyInfoData
local out={}
for i=-1,-80,-1 do
 local value=util.funck(f,i)
 if value==nil then break end
 if type(value)=='string' then
  out[#out+1]=tostring(i)..' '..(string.gsub(value,'.',function(c) return string.format('%02x',string.byte(c)) end))
 end
end
return table.concat(out,'\n')
