-- Inspect cached stock getter availability only; no network query or action is sent.
local model=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGBuildingsModel)
local out={'getSoldierInfoById='..type(model.getSoldierInfoById),
 'getTSLGGetBarrackRsp='..type(model.getTSLGGetBarrackRsp)}
local r=model:getTSLGGetBarrackRsp()
out[#out+1]='barrack_ret='..tostring(r and r[1])
if r and r[1]==0 then local s=r[4]:get_Item(803)
 out[#out+1]='scout_cached_count='..tostring(s and s[3] and s[3][1])
end
return table.concat(out,'\n')
