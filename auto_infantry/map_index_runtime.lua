-- Manual map-player discovery. Installation/context reads never query, dispatch or change affiliations.
local api={};REA_MAP_INDEX=api
local mm=CSLTypes.ModelManager.sharedInstance();local account=mm:getModel(CSLTypes.MainModel)
local main=mm:getModel(CSLTypes.SLGMainModel);local map=mm:getModel(CSLTypes.SLGMapObjectModel)
local login=account.mTLoginRsp;local world=main.mTSLGLoginMapRsp;local scope=main:getTMapGameDataID()
local zone,mapId=scope[2],scope[1]

-- Preserve exact integer IDs on LuaJIT rather than its rounded default tostring representation.
local function json(v)
 local t=type(v)
 if t=='string'then return '"'..v:gsub('[%z\1-\31\\"]',function(c)return string.format('\\u%04x',c:byte())end)..'"'end
 if t=='number'then return string.format(v==math.floor(v)and'%.0f'or'%.17g',v)end
 if t=='boolean'then return tostring(v)end
 if t~='table'then return 'null'end
 local out={};if next(v)==nil or v[1]~=nil then for _,x in ipairs(v)do out[#out+1]=json(x)end;return '['..table.concat(out,',')..']'end
 for k,x in pairs(v)do out[#out+1]=json(k)..':'..json(x)end;return '{'..table.concat(out,',')..'}'
end
local function text(v)return v and CSLTypes.YXSUtils.GBK2UTF8(v)or''end
local function count(v)return v and v:get_Count()or 0 end

-- A map/account replacement invalidates observations and saved-user lookups before further requests.
local function guard()
 local current=main:getTMapGameDataID()
 assert(account.mTLoginRsp==login and main.mTSLGLoginMapRsp==world and main.mIsMapLoaded and
  current[1]==mapId and current[2]==zone,'地图或账号已改变，搜索已停止，请重新连接助手')
 assert(main:getSignedMapTypeID()==1,'当前只支持已验证的西游幻境地图')
end

-- Read actual map dimensions/scope without requesting a league list, region or player profile.
function api.context()
 guard();local cfg=map.mInViewDataChunkCacheManager.mtNewPlay_Map
 return json({map_id=mapId,zone_id=zone,width=cfg[10],height=cfg[11]})
end

-- Plan one overlapping24/18 area query per40x30 tile; map dimensions come from the native configuration.
function api.plan()
 guard();local cfg=map.mInViewDataChunkCacheManager.mtNewPlay_Map;local width,height=cfg[10],cfg[11]
 assert(type(width)=='number'and type(height)=='number'and width>0 and height>0 and width<=2000 and height<=2000,'地图尺寸未确认，未搜索')
 local rows={};local home=map:getMyMainCityCoordinates()
 for x=0,width-1,40 do for y=0,height-1,30 do
  local cx,cy=math.min(x+20,width-1),math.min(y+15,height-1)
  rows[#rows+1]={x=cx,y=cy,distance=CSLTypes.SLGMapUtils.calMapP2PDistance(home,{cx,cy,0})}
 end end
 table.sort(rows,function(a,b)if a.distance~=b.distance then return a.distance<b.distance end;if a.x~=b.x then return a.x<b.x end;return a.y<b.y end)
 return json({regions=rows})
end

-- Read only already loaded cities; duplicate occupied cells collapse to one native player identity.
function api.cached()
 -- Object type1 is the verified main-city cache type in the supported4.31.0 Xiyou client.
 guard();local rows,seen={},{};local kind=1
 local function add(city)
  if not city or not city[3]or not city[3][1]then return end
  kind=kind or city[1][3];local p=city[3];local u=p[1]
  if not((u[1]and u[1]~=0)or(u[2]and u[2]~=''))then return end
  local key=string.format('%.0f',u[1]or 0)..'|'..(u[2]or'')..'|'..tostring(u[3])..'|'..tostring(u[4])
  if seen[key]then return end;seen[key]=true
  local pos=CSLTypes.SLGMapUtils.logicToDisplay(city[1][1])
  rows[#rows+1]={identity={u[1]or 0,u[2]or'',u[3]or 0,u[4]or 0},name=text(p[2]),league_id=p[5]or 0,
   league_name=text(p[6]),x=pos[1],y=pos[2],observed_ms=CSLTypes.SLGMainModel.GetMapTimeNow()}
 end
 local function addList(list)for i=0,count(list)-1 do add(list:get_Item(i))end end
 -- Prefer the current region cache over older login lists when an identity changed league or moved.
 local region=main.mTSLGLoginMapRsp[2]
 if region and count(region[4])>0 then kind=region[4]:get_Item(0)[1][3]end
 local allies=main.mTSLGLoginMapRsp[7];if not kind and count(allies)>0 then kind=allies:get_Item(0)[1][3]end
 local chunks=map.mInViewDataChunkCacheManager:getAllViewData()
 if kind then for i=0,count(chunks)-1 do local cache=chunks:get_Item(i).mViewDataCache
  if cache:ContainsKey(kind)then local cities=cache:get_Item(kind);local keys=cities:GetDictKeys()
   for j=0,count(keys)-1 do add(cities:get_Item(keys:get_Item(j)))end
  end
 end end
 if region then addList(region[4])end
 addList(allies);addList(main.mTSLGLoginMapRsp[15])
 return json({players=rows})
end

-- Reuse the established exact-region response guard before accepting cached city observations.
function api.region_read(seq,x,y)
 guard();REA_AUTO_INFANTRY.hunt_region_assert(seq,x,y);return api.cached()
end

-- Saved map identities are used only after a click; this operation never scans or searches other players.
function api.profile(identity)
 guard();REA_PLAYER_QUERY.bind_member(identity);return REA_PLAYER_QUERY.profile(0)
end
function api.profile_snapshot()
 guard();return REA_PLAYER_QUERY.snapshot(0)
end
return 'map_index_api_installed'
