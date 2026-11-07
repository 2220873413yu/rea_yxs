-- Read static room protocol descriptors and local elite quest grouping; no network operation.
local out={};local proto=assert(package.loaded.RoomClientProtoDes)
for _,name in ipairs({'TPVEInfo','TSitDownReq','TSitDownRsp'}) do
 out[#out+1]='TYPE '..name
 local d=proto[name]
 if type(d)=='table' then
  for k,v in pairs(d) do
   if type(v)=='number' or type(v)=='string' then out[#out+1]='META '..tostring(k)..'='..tostring(v)
   elseif type(v)=='table' then
    local bits={}
    for x,y in pairs(v) do
     if type(y)=='number' or type(y)=='string' or type(y)=='boolean' then bits[#bits+1]=tostring(x)..'='..tostring(y)
     elseif type(y)=='table' then
      local sub={};for a,b in pairs(y) do if type(b)=='number' or type(b)=='string' or type(b)=='boolean' then sub[#sub+1]=tostring(a)..'='..tostring(b) end end
      bits[#bits+1]=tostring(x)..'={'..table.concat(sub,',')..'}'
     end
    end
    out[#out+1]='DESC '..tostring(k)..' '..table.concat(bits,'|')
   end
  end
 end
end
local s=CSLTypes.DBSearcher.sharedInstance()
for id=10101,10112 do local q=s:searchQuestInfo(id)
 if q then
  local fs={};for _,k in ipairs({1,2,3,4,5,6,14,17,21,22,23,24,25,26,27,28,29,80}) do
   local v=q[k]
   if type(v)=='number' or type(v)=='string' then fs[#fs+1]=k..'='..(type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v)) end
  end
  out[#out+1]='QUEST '..id..' '..table.concat(fs,'|')
 end
end
return table.concat(out,'\n')
