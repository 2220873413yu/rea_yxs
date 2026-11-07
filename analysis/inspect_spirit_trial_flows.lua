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

for _,name in ipairs({'SLGTowerMainScene','SLGTowerChooseHeroScene','SLGTowerModel','SLGTowerController','SLGTowerHeroItem','SLGTowerStoreyReward'}) do
 local cls=package.loaded[name]
 local d=cls and (cls.__instanceDict or cls)
 if d then for k,v in pairs(d) do
  if type(v)=='function' and (k:find('TSLG') or k:find('onStart') or k:find('Hero') or k:find('MainData') or k:find('Soldier') or k:find('Skip') or k=='updateSelf' or k=='updateStartBtnState' or k=='onSignOutBtnClick' or k=='onFetchRewardClick') then dump(name..'.'..k,v,2) end
 end end
end
local proto=package.loaded.ChatClientProtoDes or {}
for name,fields in pairs(proto) do if tostring(name):find('QCT') and type(fields)=='table' then
 out[#out+1]='PROTO '..name
 for _,f in ipairs(fields) do if type(f)=='table' then out[#out+1]='FIELD '..tostring(f.tag)..' '..tostring(f.name)..' '..tostring(f.struct_path and table.concat(f.struct_path,'.') or '') end end
end end
return table.concat(out,'\n')
