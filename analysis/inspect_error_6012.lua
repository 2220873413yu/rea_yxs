-- Read the configured meaning of the returned code, without displaying a toast or sending requests.
local row=CSLTypes.DBSearcher.sharedInstance():searchHallError(6012)
local out={}
if type(row)=='table' then
 for k,v in pairs(row) do
  if type(v)=='string' then out[#out+1]=tostring(k)..'='..CSLTypes.YXSUtils.GBK2UTF8(v)
  elseif type(v)=='number' then out[#out+1]=tostring(k)..'='..v end
 end
end
return table.concat(out,'\n')
