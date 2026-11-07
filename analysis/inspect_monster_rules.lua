-- Inspect pure comparison and monster configuration functions; do not execute UI actions or senders.
local util=require('jit.util');local out={}
local function dump(name,f)
 local inf=util.funcinfo(f);out[#out+1]='FUNCTION '..name..' params='..tostring(inf.params)
 if not inf.bytecodes then return end
 for i=-1,-140,-1 do local v=util.funck(f,i);if v==nil then break end
  out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v)
  if type(v)=='table' then for k,x in pairs(v) do if type(x)=='number' or type(x)=='string' then out[#out+1]='KT '..tostring(k)..'='..tostring(x) end end end
 end
 for i=0,45 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,15 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 for pc=1,math.min(420,inf.bytecodes-1) do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
local f=package.loaded.SLGChooseHeroArmyInfo.__instanceDict.setCombatValue
local _,tip=debug.getupvalue(f,1);dump('updateCombateValueTips',tip)
for _,pair in ipairs({{'SLGMainModel','getQuestCombatValue'}, {'SLGMapMonster','SetData'},
 {'SLGMonsterDetailDialog','setData'}, {'SLGMonsterDetailDialog','SetData'},
 {'SLGMainController','sendTSLGGetAvailHeroListReq'},{'SLGWildMonsterModel','SetMonsterAttackByArmy'}}) do
 local fn=package.loaded[pair[1]] and package.loaded[pair[1]].__instanceDict[pair[2]]
 if type(fn)=='function' then dump(table.concat(pair,'.'),fn) end
end
for _,name in ipairs({'SLGMapMonster','SLGMonsterDetailDialog'}) do
 for k,v in pairs(package.loaded[name].__instanceDict) do
  if type(v)=='function' and util.funcinfo(v).bytecodes then
   local ks={};for i=-1,-120,-1 do local x=util.funck(v,i);if x==nil then break end;if type(x)=='string' then ks[#ks+1]=x end end
   out[#out+1]='METHOD '..name..'.'..k..' '..table.concat(ks,'|')
  end
 end
end
return table.concat(out,'\n')
