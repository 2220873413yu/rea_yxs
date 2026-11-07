-- Read active-army cache and response layout only; no game actions.
local out={}
local util=require('jit.util')
for _,t in ipairs({{'SLGMainController','parseTSLGGetAllArmyRsp'},{'SLGMainModel','updateTSLGGetAllArmyRsp'}}) do
 local f=package.loaded[t[1]].__instanceDict[t[2]]
 out[#out+1]=t[1]..'.'..t[2]..' '..type(f)
 if type(f)=='function' then
 for i=-1,-65,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..'='..v end end
 for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
for _,id in ipairs({303,305,315}) do
 local army=main:getMyArmyInfoByHeroGroupId(id)
 out[#out+1]='HERO '..id..' army='..type(army)
 if type(army)=='table' then for i=1,25 do local v=rawget(army,i);if type(v)=='number' or type(v)=='string' then out[#out+1]='FIELD '..i..'='..tostring(v) end end end
end
for k,v in pairs(main) do if type(k)=='string' and (string.find(k,'Army') or string.find(k,'Action')) then out[#out+1]='MAIN '..k..' '..type(v) end end
return table.concat(out,'\n')
