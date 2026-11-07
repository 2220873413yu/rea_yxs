-- Trace the target-position preparation for native beacon selection; no query or action is invoked.
local out={};local u=require('jit.util')
for _,p in ipairs({{'SLGMainController','parseTSLGMonsterGetAvailHeroListRsp'},
 {'SLGMainController','sendTSLGGetAvailHeroListReq2'},{'SLGChooseHeroScene','setContent'}}) do
 local f=package.loaded[p[1]].__instanceDict[p[2]];out[#out+1]='FUNCTION '..table.concat(p,'.')..' '..type(f)
 if type(f)=='function' then
 for i=-1,-130,-1 do local v=u.funck(f,i);if v==nil then break end
  if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..i..' '..v end
 end
 for i=0,45 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 end
end
for k,f in pairs(package.loaded.SLGMainController.__instanceDict) do
 if type(k)=='string' and k:find('AvailHero') then out[#out+1]='AVAIL_METHOD '..k..' '..type(f) end
end
local _,panel=debug.getupvalue(package.loaded.SLGFengHuoTaiSaveDialog.__instanceDict.onSaveClick,1)
for i=1,10 do local n,v=debug.getupvalue(panel,i);if not n then break end
 if type(v)=='table' then for k,x in pairs(v) do
  if type(k)=='string' and (k:find('BEACON') or x==31 or x==32) then out[#out+1]='AIM_ENUM '..k..'='..tostring(x) end
 end end
end
for _,name in ipairs({'TSLGGetAvailHeroListReq','TSLGGetAvailHeroListRsp'}) do
 out[#out+1]='TYPE '..name
 for slot,f in ipairs(package.loaded.ChatClientProtoDes[name]) do if type(f)=='table' then
  out[#out+1]='FIELD '..slot..' tag='..f.tag..' '..f.name
 end end
end
return table.concat(out,'\n')
