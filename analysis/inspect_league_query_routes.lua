-- Inspect own-building query routes, league-mine enum and cache mappings without dispatching anything.
local out={};local u=require('jit.util')
for _,p in ipairs({{'SLGLeagueController','sendTSLGLeagueGetAllBuildReq'},{'SLGLeagueController','parseTSLGLeagueGetAllBuildRsp'},
 {'SLGLeagueController','parseTSLGLeagueGetResourceRsp'},{'SLGLeagueModel','updateTSLGLeagueGetResourceRsp'},
 {'SLGMapObjectModel','getLeagueResourceData'},{'SLGMapObjectModel','getTLeagueResourceData'}}) do
 local f=package.loaded[p[1]].__instanceDict[p[2]]
 if type(f)=='function' and u.funcinfo(f).bytecodes then
  out[#out+1]='FUNCTION '..table.concat(p,'.')..' params='..u.funcinfo(f).params
  for i=-1,-80,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end end
  for i=1,10 do local n,v=debug.getupvalue(f,i);if not n then break end
   if n=='T_ID' then for a,b in pairs(v) do if tostring(a):find('LEAGUE_GET_ALL_BUILD') then out[#out+1]='PROTOCOL '..a..' '..b end end
   elseif type(v)=='table' then
    for a,b in pairs(v) do if tostring(a):find('LEAGUE_COLLECT') or tostring(a):find('WORKSHOP') then out[#out+1]='ENUM '..a..' '..tostring(b) end end
   end
  end
  for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc);out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536) end
 end
end
local f=package.loaded.SLGLeagueResCommonDialog.__instanceDict.Start
local _,click=debug.getupvalue(f,4)
for i=1,5 do local n,v=debug.getupvalue(click,i);if not n then break end;if type(v)=='table' then for a,b in pairs(v) do if tostring(a):find('LEAGUE_COLLECT') or tostring(a):find('WORKSHOP') then out[#out+1]='ENUM '..a..' '..b end end end end
return table.concat(out,'\n')
