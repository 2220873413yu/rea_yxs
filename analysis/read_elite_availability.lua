-- Read native elite admission time rules before a user-authorized retry; never enter or leave a room.
local mm=CSLTypes.ModelManager.sharedInstance();local m=mm:getModel(CSLTypes.EliteLevelModel)
local p=m:getProgressMsg();local out={}
out[#out+1]='server_nature_time='..tostring(CSLTypes.RefreshTimer.getServerNatureTimeNow())
out[#out+1]='native_open_now='..tostring(m:handleEliteOpenTime())
out[#out+1]='current_group='..tostring(p[6])
local times=p[4]
if type(times)=='table' and times.get_Count then
 for i=0,times:get_Count()-1 do local t=times:get_Item(i)
  out[#out+1]='open_period='..tostring(t[1])..'-'..tostring(t[2])
 end
end
return table.concat(out,'\n')
