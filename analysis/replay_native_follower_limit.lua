-- Replay only native default follower arithmetic with fake UI slots, never constructing scenes or sending requests.
local f=package.loaded.SLGChooseHeroScene.__instanceDict.updateSoldier
local out={};local counts={}
local function slot(name)
 return {setSodierId=function() end,setNum=function(self,n) counts[name]=n end,
  getNum=function() return counts[name] or 0 end,setFreeNum=function() end}
end
local options=CSLNew(CSLTypes.CSLList);options:Add({[1]=411,[2]=50})
local fake={_currentSelectedHero={[2]=options},_soldierLeft=slot('left'),_soldierRight=slot('right')}
local ok=pcall(f,fake)
local cap=CSLTypes.SLGMainModel.getMaxSoldierForFight(411)
return string.format('{"native_total_cap":%d,"native_left":%d,"native_right":%d,"arithmetic_captured":%s,"full_fake_ui_completed":%s}',
 cap,counts.left or -1,counts.right or -1,tostring(counts.left~=nil and counts.right~=nil),tostring(ok))
