-- Resolve the server error through the game's own error-message configuration, read only.
local util=require('jit.util')
local out={}
local cls=package.loaded.CommonFunc or CSLTypes.CommonFunc
local methods=type(cls)=='table' and (cls.__instanceDict or cls)
local f=methods and methods.showErrMsg
out[#out+1]='SHOW_ERROR '..type(f)
if type(f)=='function' then
 for i=-1,-60,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..'='..v end end
end
local search=CSLTypes.DBSearcher.sharedInstance()
local db=package.loaded.DBSearcher
local dict=type(db)=='table' and (db.__instanceDict or db)
if dict then for k,v in pairs(dict) do if type(k)=='string' and (string.find(k,'Err') or string.find(k,'Ret')) then out[#out+1]='DB '..k..' '..type(v) end end end
return table.concat(out,'\n')
