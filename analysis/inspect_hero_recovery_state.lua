-- Read cached hero state and configuration only. No request or acceleration function is called.
local out={}
local util=require("jit.util")
local names={
 {"UpgradeAccelerationNewDialog","canUseAccItemFilter"},
 {"UpgradeAccelerationNewDialog","useButtonCallback"},
 {"HeroPalaceDialog","initHeroList"},
 {"HeroPalaceDialog","heroPalaceListSort"},
 {"HeroPalaceItem","initHeroStatus"}
}
for _,t in ipairs(names) do
 local fn=package.loaded[t[1]].__instanceDict[t[2]]
 out[#out+1]="FUNCTION "..t[1].."."..t[2]
 for i=0,55 do
  local v=util.funck(fn,i)
  if v==nil then break end
  out[#out+1]="NUM "..i.."="..tostring(v)
 end
 if t[2]=="useButtonCallback" or t[2]=="initHeroList" then
  local info=util.funcinfo(fn)
  for pc=1,info.bytecodes-1 do
   local bc=util.funcbc(fn,pc)
   out[#out+1]=string.format("BC %d OP=%d A=%d B=%d C=%d D=%d",pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
  end
 end
end
local mm=CSLTypes.ModelManager.sharedInstance()
local model=mm:getModel(CSLTypes.SLGBuildingsModel)
local rsp=model:getTSLGGetHeroPubRsp()
out[#out+1]="HERO_RSP type="..type(rsp)
if type(rsp)=="table" then
 for i=1,12 do
  local v=rawget(rsp,i)
  if v~=nil then
   local detail=type(v)=="number" and tostring(v) or ""
   if type(v)=="table" and v.get_Count then detail="count="..v:get_Count() end
   out[#out+1]="RSP "..i..":"..type(v)..":"..detail
  end
 end
end
local items=mm:getModel(CSLTypes.ItemsModel)
for _,id in ipairs({70251,70261,70262,70263,70264,70271,70272,70273,70274}) do
 local ok,name=pcall(function() return items:searchItemsName(id) end)
 local count=items:getItemCount(id)
 out[#out+1]="ITEM "..id.." count="..tostring(count).." name="..(ok and tostring(name) or "unavailable")
end
return table.concat(out,"\n")
