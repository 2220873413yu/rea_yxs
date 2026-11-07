-- Enumerate already received monster positions/configuration/status; no requests and no camera movement.
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
local monster=manager:getModel(CSLTypes.SLGWildMonsterModel)
local search=CSLTypes.DBSearcher.sharedInstance()
local home=map:getMyMainCityCoordinates()
local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
local out,rows,seen={},{},{}
for i=0,chunks:get_Count()-1 do
 local c=chunks:get_Item(i).mViewDataCache
 if c:ContainsKey(3000) then
  local points=c:get_Item(3000);local keys=points:GetDictKeys()
  for j=0,keys:get_Count()-1 do
   local key=keys:get_Item(j)
   if not seen[key] then seen[key]=true
    local p=points:get_Item(key);local pos=p[1][1]
    rows[#rows+1]={p=p,pos=pos,key=key,distance=CSLTypes.SLGMapUtils.calMapP2PDistance(home,pos)}
   end
  end
 end
end
table.sort(rows,function(a,b) return a.distance<b.distance end)
out[#out+1]='MONSTER_COUNT '..#rows
for i=1,math.min(8,#rows) do
 local r=rows[i];local p=r.p;local shown=CSLTypes.SLGMapUtils.logicToDisplay(r.pos)
 out[#out+1]='MONSTER id='..p[1][2]..' pos='..shown[1]..','..shown[2]..' config='..p[2]..' distance='..r.distance..' state='..monster:GetMonsterState(r.key)..' attacker='..tostring(monster:GetMonsterArmyId(r.key))
 local config=search:searchTWildMonster_Map(p[2])
 if i<=3 then for k,v in pairs(config) do if type(v)=='number' or type(v)=='string' then
  local text=type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v)
  out[#out+1]='CONFIG '..k..'='..text
 end end end
end
for k,v in pairs(package.loaded.SLGWildMonsterModel.__instanceDict) do if type(v)=='number' then out[#out+1]='STATE_CONST '..k..'='..v end end
for _,powers in ipairs({{44999,30000},{45000,30000},{45001,30000},{174900,30000},{15000,30000}}) do
 local r=CSLTypes.GlobalVariable.getCombatWinRatioInfo(powers[1],powers[2])
 out[#out+1]='RATIO_CONFIG '..powers[1]..'/'..powers[2]
 if r then for k,v in pairs(r) do if type(v)=='number' or type(v)=='string' then out[#out+1]='RATIO_FIELD '..k..'='..(type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v)) end end end
end
return table.concat(out,'\n')
