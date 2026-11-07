-- Private research API: only own league building/detail and available-hero queries; no spending method exists.
local api=assert(REA_LEAGUE_READONLY);local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel);local league=manager:getModel(CSLTypes.SLGLeagueModel)
local map=manager:getModel(CSLTypes.SLGMapObjectModel);local search=CSLTypes.DBSearcher.sharedInstance()
local ctrl=CSLTypes.SLGLeagueController.getInstance();local scene=CSLTypes.SceneNotifier.getInstance()
local bound=main.mTSLGLoginMapRsp;local beforeBuild,beforeDetail,target,available
local rawScene,rawState=rawget(scene,'notifyUpdateData'),rawget(main,'notifyStateChange')
local originalScene,originalState=scene.notifyUpdateData,main.notifyStateChange
local sw,tw;local pending,suppress=false,false
sw=function(self,id,payload,...)
 if pending and id==1060 and type(payload)=='table' and payload[2]==target and payload[3]==12 then
  available=payload;pending=false;suppress=true;return
 end
 return originalScene(self,id,payload,...)
end
tw=function(self,id,...)
 if suppress and id==-9991 then suppress=false;return end
 return originalState(self,id,...)
end
rawset(scene,'notifyUpdateData',sw);rawset(main,'notifyStateChange',tw)

-- Refresh the current own league's building list; no coordinates or foreign league ID can be supplied.
function api.league_build_query()
 assert(main.mTSLGLoginMapRsp==bound,'World changed')
 beforeBuild=league:getTSLGLeagueGetAllBuildRsp();ctrl:sendTSLGLeagueGetAllBuildReq();return 'own_buildings_queried'
end

-- Summarize fresh building containers and one already-loaded owned mine, excluding player identities.
function api.league_build_result()
 local r=league:getTSLGLeagueGetAllBuildRsp()
 if not r or r==beforeBuild then return '{"ready":false}' end
 assert(r[1]==0,'League building query failed')
 local fields={};for k,v in pairs(r) do if type(k)=='number' and type(v)=='table' and v.get_Count then fields['field_'..k]=v:get_Count() end end
 local chunks=map.mInViewDataChunkCacheManager:getAllViewData();local own=main:getMyLeagueId();local point
 --11114 contains the complete owned mine even when its map chunk has been evicted.
 if type(r[5])=='table' and type(r[5][2])=='number' and r[5][2]>0 and r[5][9]==own then point=r[5] end
 for i=0,chunks:get_Count()-1 do local c=chunks:get_Item(i).mViewDataCache
  if c:ContainsKey(5002) then local ps=c:get_Item(5002);local ks=ps:GetDictKeys()
   for j=0,ks:get_Count()-1 do local p=ps:get_Item(ks:get_Item(j));if not point and p[9]==own then point=p end end
  end
 end
 local p={found=point~=nil}
 if point then local shown=CSLTypes.SLGMapUtils.logicToDisplay(point[1]);p.target_id=point[2];p.config_id=point[3];p.x=shown[1];p.y=shown[2] end
 return '{"ready":true,"building_counts":'..api.encode_flat_state(fields)..',"mine":'..api.encode_flat_state(p)..'}'
end

-- Query details and native aim12 hero metrics only for a target proven to belong to our league cache.
function api.league_mine_query(id)
 assert(main.mTSLGLoginMapRsp==bound,'World changed')
 local building=league:getTSLGLeagueGetAllBuildRsp()
 local own=building and building~=beforeBuild and building[1]==0 and type(building[5])=='table' and
  building[5][2]==id and building[5][9]==main:getMyLeagueId()
 local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
 for i=0,chunks:get_Count()-1 do local c=chunks:get_Item(i).mViewDataCache
  if c:ContainsKey(5002) then local ps=c:get_Item(5002);local ks=ps:GetDictKeys()
   for j=0,ks:get_Count()-1 do local p=ps:get_Item(ks:get_Item(j));if p[2]==id and p[9]==main:getMyLeagueId() then own=true end end
  end
 end
 assert(own,'Mine not proven to belong to our league')
 target=id;available=nil;pending=true;beforeDetail=league:getTSLGLeagueGetResourceRsp()
 ctrl:sendTSLGLeagueGetResourceReq(id)
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq(id,12,0,0)
 return 'own_mine_reads_sent'
end

-- Export only relevant resource/config fields, per-stage timestamps and owned hero metrics.
function api.league_mine_result()
 local r=league:getTSLGLeagueGetResourceRsp()
 if not r or r==beforeDetail or not available then return '{"ready":false}' end
 assert(r[1]==0 and available[1]==0 and r[2][2]==target,'Mine read response mismatch')
 local p=r[2];local config=assert(search:searchTLeagueResource(p[3]));local shown=CSLTypes.SLGMapUtils.logicToDisplay(p[1])
 local info={target_id=target,config_id=p[3],x=shown[1],y=shown[2],stock=p[5],own=p[9]==main:getMyLeagueId(),
  map_collect_records=p[6]:get_Count(),detail_armies=r[3]:get_Count(),visible=manager:getModel(CSLTypes.SLGWarFogModel):isCellVisible(p[1][1],p[1][2],p[1][3])}
 local cf={};for k,v in pairs(config) do
  if type(k)=='number' and type(v)=='number' then cf['field_'..k]=v
  elseif type(k)=='number' and type(v)=='string' and #v<200 then cf['field_'..k]=CSLTypes.YXSUtils.GBK2UTF8(v) end
 end
 local members={}
 for i=0,r[3]:get_Count()-1 do local a=r[3]:get_Item(i)
  members[#members+1]=api.encode_flat_state({army_id=a[1],state=a[4],aim=a[5],target_id=a[6],stage_end=a[11]})
 end
 local rows={}
 for i=0,available[4]:get_Count()-1 do local h=available[4]:get_Item(i);local id=h[1][1][3];local s=api.read_hero_state(id)
  rows[#rows+1]=api.encode_flat_state({hero_id=id,name=s.name,speed=h[6],load=h[5],travel_seconds=h[3],busy=s.busy,
   hero_state=s.hero_state,cooldown_ms=s.remaining_ms,action=package.loaded.SLGChooseHeroItem.__instanceDict.getActionState(h)})
 end
 return '{"ready":true,"mine":'..api.encode_flat_state(info)..',"config":'..api.encode_flat_state(cf)..
  ',"armies":['..table.concat(members,',')..'],"heroes":['..table.concat(rows,',')..']}'
end

-- Restore callbacks to their exact original values; no observer or UI object survives this probe.
function api.league_close()
 pending=false;suppress=false
 if rawget(scene,'notifyUpdateData')==sw then rawset(scene,'notifyUpdateData',rawScene) end
 if rawget(main,'notifyStateChange')==tw then rawset(main,'notifyStateChange',rawState) end
 return 'closed'
end
return 'league_readonly_ready'
