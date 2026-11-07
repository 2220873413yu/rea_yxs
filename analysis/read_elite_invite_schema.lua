-- Read the existing-friend-room invitation schema and all local Yangzhou defender variants only.
local out={};local proto=package.loaded.RoomClientProtoDes
for name,fields in pairs(proto) do
 if type(name)=='string' and type(fields)=='table' and (name:lower():find('elite') or name:lower():find('invite')) then
  out[#out+1]='TYPE '..name
  for _,d in ipairs(fields) do if type(d)=='table' then
   out[#out+1]=string.format('FIELD tag=%s name=%s',tostring(d.tag),tostring(d.name))
  end end
 end
end
local search=CSLTypes.DBSearcher.sharedInstance()
for id=10101,10108 do local q=search:searchQuestInfo(id);local names,seen={},{}
 for field=21,27 do
  for raw in tostring(q[field]):gmatch('%d+') do local npcId=tonumber(raw)
   if npcId>1 and not seen[npcId] then local npc=search:searchNPCInfo(npcId)
    if npc and npc[5]~=101411 and npc[5]~=101412 and npc[5]~=101413 and npc[5]~=101803 then
     names[#names+1]=CSLTypes.YXSUtils.GBK2UTF8(npc[3]);seen[npcId]=true
    end
   end
  end
 end
 out[#out+1]='DEFENDERS '..id..' '..table.concat(names,'、')
end
return table.concat(out,'\n')
