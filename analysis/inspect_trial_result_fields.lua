-- Read protocol descriptors and function names related to the actual SLG result only.
local out={};local u=require('jit.util')
for _,name in ipairs({'TPushPVPResult','TSLGSitDownRsp','TSLGPushPVEInfo','TSLGPVEResult'})do
 local d=package.loaded.ChatClientProtoDes[name] or package.loaded.RoomClientProtoDes[name]
 out[#out+1]='PROTO '..name
 for i,f in ipairs(d or {})do if type(f)=='table'then out[#out+1]='FIELD lua='..i..'; tag='..tostring(f.tag)..'; name='..tostring(f.name)..'; type='..tostring(f.struct_path and table.concat(f.struct_path,'.') or '')end end
end
for _,name in ipairs({'SLGMainModel','GameModel','GameMsgMgr'})do
 local cls=package.loaded[name];local d=cls and (cls.__instanceDict or cls)
 if d then for k,v in pairs(d)do if type(k)=='string' and type(v)=='function'then
  if k:find('Result') or k:find('SkipTime') or k:find('SLGTower')then out[#out+1]='METHOD '..name..'.'..k end
 end end end
end
return table.concat(out,'\n')
