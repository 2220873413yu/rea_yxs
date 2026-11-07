-- Evaluate the game's pure recommendation function and inspect monster configuration/status mappings.
local util=require('jit.util');local out={}
local _,update=debug.getupvalue(package.loaded.SLGChooseHeroArmyInfo.__instanceDict.setCombatValue,1)
local _,tip=debug.getupvalue(update,1)
local function dump(label,f)
 out[#out+1]='FUNCTION '..label
 for i=-1,-120,-1 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v) end
 for i=0,50 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
dump('getCombateValueTips',tip)
for _,ratio in ipairs({0.5,0.9,1,1.01,1.1,1.2,1.3,1.49,1.5,1.51,1.99,2,2.01,3,5.83}) do
 local result=tip(math.floor(30000*ratio),30000)
 local values={}
 for i=0,result.Length-1 do values[#values+1]=tostring(CSLArrayGet(result,i)) end
 out[#out+1]='COMPARE ratio='..ratio..' result='..table.concat(values,'|')
end
dump('monsterSetContent',package.loaded.SLGMonsterDetailDialog.__instanceDict.setContent)
return table.concat(out,'\n')
