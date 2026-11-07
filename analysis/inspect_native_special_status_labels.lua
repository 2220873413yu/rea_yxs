-- Evaluate native label formatting against dummy Lua-only UI tables; no real UI or game state is changed.
local manager=CSLTypes.ModelManager.sharedInstance()
local heroes=manager:getModel(CSLTypes.SLGBuildingsModel):getTSLGGetHeroPubRsp()[2][2][1]
local methods=package.loaded.SLGChooseHeroItem.__instanceDict
local out={}
local function object() return {gameObject={SetActive=function() end}} end
for i=0,heroes:get_Count()-1 do
 local hero=heroes:get_Item(i)
 if hero[2]==20 then
  local ok,action=pcall(methods.getActionState,{[1]=hero})
  if ok then
   local dummy={_itemData={actionState=action},stateArea=object(),actionStateTipArea=object(),clickArea={},actionStateTip={}}
   local shown,err=pcall(methods.updateActionState,dummy)
   out[#out+1]='hero='..hero[1][3]..' raw='..hero[2]..' action='..tostring(action)..' label='..tostring(dummy.actionStateTip.text)..' label_ok='..tostring(shown)
   if not shown then out[#out+1]=tostring(err) end
  else out[#out+1]='hero='..hero[1][3]..' raw=20 conversion_error='..tostring(action) end
 end
end
return table.concat(out,'\n')
