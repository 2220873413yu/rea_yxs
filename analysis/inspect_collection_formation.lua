-- Inspect native formation declarations and hero configuration without game actions.
local util=require('jit.util')
local out={}
for _,name in ipairs({'SLGChooseHeroScene','SLGChosenSoldier','SLGChooseHeroLogicCollectResource','SLGChooseHeroItem'}) do
 local methods=package.loaded[name] and package.loaded[name].__instanceDict
 if methods then
  for k,f in pairs(methods) do
   if type(k)=='string' and type(f)=='function' and
    (k:find('Soldier') or k:find('Trip') or k:find('Formation') or k:find('ActionState')) then
    local constants={}
    for i=-1,-90,-1 do
     local v=util.funck(f,i);if v==nil then break end
     if type(v)=='string' then constants[#constants+1]=v end
    end
    out[#out+1]=name..'.'..k..' '..table.concat(constants,'|')
   end
  end
 end
end
local search=CSLTypes.DBSearcher.sharedInstance()
for _,entry in ipairs({{'SLGChooseHeroScene','updateSoldier'},{'SLGChooseHeroScene','createChosenSoldier'}}) do
 local f=package.loaded[entry[1]].__instanceDict[entry[2]]
 out[#out+1]='FUNCTION '..entry[2]
 for i=-1,-90,-1 do
  local v=util.funck(f,i);if v==nil then break end
  if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..v end
 end
 for i=1,15 do local n,v=debug.getupvalue(f,i);if not n then break end;out[#out+1]='UP '..i..' '..n..' '..type(v) end
 for pc=1,util.funcinfo(f).bytecodes-1 do
  local bc=util.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
end
for _,id in ipairs({242,305,303}) do
 local config=search:searchHeroInfoByStarAndGroup(1,id)
 local fields={}
 for k,v in pairs(config) do if type(k)=='number' and type(v)=='number' then fields[#fields+1]=k..'='..v end end
 out[#out+1]='CONFIG '..id..' '..table.concat(fields,',')
end
return table.concat(out,'\n')
