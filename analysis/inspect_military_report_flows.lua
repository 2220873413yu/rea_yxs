-- Inspect bytecode constants and upvalues only; never invoke the inspected UI, claim or delete callbacks.
local out={};local u=require('jit.util');local seen={}
local function dump(label,fn,depth)
 if type(fn)~='function'or seen[fn]then return end;seen[fn]=true
 local info=u.funcinfo(fn);if not info.bytecodes then return end
 out[#out+1]='FUNCTION '..label..' params='..info.params
 for i=-1,-180,-1 do local v=u.funck(fn,i);if v==nil then break end
  if type(v)=='string'then
   if v:find('[\128-\255]')then out[#out+1]='HEX '..i..' '..v:gsub('.',function(c)return string.format('%02x',string.byte(c))end)
   else out[#out+1]='K '..i..' '..v end
  end
 end
 for i=0,35 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v)end
 local nested={}
 for i=1,30 do local name,value=debug.getupvalue(fn,i);if not name then break end
  out[#out+1]='UP '..i..' '..name..' '..type(value)
  if type(value)=='function'then nested[#nested+1]={name,value}end
 end
 for pc=1,info.bytecodes-1 do local bc=u.funcbc(fn,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 if depth>0 then for _,v in ipairs(nested)do dump(label..'.UP.'..v[1],v[2],depth-1)end end
end
for _,pair in ipairs({{'SLGMilitaryNewsDialog','showMilitaryNews'},{'SLGMilitaryNewsDialog','initSLGNewsInfo'},
 {'SLGMilitaryNewsDialog','Start'},{'SLGMilitaryNewsDialog','updateSelf'},{'SLGMilitaryNewsDialog','GetUserEmailReward'},
 {'SLGMilitaryNewsItem','initItem'},{'SLGMilitaryNewsItem','UpdateItem'},{'SLGMilitaryNewsItemData','initialize'},
 {'SLGBuildingsModel','setTSLGGetAllEmailRsp'},{'SLGBuildingsModel','updateTSLGGetAllEmailRsp'},
 {'SLGBuildingsModel','updateTSLGGetEmailRewardRsp'},{'SLGBuildingsModel','getTSLGGetAllEmailRsp'},
 {'SLGBuildingsController','sendTSLGGetAllEmailReq'},{'SLGBuildingsController','parseTSLGGetAllEmailRsp'},
 {'SLGBuildingsController','sendTSLGGetEmailRewardReq'}})do
 local c=package.loaded[pair[1]];if c then dump(table.concat(pair,'.'),(c.__instanceDict or c)[pair[2]],1)end
end
return table.concat(out,'\n')
