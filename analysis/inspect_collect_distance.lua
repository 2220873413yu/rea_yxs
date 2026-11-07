-- Inspect distance, view-query and collection eligibility functions. Never invoke senders.
local util=require('jit.util')
local out={}
for _,t in ipairs({{'SLGMapUtils','calMapP2PDistance'},{'SLGMapUtils','Trans2CubeCoPos'},
 {'SLGResourceCommonDialog','canCollect'},{'SLGResourceCommonDialog','CollectPopupChooseHeroPanel'},
 {'SLGMainController','sendTSLGViewInfoReq'},{'SLGMapObjectModel','GetMapInfo'},{'SLGMapResourceInfo','initUI'}}) do
 local cls=package.loaded[t[1]]
 local f=cls and cls.__instanceDict[t[2]]
 out[#out+1]='FUNCTION '..t[1]..'.'..t[2]..' '..type(f)
 if type(f)=='function' then
  for i=-1,-90,-1 do local v=util.funck(f,i);if v==nil then break end;if type(v)=='string' and not string.find(v,'[\128-\255]') then out[#out+1]='K '..(-i-1)..'='..v end end
  for i=0,40 do local v=util.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..'='..tostring(v) end
  for i=1,12 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v);if n=='T_ID' then out[#out+1]='VIEW_PROTOCOL '..tostring(v.E_SVR_MSG_ID_SLG_VIEW_INFO) end end
  for pc=1,util.funcinfo(f).bytecodes-1 do local bc=util.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
local search=CSLTypes.DBSearcher.sharedInstance()
for _,id in ipairs({30001,30002,31001}) do
 local config=search:searchTNewPlay_Resource_Map(id)
 out[#out+1]='CONFIG '..id..' '..type(config)
 if type(config)=='table' then
  for k,v in pairs(config) do
   if type(v)=='number' then out[#out+1]='CFG '..k..'='..v
   elseif type(v)=='string' then out[#out+1]='CFG '..k..'='..CSLTypes.YXSUtils.GBK2UTF8(v) end
  end
 end
end
return table.concat(out,'\n')
