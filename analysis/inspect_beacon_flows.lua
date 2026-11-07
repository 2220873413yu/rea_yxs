-- Trace native event completion/queue/time decisions without invoking UI callbacks or any sender.
local out={};local u=require('jit.util');local seen={}
local function dump(label,f,depth)
 if type(f)~='function' or seen[f] then return end;seen[f]=true
 local info=u.funcinfo(f);if not info.bytecodes then return end
 out[#out+1]='FUNCTION '..label..' params='..info.params
 for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end
  if type(v)=='string' and not v:find('[\128-\255]') then out[#out+1]='K '..i..' '..v end
 end
 for i=0,35 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 local nested={}
 for i=1,25 do local n,v=debug.getupvalue(f,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if type(v)=='function' then nested[#nested+1]={n,v}
  elseif type(v)=='table' and n=='E_SLG_ARMY_AIM_TYPE' then for k,x in pairs(v) do
   if type(k)=='string' and k:find('BEACON') then out[#out+1]='AIM '..k..'='..tostring(x) end
  end end
 end
 for pc=1,info.bytecodes-1 do local bc=u.funcbc(f,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end
 if depth>0 then for _,p in ipairs(nested) do dump(label..'.UP.'..p[1],p[2],depth-1) end end
end
for _,p in ipairs({{'SLGFengHuoTaiSaveDialog','onSaveClick'},
 {'SLGFengHuoTaiResourceCommonDialog','onCollectClick'},
 {'SLGFengHuoTaiTreasureDetailDialog','onScoutClick'},
 {'SLGMainModel','getMaxFengHuoTaiArmyCount'},{'SLGMainModel','checkMaxFengHuoTaiArmyCount'},
 {'SLGMainModel','setTSLGGetBeaconTowerInfoRsp'},{'SLGMainModel','updateBeaconTower'},
 {'FengHuoTaiDialog','updateLeftTime'},{'FengHuoTaiDialogEventItem','setEventState'},
 {'FengHuoTaiDialogEventItem','onBtn'},{'SLGFengHuoTaiSaveDialog','canSave'}}) do
 pcall(function() return CSLTypes[p[1]] end)
 dump(table.concat(p,'.'),package.loaded[p[1]].__instanceDict[p[2]],1)
end
return table.concat(out,'\n')
