-- Trace task timestamps/status flags and condition descriptions without executing UI or senders.
local u=require('jit.util');local out={}
for _,p in ipairs({{'SLGDispatchListTaskItem','UpdateItem'},{'SLGDispatchController','parseTSLGDuHuFuGetHeroListRsp'}}) do
 local f=package.loaded[p[1]].__instanceDict[p[2]]
 out[#out+1]='FUNCTION '..table.concat(p,'.')
 for i=-1,-120,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
 for i=0,25 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGDispatchModel)
for id=1,8 do local ok,value=pcall(m.GetTaskConditionDesc,m,id)
 if ok and type(value)=='string' then out[#out+1]='CONDITION '..id..' '..CSLTypes.YXSUtils.GBK2UTF8(value) end
end
return table.concat(out,'\n')
