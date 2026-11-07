-- Read cache coverage and native coordinate conversion for the discussed tile; no server request.
local map=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMapObjectModel)
local cache=map.mInViewDataChunkCacheManager
local util=CSLTypes.SLGMapUtils
local out={}
for _,p in ipairs({{96,89},{96,88},{95,86}}) do
 local shown=util.logicToDisplay({[1]=p[1],[2]=p[2]})
 local key=util.createKey(p[1],p[2])
 local ck=cache:MapKeyPos2ChunkKeyPos(key)
 local known=cache.mDataChunkDic:ContainsKey(ck)
 local ok,kind=pcall(map.getObjectType,map,p[1],p[2])
 out[#out+1]='display='..shown[1]..','..shown[2]..' chunk_loaded='..tostring(known)..' type_known='..tostring(ok)..' type='..tostring(kind)
end
return table.concat(out,'\n')
