-- Trace actual unit/scout packet construction and selection rules, without invoking action senders.
local out={};local u=require('jit.util')
local function dump(label,f)
 if type(f)~='function' or not u.funcinfo(f).bytecodes then return end
 out[#out+1]='FUNCTION '..label
 for i=-1,-140,-1 do local v=u.funck(f,i);if v==nil then break end
  if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..i..' '..v end
 end
 for i=0,25 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for i=1,20 do local n,v=debug.getupvalue(f,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if type(v)=='table' then for k,x in pairs(v) do if type(k)=='string' and (k:find('BEACON') or k:find('SCOUT')) then
   out[#out+1]='ENUM '..k..' '..tostring(x)
  end end end
 end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
for _,p in ipairs({{'SLGChooseHeroLogicFengHuoTaiSave','startTrip'},
 {'SLGChooseHeroLogicFengHuoTaiSave','startTrip2'},{'SLGChooseHeroLogicFengHuoTaiSave','getTargetID2'},
 {'SLGChooseHeroLogicFengHuoTaiSave','getAmyInfoData'},{'SLGChooseHeroScene','updateSoldier'},
 {'SLGScoutDialog','setBaseInfo'},{'SLGScoutDialog','updateSelf'},
 {'SLGMainController','sendTSLGScoutAreaReq'},{'SLGMainController','parseTSLGScoutAreaRsp'},
 {'SLGMainModel','addScoutInfo'},{'SLGChooseHeroLogicBase','create'}}) do
 pcall(function() return CSLTypes[p[1]] end)
 dump(table.concat(p,'.'),package.loaded[p[1]].__instanceDict[p[2]])
end
return table.concat(out,'\n')
