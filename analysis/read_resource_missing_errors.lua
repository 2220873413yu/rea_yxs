-- Read configured missing-target errors only; do not send a request or modify game state.
local out={};local search=CSLTypes.DBSearcher.sharedInstance()
for code=6000,6300 do
 local r=search:searchHallError(code)
 if type(r)=='table' then for _,v in pairs(r) do if type(v)=='string' then
  local s=CSLTypes.YXSUtils.GBK2UTF8(v)
  if s:find('不存在') or s:find('消失') or s:find('资源') or s:find('目标') then out[#out+1]=code..' '..s end
 end end end
end
return table.concat(out,'\n')
