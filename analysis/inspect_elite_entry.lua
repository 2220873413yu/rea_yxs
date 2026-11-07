-- Read exact co-op/random entry arguments and current elite quest/NPC configuration; no entry is attempted.
local out={};local u=require('jit.util');local mm=CSLTypes.ModelManager.sharedInstance()
local model=mm:getModel(CSLTypes.EliteLevelModel);local progress=model:getProgressMsg()
for _,name in ipairs({'onFriendFightBtnCallBack','onRandomFightBtnCallBack','initCurrentQuest'}) do
 local f=package.loaded.EliteLevelScene.__instanceDict[name];out[#out+1]='FUNCTION '..name
 for i=-1,-90,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
 for i=0,25 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
local s=CSLTypes.DBSearcher.sharedInstance()
for _,id in ipairs({progress[6],progress[7]}) do
 local q=s:searchQuestInfo(id);out[#out+1]='ELITE_QUEST '..tostring(id)
 if q then for k,v in pairs(q) do if type(k)=='number' and (type(v)=='number' or type(v)=='string') then
  local text=type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v)
  if #text>0 and #text<400 then out[#out+1]='Q '..k..'='..text end
 end end end
end
for _,name in ipairs({'EliteChooseHeroScene'}) do
 local c=package.loaded[name];if not c then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 if c and c.__instanceDict then for k,f in pairs(c.__instanceDict) do if type(f)=='function' and u.funcinfo(f).bytecodes then
  local ks={};local relevant=false
  for i=-1,-130,-1 do local v=u.funck(f,i);if v==nil then break end
   if type(v)=='string' then ks[#ks+1]=v;if v=='searchNPCInfo' or v=='sendEliteSitDownMsg' then relevant=true end end
  end
  if relevant then out[#out+1]='HERO_METHOD '..k..' '..table.concat(ks,'|') end
 end end end
end
return table.concat(out,'\n')
