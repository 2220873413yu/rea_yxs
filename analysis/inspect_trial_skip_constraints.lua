-- Read skip timing field declarations and static handlers; do not start or finish any combat.
local out={};local u=require('jit.util')
for _,name in ipairs({'TSLGInfo','TSLGPushArmy2ArmyResult','TDoPVPResultRsp'})do
 local d=package.loaded.RoomClientProtoDes[name] or package.loaded.ChatClientProtoDes[name]
 out[#out+1]='PROTO '..name
 for i,f in ipairs(d or {})do if type(f)=='table'then out[#out+1]='FIELD lua='..i..'; tag='..f.tag..'; name='..f.name end end
end
for _,name in ipairs({'SLGMainController','GameMsgMgr','HallMsgMgr','SLGGameScene','PVEModel'})do
 local c=package.loaded[name]
 if c then for k,v in pairs(c.__instanceDict or c)do if type(v)=='function' and u.funcinfo(v).bytecodes then
  for i=-1,-180,-1 do local s=u.funck(v,i);if s==nil then break end
   if s=='updateSkipTime' or s=='setTPushPVEResult'then out[#out+1]='LINK '..name..'.'..k..' '..s end
  end
 end end end
end
return table.concat(out,'\n')
