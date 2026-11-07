-- Read current co-op quest and the native room-to-quest mapping; no room or battle operation is invoked.
local u=require('jit.util');local out={}
local f=package.loaded.MatchTherRoomModel.__instanceDict.get_quest
for i=-1,-80,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
for i=0,20 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
 out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
end
local mm=CSLTypes.ModelManager.sharedInstance();local m=mm:getModel(CSLTypes.MatchTherRoomModel)
local ok,q=pcall(m.get_quest,m);out[#out+1]='CURRENT_QUEST '..tostring(ok)..' '..type(q)
if ok and type(q)=='table' then for k,v in pairs(q) do if type(k)=='number' and (type(v)=='number' or type(v)=='string') then
 out[#out+1]='Q '..k..'='..(type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v))
end end end
local r=m:get_fiendGroupRoomInfo()
if type(r)=='table' then for k,v in pairs(r) do if type(k)=='number' and type(v)=='number' then out[#out+1]='ROOM_FIELD '..k..'='..tostring(v) end end end
local data=CSLTypes.DataCenter.sharedDataCenter().allLocalData
for k,v in pairs(data) do if type(k)=='string' and (k:lower():find('quest') or k:lower():find('scene') or k:lower():find('npc')) then out[#out+1]='DB '..k..' '..type(v) end end
return table.concat(out,'\n')
