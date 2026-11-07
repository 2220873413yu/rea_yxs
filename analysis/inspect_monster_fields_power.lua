-- Read local monster rows and power-comparison functions without sending requests or starting combat.
local util=require('jit.util');local out={}
pcall(require,'SLGChooseHeroArmyInfo')
local function dump(name,f)
 local info=util.funcinfo(f);out[#out+1]='FUNCTION '..name..' params='..tostring(info.params)
 if not info.bytecodes then return end
 for i=-1,-120,-1 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v) end
 for i=0,35 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 for pc=1,math.min(250,info.bytecodes-1) do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
for name,cls in pairs(package.loaded) do
 local m=type(cls)=='table' and cls.__instanceDict
 if type(m)=='table' then for k,f in pairs(m) do
  if type(f)=='function' and (k=='setCombatValue' or k=='getMyCombatValue' or k=='getEnemyCombatValue' or
   (name=='SLGMonsterDetailDialog' and (k=='SetData' or k=='updateSelf' or k=='initUI')) or
   (name=='SLGMainController' and (k=='sendTSLGGetMonsterDetailReq' or k=='parseTSLGMonsterGetAvailHeroListRsp')) or
   (name=='SLGWildMonsterModel' and (k=='GetMonsterState' or k=='SetMonsterAttackByArmy')) or
   (name=='SLGMapObjectModel' and k=='getWildMonster')) then dump(name..'.'..k,f) end
 end end
end
local map=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMapObjectModel)
local all=map.mInViewDataChunkCacheManager:getAllViewData();local shown={}
for i=0,all:get_Count()-1 do
 local chunk=all:get_Item(i).mViewDataCache
 local keys=chunk:GetDictKeys()
 for j=0,keys:get_Count()-1 do
  local kind=keys:get_Item(j)
  if not shown[kind] then
   shown[kind]=true;local d=chunk:get_Item(kind);out[#out+1]='VIEW_TYPE '..tostring(kind)..' count='..d:get_Count()
   if kind~=1000 and d:get_Count()>0 then
    local p=d:get_Item(d:GetDictKeys():get_Item(0))
    local fields={}
    for k,v in pairs(p) do if type(v)=='number' then fields[#fields+1]=tostring(k)..'='..tostring(v) elseif type(v)=='table' and type(v[1])=='table' and type(v[1][1])=='number' then
     if type(v[1][2])=='number' then local ok,pos=pcall(CSLTypes.SLGMapUtils.logicToDisplay,v[1]);if ok then fields[#fields+1]='common['..k..']id='..tostring(v[2])..' pos='..pos[1]..','..pos[2] end end
    end end
    out[#out+1]='SAMPLE '..table.concat(fields,' ')
   end
  end
 end
end
return table.concat(out,'\n')
