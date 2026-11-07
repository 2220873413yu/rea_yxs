-- Read native collection rules/aim enums and current own-army phase without issuing any network command.
local u=require('jit.util');local out={}
local function dump(name,f)
 if type(f)~='function' or not u.funcinfo(f).bytecodes then return end
 out[#out+1]='FUNCTION '..name..' params='..u.funcinfo(f).params
 for i=-1,-100,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
 for i=0,20 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for pc=1,math.min(260,u.funcinfo(f).bytecodes-1) do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
for _,p in ipairs({{'SLGMapLeagueResource','onClick'},{'SLGMapLeagueResource','updateSelf'},
 {'SLGChooseHeroLogicLeagueCollect','getTargetID2'},{'SLGChooseHeroLogicLeagueCollect','startTrip2'},
 {'SLGChooseHeroLogicLeagueCollect','getHeroFlags'},{'SLGMainModel','isCollectAimType'},
 {'SLGMainModel','checkMaxCollectionArmyCount'},{'SLGLeagueController','sendTSLGLeagueGetResourceReq'},
 {'SLGLeagueModel','getLeagueCollectDataByArmyId'}}) do
 local cls=package.loaded[p[1]];dump(table.concat(p,'.'),cls and cls.__instanceDict[p[2]])
end
local manager=CSLTypes.ModelManager.sharedInstance();local main=manager:getModel(CSLTypes.SLGMainModel)
local list=main._myActionState and main._myActionState[2]
if list then for i=0,list:get_Count()-1 do
 local a=list:get_Item(i)
 if a[5]~=1 and a[5]~=3 then
  out[#out+1]='OWN_ARMY id='..a[1]..' aim='..a[5]..' stage='..a[4]..' target='..a[6]..' secondary='..tostring(a[7])..' hero='..a[15][1]..' end='..tostring(a[11])
 end
end end
for _,name in ipairs({'SLGMapLeagueResource','SLGLeagueModel','SLGMapObjectModel'}) do
 local cls=package.loaded[name]
 for key,f in pairs(cls.__instanceDict) do
  if type(key)=='string' and type(f)=='function' and u.funcinfo(f).bytecodes and
   (name=='SLGMapLeagueResource' or key:lower():find('league') or key:lower():find('building')) then
   local keys={};for i=-1,-80,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then keys[#keys+1]=v end end
   out[#out+1]='METHOD '..name..'.'..key..' '..table.concat(keys,'|')
  end
 end
end
return table.concat(out,'\n')
