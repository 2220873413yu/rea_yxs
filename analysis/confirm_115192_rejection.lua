-- Attribute the server rejection and confirm no army was created for this attempt.
local out={};local manager=CSLTypes.ModelManager.sharedInstance()
local r=CSLTypes.DBSearcher.sharedInstance():searchHallError(6109)
for k,v in pairs(r or {}) do if type(v)=='string' then out[#out+1]='ERROR '..CSLTypes.YXSUtils.GBK2UTF8(v) end end
local m=manager:getModel(CSLTypes.SLGMainModel)
local a=m:getMyArmyInfoByHeroGroupId(307)
out[#out+1]='HERO_307_ARMY '..tostring(a and a[1] or 'none')
local fog=manager:getModel(CSLTypes.SLGWarFogModel)
out[#out+1]='VISIBLE '..tostring(fog:isCellVisible(115,58,0))
return table.concat(out,'\n')
