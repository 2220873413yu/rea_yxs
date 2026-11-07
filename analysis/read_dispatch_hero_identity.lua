-- Resolve dispatch card IDs to world hero groups from local config, without guessing by arithmetic.
local out={};local s=CSLTypes.DBSearcher.sharedInstance()
for _,id in ipairs({4101,4233,4308,4325,3201,1306,4219,316}) do local c=s:searchHeroInfo(id)
 out[#out+1]='CARD '..id
 if c then for k,v in pairs(c) do if type(k)=='number' and k<=12 and (type(v)=='string' or type(v)=='number') then
  out[#out+1]='C '..k..'='..(type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v))
 end end end
end
for _,module in ipairs({'ClientUseOnlyProtoDes','TaskServerClientProtoDes'}) do
 local p=package.loaded[module]
 if p and p.THeroBriefInfo then for _,f in ipairs(p.THeroBriefInfo) do out[#out+1]='BRIEF tag='..f.tag..' name='..f.name end end
end
return table.concat(out,'\n')
