-- Inspect existing return handlers and army cache only; never send a game request.
local util=require('jit.util')
local out={}
for _,name in ipairs({'SLGMainController','SLGMainModel'}) do
 local methods=package.loaded[name].__instanceDict
 local keys={}
 for key,fn in pairs(methods) do
  if type(key)=='string' and type(fn)=='function' and
   (key:find('Army') or key:find('Return') or key:find('Recall') or key:find('CollectionArmy')) then keys[#keys+1]=key end
 end
 table.sort(keys)
 for _,key in ipairs(keys) do
  local fn=methods[key]
  local constants={}
  for i=-1,-90,-1 do
   local value=util.funck(fn,i);if value==nil then break end
   if type(value)=='string' then constants[#constants+1]=value end
  end
  out[#out+1]=name..'.'..key..' '..table.concat(constants,'|')
  if key=='checkMaxCollectionArmyCount' or key=='getMaxCollectionArmyCount' then
   for pc=1,util.funcinfo(fn).bytecodes-1 do
    local bc=util.funcbc(fn,pc)
    out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
   end
  end
 end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
out[#out+1]='QUEUE_FULL '..tostring(main:checkMaxCollectionArmyCount())..' LIMIT '..tostring(main:getMaxCollectionArmyCount())
local army=main._myActionState
for k,v in pairs(army or {}) do
 if type(k)=='number' and type(v)=='number' then out[#out+1]='ARMY_RSP '..k..'='..v end
end
for _,index in ipairs({2,3}) do
 local list=army and army[index]
 if type(list)=='table' and list.get_Count then
  out[#out+1]='ARMY_LIST '..index..' COUNT '..list:get_Count()
  for i=0,list:get_Count()-1 do
   local row=list:get_Item(i);local fields={}
   for k=1,14 do if type(row[k])=='number' then fields[#fields+1]=k..'='..row[k] end end
   if type(row[15])=='table' then fields[#fields+1]='hero='..tostring(row[15][1]) end
   out[#out+1]=table.concat(fields,',')
  end
 end
end
return table.concat(out,'\n')
