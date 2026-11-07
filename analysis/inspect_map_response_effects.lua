-- Decode nested response-handler prototypes and coordinate helpers; never execute response handlers.
local util=require('jit.util');local out={}
local function dump(label,f,depth)
 local info=util.funcinfo(f)
 out[#out+1]='FUNCTION '..label..' params='..tostring(info.params)..' bytecodes='..tostring(info.bytecodes)
 for i=-1,-130,-1 do
  local v=util.funck(f,i);if v==nil then break end
  out[#out+1]='K '..(-i-1)..' '..type(v)..' '..tostring(v)
  if type(v)=='proto' and depth<2 then dump(label..'/proto'..(-i-1),v,depth+1) end
 end
 for i=0,35 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
 for pc=1,math.min(600,(info.bytecodes or 1)-1) do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
end
for _,pair in ipairs({{'SLGMainController','parseTSLGViewInfoRspCoroutine'},
 {'SLGMapUtils','displayToLogic'},{'SLGMapObjectModel','setScreenCenter'},
 {'InViewDataChunkCacheManager','UpdateDataChunkIndex'},{'InViewDataChunkCacheManager','MapKeyPos2ChunkKeyPos'}}) do
 local f=package.loaded[pair[1]].__instanceDict[pair[2]]
 if type(f)=='function' then dump(table.concat(pair,'.'),f,0) end
end
local manager=CSLTypes.ModelManager.sharedInstance()
local map=manager:getModel(CSLTypes.SLGMapObjectModel)
out[#out+1]='RANGE '..tostring(CSLTypes.SLGMapObjectModel.RANGE_X)..','..tostring(CSLTypes.SLGMapObjectModel.RANGE_Y)
local cache=map.mInViewDataChunkCacheManager
for k,v in pairs(cache.mtNewPlay_Map) do if type(v)=='number' then out[#out+1]='MAP_CONFIG '..k..'='..tostring(v) end end
for _,key in ipairs({'screenCenter','mViewDataCenterX','mViewDataCenterY'}) do
 local v=map[key];out[#out+1]='MAP_FIELD '..key..'='..tostring(v)
 if type(v)=='table' then for k,x in pairs(v) do if type(x)=='number' then out[#out+1]='CENTER '..k..'='..x end end end
end
return table.concat(out,'\n')
