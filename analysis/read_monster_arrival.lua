-- Read only this experiment's current army and native enter/skip button arguments.
local out={};local util=require('jit.util')
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local a=main:getMyArmyInfoByHeroGroupId(427)
if a then
 for _,i in ipairs({1,4,5,6,7,10,11,12}) do if type(a[i])=='number' then out[#out+1]='ARMY '..i..'='..a[i] end end
else out[#out+1]='ARMY absent' end
out[#out+1]='MONTHCARD '..tostring(main:isSLGMonthCardEnabled())
local start=package.loaded.SLGSitdownPromptDialog.__instanceDict.Start
for idx=1,3 do
 local n,f=debug.getupvalue(start,idx)
 if type(f)=='function' then
  out[#out+1]='FUNCTION '..n..' params='..util.funcinfo(f).params
  for i=-1,-100,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..CSLTypes.YXSUtils.GBK2UTF8(v) end end
  for i=0,10 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
  for i=1,10 do local un,uv=debug.getupvalue(f,i);if not un then break end;out[#out+1]='UP '..i..' '..un..' '..type(uv) end
  for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
return table.concat(out,'\n')
