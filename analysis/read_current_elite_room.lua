-- Read the just-entered elite room and native defender selection mapping without changing room state.
local out={};local u=require('jit.util');local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.EliteLevelModel);local p=m:getPveInfo();local s=CSLTypes.DBSearcher.sharedInstance()
out[#out+1]='CURRENT_QUEST '..tostring(p[2]);out[#out+1]='MATCH_KIND '..tostring(p[3])
local q=s:searchQuestInfo(p[2]);out[#out+1]='QUEST_NAME '..CSLTypes.YXSUtils.GBK2UTF8(q[6])
for _,field in ipairs({23,24,25}) do
 local raw=q[field]
 for id in tostring(raw):gmatch('%d+') do local n=s:searchNPCInfo(tonumber(id))
  if n then out[#out+1]='CONFIG_DEFENDER '..id..' '..CSLTypes.YXSUtils.GBK2UTF8(n[3]) end
 end
end
local d=package.loaded.EliteChooseHeroScene.__instanceDict
for key,f in pairs(d) do if type(f)=='function' and u.funcinfo(f).bytecodes then
 local ks={};local relevant=false
 for i=-1,-140,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then ks[#ks+1]=v
  if v=='getPveInfo' or v=='parseNPCPosition' then relevant=true end
 end end
 if relevant then
  out[#out+1]='FUNCTION '..key..' '..table.concat(ks,'|')
  for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end end
return table.concat(out,'\n')
