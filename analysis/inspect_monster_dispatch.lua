-- Inspect exact native request arguments before a single user-authorized departure.
local util=require('jit.util');local out={}
for _,p in ipairs({{'SLGChooseHeroLogicMonster','getTargetID2'},{'SLGMainController','sendTSLGSitDownClientReq'},
 {'SLGSitdownPromptDialog','Start'},{'SLGSitdownPromptDialog','updateContent'},
 {'SLGMainModel','getMaxCombateArmyCount'},{'SLGMainModel','checkMaxCombateArmyCount'}}) do
 local f=package.loaded[p[1]].__instanceDict[p[2]]
 if type(f)=='function' and util.funcinfo(f).bytecodes then
 out[#out+1]='FUNCTION '..table.concat(p,'.')..' params='..util.funcinfo(f).params
 for i=-1,-110,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' and not string.find(v,'[\128-\255]') then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=0,20 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for i=1,15 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
return table.concat(out,'\n')
