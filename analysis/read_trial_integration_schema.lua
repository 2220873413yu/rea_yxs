-- Read request field tags and declarations needed for attributable production receipts.
local out={}
for _,n in ipairs({'TSLGSitDownClientReq','TSLGQCTChooseTrialHeroReq','TSLGGetQCTQuestProfileInfoRsp'})do
 out[#out+1]=n
 for i,f in ipairs(package.loaded.ChatClientProtoDes[n] or {})do if type(f)=='table'then out[#out+1]=i..' '..f.tag..' '..f.name end end
end
return table.concat(out,'\n')
