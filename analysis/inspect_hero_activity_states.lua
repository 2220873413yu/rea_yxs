-- Read current hero/army associations and native status labels without any server request.
local out={}
local util=require('jit.util')
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local buildings=manager:getModel(CSLTypes.SLGBuildingsModel)
local heroes=buildings:getTSLGGetHeroPubRsp()[2][2][1]
local function name(id)
 local config=CSLTypes.DBSearcher.sharedInstance():searchHeroInfoByStarAndGroup(1,id)
 return CSLTypes.YXSUtils.GBK2UTF8(config[7])
end
for i=0,heroes:get_Count()-1 do
 local hero=heroes:get_Item(i)
 if hero[2]~=0 then out[#out+1]='HERO '..hero[1][3]..' '..name(hero[1][3])..' state='..hero[2]..' recovery_end_ms='..string.format('%.0f',hero[3]) end
end
for _,index in ipairs({2,3}) do
 local armies=main._myActionState[index]
 for i=0,armies:get_Count()-1 do
  local army=armies:get_Item(i)
  out[#out+1]='ARMY list='..index..' id='..army[1]..' hero='..army[15][1]..' '..name(army[15][1])..' state='..army[4]..' aim='..army[5]..' end_ms='..string.format('%.0f',army[11])
 end
end
for _,module in ipairs({'SLGChooseHeroItem','HeroPalaceItem','SLGArmyModel'}) do
 local methods=package.loaded[module].__instanceDict
 for key,fn in pairs(methods) do
  if type(key)=='string' and type(fn)=='function' and (key:find('State') or key:find('Status') or key:find('Idle')) then
   local constants={}
   for i=-1,-90,-1 do local v=util.funck(fn,i);if v==nil then break end;if type(v)=='string' then constants[#constants+1]=v end end
   out[#out+1]='METHOD '..module..'.'..key..' '..table.concat(constants,'|')
  end
 end
end
local fn=package.loaded.SLGChooseHeroItem.__instanceDict.getActionState
out[#out+1]='FUNCTION getActionState'
for i=0,40 do local v=util.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
for pc=1,util.funcinfo(fn).bytecodes-1 do local bc=util.funcbc(fn,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
return table.concat(out,'\n')
