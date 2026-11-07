-- Read the native ownership predicate bytecode and trip observer surface without side effects.
local out={}
local util=require('jit.util')
local fn=package.loaded.SLGMainModel.__instanceDict.checkIsMyArmy
out[#out+1]='params='..util.funcinfo(fn).params
for i=-1,-20,-1 do local v=util.funck(fn,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
for pc=1,util.funcinfo(fn).bytecodes-1 do
 local bc=util.funcbc(fn,pc)
 out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
end
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local trip=manager:getModel(CSLTypes.SLGArmyTripModel)
out[#out+1]='trip add='..type(trip.addObserver)..' remove='..type(trip.removeObserver)
local armies=main._myActionState[2]
for i=0,armies:get_Count()-1 do
 local army=armies:get_Item(i)
 local ok,result=pcall(main.checkIsMyArmy,army)
 out[#out+1]='own_check='..tostring(ok)..','..tostring(result)
end
return table.concat(out,'\n')
