-- Read the named elite defenders from local NPC configuration, without entering a room.
local out={};local s=CSLTypes.DBSearcher.sharedInstance()
for _,id in ipairs({2009,2008,2061,2040,2032,2047}) do local n=s:searchNPCInfo(id)
 out[#out+1]='NPC '..id
 if n then for k,v in pairs(n) do if type(k)=='number' and k<=12 and (type(v)=='string' or type(v)=='number') then
  out[#out+1]='F '..k..'='..(type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v))
 end end end
end
local u=require('jit.util');local d=package.loaded.EliteChooseHeroScene.__instanceDict
for k,f in pairs(d) do if type(f)=='function' and u.funcinfo(f).bytecodes then
 local ks={};local found=false
 for i=-1,-120,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then ks[#ks+1]=v;if v=='mVecNPCIds' then found=true end end end
 if found then out[#out+1]='METHOD '..k..' '..table.concat(ks,'|') end
end end
return table.concat(out,'\n')
