-- Inspect native selection predicates and recursive helpers; never select heroes or send a dispatch.
local u=require('jit.util');local out={};local seen={}
local ok,bc=pcall(require,'jit.bc')
out[#out+1]='JIT_BC '..tostring(ok)
local function dump(label,f,depth)
 if type(f)~='function' or seen[f] or not u.funcinfo(f).bytecodes then return end
 seen[f]=true
 local info=u.funcinfo(f);out[#out+1]='FUNCTION '..label..' params='..info.params..' bytecodes='..info.bytecodes
 for i=-1,-150,-1 do local v=u.funck(f,i);if v==nil then break end;if type(v)=='string' then out[#out+1]='K '..i..' '..v end end
 for i=0,30 do local v=u.funck(f,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 local ups={}
 for i=1,25 do local n,v=debug.getupvalue(f,i);if not n then break end
  out[#out+1]='UP '..i..' '..n..' '..type(v)
  if type(v)=='function' then ups[#ups+1]={name=n,value=v} end
 end
 if ok then
  local writer={write=function(self,text) out[#out+1]=text end,flush=function() end}
  bc.dump(f,writer)
 else
  for pc=1,info.bytecodes-1 do local ins=u.funcbc(f,pc)
   out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,ins%256,math.floor(ins/256)%256,math.floor(ins/16777216)%256,math.floor(ins/65536)%256,math.floor(ins/65536)%65536)
  end
 end
 if depth>0 then for _,v in ipairs(ups) do dump(label..'.UP.'..v.name,v.value,depth-1) end end
end
local d=package.loaded.SLGDispatchModel.__instanceDict
for _,name in ipairs({'AutoSelectHeros','GetHeroCanDispatch','GetHeroSatisfyNum','GetHerosByTypeIsZero',
 'GetSelectHerosByType','SortHerosByConsitionType','RefreshTaskConditonInfos','RefreshHeroInfoData',
 'isCanDispatchHeros','isHeroSatisfyAnyCondition','pruneHerosByTaskCondition','SortHeroList',
 '_SortHeroList_b__35_0','availHeroToHeroInfo'}) do dump('SLGDispatchModel.'..name,d[name],3) end
dump('ChooseHeroItem.updateActionState',package.loaded.SLGDispatchChooseHeroItem.__instanceDict.updateActionState,1)
dump('DispatchChooseHeroScene.updateArmyInfo',package.loaded.SLGDispatchChooseHeroScene.__instanceDict.updateArmyInfo,1)
dump('DispatchChooseHeroScene.AutoDispatch',package.loaded.SLGDispatchChooseHeroScene.__instanceDict.AutoDispatch,1)
dump('parseHeroList',package.loaded.SLGDispatchController.__instanceDict.parseTSLGDuHuFuGetHeroListRsp,1)
return table.concat(out,'\n')
