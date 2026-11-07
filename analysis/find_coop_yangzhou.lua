-- Search local scene/quest configuration only; no server requests or room operations.
local out={};local search=CSLTypes.DBSearcher.sharedInstance()
local model=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.PVEModel)
for _,key in ipairs({'curScene','focusQuestID','iLastQuestID','questType'}) do out[#out+1]='PVE '..key..'='..tostring(model[key]) end
for id=1,600 do
 local ok,s=pcall(search.searchSceneInfo,search,id)
 if ok and type(s)=='table' then
  local match=false;local fields={}
  for k,v in pairs(s) do if type(k)=='number' and type(v)=='string' then
   local text=CSLTypes.YXSUtils.GBK2UTF8(v);if text:find('扬州') then match=true end
   if #text>0 and #text<120 then fields[#fields+1]=tostring(k)..'='..text end
  end end
  if match then
   out[#out+1]='SCENE '..id..' '..table.concat(fields,'|')
   local good,quests=pcall(search.searchAllQuestsByScene,search,id)
   out[#out+1]='QUEST_CONTAINER '..tostring(good)..' '..type(quests)..(not good and (' '..tostring(quests)) or '')
   if good and type(quests)=='table' then
    for k,q in pairs(quests) do if type(q)=='table' then
     local fs={};for f,v in pairs(q) do if type(f)=='number' and (type(v)=='number' or type(v)=='string') then
      local text=type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v)
      if #text>0 and #text<180 then fs[#fs+1]=f..'='..text end
     end end
     out[#out+1]='QUEST '..tostring(k)..' '..table.concat(fs,'|')
    end end
   end
  end
 end
end
local q=search:searchQuestInfo(model.focusQuestID)
if type(q)=='table' then for k,v in pairs(q) do if type(k)=='number' and (type(v)=='number' or type(v)=='string') then
 local s=type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v)
 if #s>0 and #s<300 then out[#out+1]='FOCUS '..k..'='..s end
end end end
local c=CSLTypes.HallMsgMgr
for k,v in pairs(c) do if type(k)=='string' and (k:lower():find('fiend') or k:lower():find('friend') or k:lower():find('group')) then out[#out+1]='HALL '..k..' '..type(v) end end
return table.concat(out,'\n')
