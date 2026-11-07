-- Read timer units, follower eligibility and scout-distance configuration; no event operation is invoked.
local out={};local u=require('jit.util');local seen={}
local function dump(label,f,depth)
 if type(f)~='function' or seen[f] or not u.funcinfo(f).bytecodes then return end;seen[f]=true
 out[#out+1]='FUNCTION '..label
 for i=-1,-140,-1 do local v=u.funck(f,i);if v==nil then break end
  if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..i..' '..v end
 end
 for i=0,40 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 local nested={}
 for i=1,20 do local n,v=debug.getupvalue(f,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if type(v)=='function' then nested[#nested+1]={n,v} end
 end
 for pc=1,u.funcinfo(f).bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 if depth>0 then for _,p in ipairs(nested) do dump(label..'.UP.'..p[1],p[2],depth-1) end end
end
for _,p in ipairs({{'SLGFengHuoTaiSaveDialog','updateLeftSaveTime'},{'SLGChooseHeroScene','updateStartBtn'},
 {'SLGMainModel','getMaxSoldierForFight'},{'SLGMainController','parseTSLGGetBeaconTowerInfoRsp'},
 {'SLGMainController','parseTSLGBeaconTowerEventChangeNotify'}}) do
 dump(table.concat(p,'.'),package.loaded[p[1]].__instanceDict[p[2]],1)
end
local s=CSLTypes.DBSearcher.sharedInstance();local v=s:searchGlobalVariable(103010)
out[#out+1]='SCOUT_DISTANCE_PER_UNIT '..tostring(v and v[2])
return table.concat(out,'\n')
