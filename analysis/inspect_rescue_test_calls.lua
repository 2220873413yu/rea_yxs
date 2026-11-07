-- Verify native retreat signatures and the formation's pure field readers before a one-shot rescue test.
local out={};local u=require('jit.util')
for _,p in ipairs({{'SLGMainController','sendTSLGRetreatArmyReq'},
 {'SLGMainController','parseTSLGRetreatArmyRsp'},{'SLGChooseHeroScene','getFirstHandValue'},
 {'SLGChooseHeroScene','updateArmyInfo'}}) do
 local fn=package.loaded[p[1]].__instanceDict[p[2]]
 out[#out+1]='FUNCTION '..table.concat(p,'.')..' params='..u.funcinfo(fn).params
 for i=-1,-100,-1 do local v=u.funck(fn,i);if v==nil then break end
  if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..i..' '..v end
 end
 for i=0,20 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for i=1,10 do local n,v=debug.getupvalue(fn,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if n=='T_ID' then for k,x in pairs(v) do if type(k)=='string' and k:find('RETREAT_ARMY') then out[#out+1]='RETREAT_ID '..tostring(x) end end end
 end
 for pc=1,u.funcinfo(fn).bytecodes-1 do local bc=u.funcbc(fn,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
for _,name in ipairs({'TSLGRetreatArmyReq','TSLGRetreatArmyRsp','TSLGStartArmyTripReq','TSLGArmyStatusNotify'}) do
 out[#out+1]='TYPE '..name
 for slot,f in ipairs(package.loaded.ChatClientProtoDes[name] or {}) do if type(f)=='table' then
  out[#out+1]='FIELD '..slot..' tag='..f.tag..' '..f.name
 end end
end
return table.concat(out,'\n')
