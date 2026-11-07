-- Inspect hero/follower/scout selection implementations without constructing UI or issuing an order.
local out={};local u=require('jit.util')
for _,name in ipairs({'SLGChooseHeroLogicFengHuoTaiSave','SLGChooseHeroLogicCollectResource','SLGChooseHeroLogicMonster',
 'SLGChooseHeroLogicBase','SLGScoutDialog','SLGChooseHeroScene','SLGMainController'}) do
 pcall(function() return CSLTypes[name] end)
 local cls=package.loaded[name];local d=type(cls)=='table' and cls.__instanceDict
 out[#out+1]='MODULE '..name..' '..type(d)
 if d then for key,f in pairs(d) do if type(key)=='string' and type(f)=='function' and u.funcinfo(f).bytecodes and
  (name=='SLGChooseHeroLogicFengHuoTaiSave' or
   (name=='SLGScoutDialog' and not key:find('LuaBehaviour') and not key:find('Stage') and not key:find('Bindings')) or
   key:lower():find('soldier') or key=='startTrip2' or key=='getSoldierCount' or
   (name=='SLGMainController' and key:lower():find('scout'))) then
  local ks={}
  for i=-1,-120,-1 do local v=u.funck(f,i);if v==nil then break end
   if type(v)=='string' and not v:find('[\128-\255]') then ks[#ks+1]=v end
  end
  out[#out+1]='METHOD '..name..'.'..key..' '..table.concat(ks,'|')
 end end end
end
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local r=m:getTSLGGetBeaconTowerInfoRsp();local s=CSLTypes.DBSearcher.sharedInstance()
if r then for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i);local c=s:searchTMapIntelStation_Event_Map(e[2])
 out[#out+1]=string.format('CACHED_EVENT config=%d kind=%s object_type=%s state=%s start=%s end=%s army=%s',
  e[2],tostring(c[2]),tostring(e[1][3]),tostring(e[3]),tostring(e[5]),tostring(e[6]),tostring(e[4]))
end end
return table.concat(out,'\n')
