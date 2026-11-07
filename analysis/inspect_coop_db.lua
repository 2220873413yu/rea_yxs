-- Inspect local DB routing and group-create call sites; never execute a sender.
local u=require('jit.util');local out={}
for _,p in ipairs({{'DBSearcher','searchAllQuestsByScene'},{'DBSearcher','searchQuestInfo'},
 {'PVEModel','getAllQuestsOfCurScene'},{'RankMatchController','sendTCreateMatchGroupReq'}}) do
 local f=package.loaded[p[1]].__instanceDict[p[2]];out[#out+1]='METHOD '..table.concat(p,'.')..' params='..tostring(u.funcinfo(f).params)
 for i=-1,-90,-1 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='K '..i..' '..tostring(v) end
 for i=1,8 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..n..' '..type(v) end
end
for name,c in pairs(package.loaded) do
 if type(name)=='string' and type(c)=='table' and c.__instanceDict then
  for k,f in pairs(c.__instanceDict) do if type(f)=='function' and u.funcinfo(f).bytecodes then
   local match=false;local ks={}
   for i=-1,-110,-1 do local v=u.funck(f,i);if v==nil then break end
    if type(v)=='string' then ks[#ks+1]=v
     if v=='sendTFiendCreateGroupReq' or v=='sendTFiendJoinGroupReq' or v=='sendTFiendStartGameReq' or v=='扬州关隘' or v=='好友组队' then match=true end
    end
   end
   if match then out[#out+1]='ROUTE '..name..'.'..tostring(k)..' '..table.concat(ks,'|') end
  end end
 end
end
return table.concat(out,'\n')
