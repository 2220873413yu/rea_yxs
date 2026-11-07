-- Borrow the exact hero objects from the native chooser populated by this experiment's successful11012 response.
-- This only updates the experiment observer's local view; it sends no packet and does not select any hero.
local api=assert(REA_TRIAL_ONE_LAYER)
assert(api.availableSent and not api.selectSent and not api.challengeSent,'Unexpected experiment stage')
local popup=assert(CSLTypes.PopUtils.findPopLayout(CSLTypes.SLGTowerChooseHeroScene),'Native chooser missing')
local data=assert(popup.multiChooseHeroScene._chooseData,'Received native roster missing')
local rows=CSLNew(CSLTypes.CSLList)
for i=0,data:get_Count()-1 do rows:Add(data:get_Item(i).availHero)end
assert(rows:get_Count()>0,'Native received roster is empty')
local target
for i=1,15 do local n,v=debug.getupvalue(api.query_available,i);if not n then break end;if n=='target'then target=v end end
assert(target and target==CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGTowerModel):getMainData()[12],'Target changed')
local observer
for i=1,15 do local n,v=debug.getupvalue(api.close,i);if not n then break end;if n=='observer'then observer=v end end
assert(observer,'Experiment observer missing')
observer:updateSelf({id=1060,updateData={0,target,16,rows}})
return 'received_native_ui_roster_captured; heroes='..rows:get_Count()
