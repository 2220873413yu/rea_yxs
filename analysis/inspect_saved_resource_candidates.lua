-- Read cached resource points for the user's saved coordinates; never query or send an action.
local out={}
local wanted={['102,194']=true,['108,190']=true,['102,181']=true,['71,183']=true}
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local search=CSLTypes.DBSearcher.sharedInstance()
local home=map:getMyMainCityCoordinates()
local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
local seen={}
for i=0,chunks:get_Count()-1 do
 local chunk=chunks:get_Item(i).mViewDataCache
 if chunk:ContainsKey(1000) then
  local points=chunk:get_Item(1000);local keys=points:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local key=keys:get_Item(j)
   if not seen[key] then
    seen[key]=true
    local pos=CSLTypes.SLGMapUtils.keyToPos(key)
    local shown=CSLTypes.SLGMapUtils.logicToDisplay(pos)
    local text=shown[1]..','..shown[2]
    if wanted[text] then
     local point=points:get_Item(key);local config=search:searchTNewPlay_Resource_Map(point[2])
     out[#out+1]=text..' kind='..config[3]..' level='..config[2]..' distance='..math.max(0,CSLTypes.SLGMapUtils.calMapP2PDistance(home,pos)-1)..' cached_quantity='..point[6]..' occupants='..point[4]:get_Count()
    end
   end
  end
 end
end
return table.concat(out,'\n')
