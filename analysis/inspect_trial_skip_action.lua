-- Inspect native login/packet assembly functions; no callbacks or senders are executed.
local out={};local u=require('jit.util');local seen={}
local function dump(label,fn,depth)
 if type(fn)~='function' or seen[fn] then return end;seen[fn]=true
 local info=u.funcinfo(fn);if not info.bytecodes then return end
 out[#out+1]='FUNCTION '..label..' params='..info.params
 for i=-1,-160,-1 do local v=u.funck(fn,i);if v==nil then break end
  if type(v)=='string' and (v=='' or v:match('^[%a_][%w_%.]*$')) then out[#out+1]='K '..i..' '..v end
 end
 for i=0,30 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 local nested={}
 for i=1,30 do local name,value=debug.getupvalue(fn,i);if not name then break end
  out[#out+1]='UP '..i..' '..name..' '..type(value)
  if type(value)=='function' then nested[#nested+1]={name,value} end
 end
 for pc=1,info.bytecodes-1 do local bc=u.funcbc(fn,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 if depth>0 then for _,v in ipairs(nested) do dump(label..'.UP.'..v[1],v[2],depth-1) end end
end

for _,pair in ipairs({{'SLGGameScene','initRoundTimeoutBtn'},{'SLGGameScene','onRoundTimeoutBtnClick'},{'SLGGameScene','Start'},{'GameMsgMgr','handlePVPResultMessage'},{'GameMsgMgr','createPVPResultWithBanlance'},{'SLGMainController','parseTSLGTimeoutSkipRsp'},{'SLGMainController','sendTSLGTimeoutSkipReq'}})do
 local cls=package.loaded[pair[1]]
 if cls then dump(table.concat(pair,'.'),(cls.__instanceDict or cls)[pair[2]],1)end
end
return table.concat(out,'\n')
