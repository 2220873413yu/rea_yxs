-- Inspect declarations and current event configs only; never invoke scout/trip/retreat/reward callbacks.
local out={};local u=require('jit.util');local seen={}
local function dump(label,f,depth)
 if type(f)~='function' or seen[f] then return end;seen[f]=true
 local info=u.funcinfo(f);if not info.bytecodes then return end
 out[#out+1]='FUNCTION '..label..' params='..info.params
 for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end
  if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..i..' '..v end
 end
 for i=0,35 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 local nested={}
 for i=1,25 do local n,v=debug.getupvalue(f,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if type(v)=='function' then nested[#nested+1]={n,v} end
 end
 for pc=1,info.bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 if depth>0 then for _,p in ipairs(nested) do dump(label..'.UP.'..p[1],p[2],depth-1) end end
end
for _,p in ipairs({{'SLGFengHuoTaiMonsterDetailDialog','onFightBtnClick'},
 {'CommonClientFunc','showSLGChooseHeroDialog'},{'SLGMainController','sendTSLGGetAvailHeroListReq'},
 {'SLGFengHuoTaiMonsterDetailDialog','setContent'},{'SLGFengHuoTaiResourceCommonDialog','onCollectClick'},
 {'SLGFengHuoTaiResourceCommonDialog','SetData'},{'SLGFengHuoTaiTreasureDetailDialog','setContent'},
 {'SLGChooseHeroLogicMonster','startTrip'},{'SLGChooseHeroLogicMonster','startTrip2'},
 {'SLGChooseHeroLogicCollectResource','startTrip'},{'SLGChooseHeroLogicCollectResource','startTrip2'},
 {'SLGScoutDialog','onScoutClick'},{'SLGScoutDialog','setBaseInfo'},
 {'SLGMainController','parseTSLGScoutAreaRsp'},{'SLGMainModel','addScoutInfo'},
 {'SLGScoutDialog','Start'},{'SLGScoutDialog','setContent'},{'SLGScoutDialog','confirmScout'},
 {'SLGMainController','sendTSLGScoutAreaReq'},{'SLGSitdownPromptDialog','Start'},
 {'SLGScoutDialog','Awake'},{'SLGScoutDialog','updateSelf'},
 {'SLGChooseHeroScene','setContent'},{'SLGChooseHeroScene','getContent'},
 {'SLGChooseHeroLogicMonster','initialize'},{'SLGChooseHeroLogicMonster','getTargetID2'},
 {'SLGChooseHeroLogicMonster','updateHeroData'},{'SLGChooseHeroLogicCollectResource','updateHeroData'},
 {'SLGChooseHeroLogicCollectResource','startTrip2'},
 {'SLGChooseHeroLogicCollectResource','startResourceCollectTrip'},
 {'SLGFengHuoTaiResourceCommonDialog','canCollect'}}) do
 pcall(function() return CSLTypes[p[1]] end)
 local cls=package.loaded[p[1]]
 if type(cls)~='table' then local ok,c=pcall(require,p[1]);if ok then cls=c end end
 if cls then
  out[#out+1]='METHODTYPE '..table.concat(p,'.')..' '..type(cls.__instanceDict[p[2]])
  dump(table.concat(p,'.'),cls.__instanceDict[p[2]],1)
 end
end
for _,name in ipairs({'SLGChooseHeroLogicCollectResource','SLGScoutDialog','SLGChooseHeroLogicMonster'}) do
 local cls=package.loaded[name]
 if cls then for k,v in pairs(cls.__instanceDict) do if type(v)=='function' and
  (k:find('Trip') or k:find('Scout') or k:find('Speed') or k:find('Load') or k:find('Combat')) then
   dump(name..'.'..k,v,1)
  end end end
end
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local search=CSLTypes.DBSearcher.sharedInstance();local r=main:getTSLGGetBeaconTowerInfoRsp()
for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i);local c=search:searchTMapIntelStation_Event_Map(e[2])
 out[#out+1]='EVENT '..e[1][2]..' config='..e[2]..' kind='..c[2]..' state='..e[3]
 for k,v in pairs(c) do if type(v)=='number' or type(v)=='boolean' then out[#out+1]='CONFIG '..tostring(k)..'='..tostring(v) end end
end
return table.concat(out,'\n')
