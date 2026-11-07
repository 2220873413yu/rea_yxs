-- Read the active army accessor bytecode and cached collection sizes.
local util=require('jit.util')
local _,f=debug.getupvalue(package.loaded.SLGMainModel.__instanceDict.getMyArmyInfoByHeroGroupId,1)
local out={}
for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
for i=1,8 do local v=main._myActionState[i];if v~=nil then out[#out+1]='FIELD '..i..' '..type(v)..' '..(type(v)=='table' and v.get_Count and v:get_Count() or type(v)=='number' and v or '') end end
return table.concat(out,'\n')
