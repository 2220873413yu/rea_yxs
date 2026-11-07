-- Aggregate cached report records using the game's native template and reward eligibility rules.
local out={};local mm=CSLTypes.ModelManager.sharedInstance()
local model=mm:getModel(CSLTypes.SLGBuildingsModel);local r=model:getTSLGGetAllEmailRsp()
local main=mm:getModel(CSLTypes.SLGMainModel)
out[#out+1]='SERVER_NOW_MS='..tostring(CSLTypes.SLGMainModel.GetMapTimeNow())
out[#out+1]='CACHE_MAP='..tostring(model:getmapId4MilitaryNews())
out[#out+1]='CURRENT_MAP='..tostring(main:getCurrentMapId())
if not r or r[1]~=0 then return table.concat(out,'\n')..'\nNO_SUCCESSFUL_CACHE'end
local db=CSLTypes.DBSearcher.sharedInstance();local groups={};local states={};local pendingGroups={};local pending=0;local unique={};local duplicates=0
local oldest,newest,oldPending,newPending
for i=0,r[2]:get_Count()-1 do local row=r[2]:get_Item(i);local cfg=db:searchMilitaryNewsItemInfo(row[2])
 if unique[row[1]]then duplicates=duplicates+1 else unique[row[1]]=true end
 local cat=cfg and cfg[2]or -1;groups[cat]=(groups[cat]or 0)+1
 local state=row[5];states[state]=(states[state]or 0)+1
 local eligible=cfg and(cfg[4]==3 or cfg[4]==5 or cfg[4]==6)and state==0 and row[4]and row[4]:get_Count()>0
 local at=row[7]
 if type(at)=='number'then oldest=oldest and math.min(oldest,at)or at;newest=newest and math.max(newest,at)or at end
 if eligible then
  pending=pending+1
  pendingGroups[cat]=(pendingGroups[cat]or 0)+1
  if type(at)=='number'then oldPending=oldPending and math.min(oldPending,at)or at;newPending=newPending and math.max(newPending,at)or at end
 end
end
out[#out+1]='TOTAL='..r[2]:get_Count();out[#out+1]='DUPLICATES='..duplicates;out[#out+1]='CLAIMABLE='..pending
out[#out+1]='OLDEST_SEC='..tostring(oldest);out[#out+1]='NEWEST_SEC='..tostring(newest)
out[#out+1]='OLDEST_CLAIMABLE_SEC='..tostring(oldPending);out[#out+1]='NEWEST_CLAIMABLE_SEC='..tostring(newPending)
for k,v in pairs(groups)do out[#out+1]='CATEGORY '..k..'='..v end
for k,v in pairs(pendingGroups)do out[#out+1]='CLAIMABLE_CATEGORY '..k..'='..v end
for k,v in pairs(states)do out[#out+1]='REWARD_STATE '..tostring(k)..'='..v end
for _,name in ipairs({'TUserGameArmyEmailInfo','TGlobalVariable'})do
 local proto=package.loaded.ChatClientProtoDes[name]or package.loaded.GameDBConfigProtoDes[name]
 out[#out+1]='SCHEMA '..name
 for i,f in ipairs(proto or{})do out[#out+1]='FIELD lua='..i..' tag='..f.tag..' '..f.name end
end
for _,id in ipairs({102023,102024,102025})do local cfg=db:searchGlobalVariable(id)
 if cfg then for k,v in pairs(cfg)do if type(v)=='number'then out[#out+1]='GLOBAL '..id..'['..tostring(k)..']='..v end end end
end
local c=package.loaded.SLGBuildingsController.__instanceDict
for i=1,10 do local name,value=debug.getupvalue(c.sendTSLGGetAllEmailReq,i);if not name then break end
 if name=='T_ID'then out[#out+1]='LIST_PROTOCOL='..tostring(value.E_SVR_MSG_ID_SLG_GET_USER_EMAIL)end
end
return table.concat(out,'\n')
