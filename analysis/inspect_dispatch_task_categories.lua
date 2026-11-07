-- Enumerate local task configuration and category descriptors only; no server request or dispatch.
local out={};local u=require('jit.util');local search=CSLTypes.DBSearcher.sharedInstance()
local f=search.GetSLGDuHuFuEvent
for i=-1,-40,-1 do local v=u.funck(f,i);if v==nil then break end
 if type(v)=='string' then out[#out+1]='LOOKUP_K '..v end
end
for i=0,15 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='LOOKUP_N '..i..' '..tostring(v) end
for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
 out[#out+1]=string.format('LOOKUP_BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
  math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
end
local data=CSLTypes.DataCenter.sharedDataCenter().allLocalData
for key in pairs(data) do
 if type(key)=='string' and (key:lower():find('duhu') or key:lower():find('dispatch')) then out[#out+1]='LOCAL_DATA '..key end
end
local events=data[256][238][13]
local eventKeys=events:GetDictKeys();out[#out+1]='EVENT_COUNT '..eventKeys:get_Count()
local groups={}
for i=0,eventKeys:get_Count()-1 do local row=events:get_Item(eventKeys:get_Item(i))
 local g=tostring(row[13]);groups[g]=groups[g] or {n=0,stars={},samples={}}
 local group=groups[g];group.n=group.n+1;group.stars[row[2]]=true
 if #group.samples<3 then group.samples[#group.samples+1]=CSLTypes.YXSUtils.GBK2UTF8(row[4]) end
 if row[13]==1 and row[3]==4 then
  out[#out+1]=string.format('CURRENT_POOL id=%d star=%d group=%s name=%s people=%s seconds=%s conditions=%s f3=%s',
   row[1],row[2],g,CSLTypes.YXSUtils.GBK2UTF8(row[4]),tostring(row[8]),tostring(row[9]),tostring(row[6]),tostring(row[3]))
 end
end
for g,group in pairs(groups) do local stars={};for s in pairs(group.stars) do stars[#stars+1]=s end;table.sort(stars)
 out[#out+1]='GROUP '..g..' count='..group.n..' stars='..table.concat(stars,',')..' examples='..table.concat(group.samples,'/')
end
for module,p in pairs(package.loaded) do if type(module)=='string' and module:find('ProtoDes') and type(p)=='table' then
 for name,d in pairs(p) do if type(name)=='string' and (name:find('DuHuFu') or name:find('Duhu')) and type(d)=='table' then
  for _,field in ipairs(d) do if type(field)=='table' and (field.tag==1 or field.tag==2 or field.tag==12) then
   out[#out+1]='DESCRIPTOR '..module..'.'..name..' tag='..field.tag..' name='..tostring(field.name)
  end end
 end end
end end
for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end
 out[#out+1]='LOOKUP_UP '..n..' '..type(v)
 if type(v)=='table' then
  for k,x in pairs(v) do if type(k)=='string' and (k:lower():find('duhu') or k:lower():find('dispatch')) then
   out[#out+1]='CONFIG_TABLE '..k..' '..type(x)
  end end
 end
end
for _,name in ipairs({'SLGDispatchListTaskItem','SLGDispatchDialog','SLGDispatchModel'}) do
 local d=package.loaded[name].__instanceDict
 for _,key in ipairs({'SetData','SetTaskStars','UpdateItem','RefreshStar','RefreshTaskList','SortTaskInfos'}) do
  local fn=d[key]
  if type(fn)=='function' and u.funcinfo(fn).bytecodes then
   out[#out+1]='READER '..name..'.'..key
   for i=-1,-100,-1 do local v=u.funck(fn,i);if v==nil then break end
    if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..v end
   end
  end
 end
end
return table.concat(out,'\n')
