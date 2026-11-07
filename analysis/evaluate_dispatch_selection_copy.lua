-- Calculate only on a new isolated model. Never change the actual selection or call a dispatch sender.
local mm=CSLTypes.ModelManager.sharedInstance();local model=mm:getModel(CSLTypes.SLGDispatchModel)
local main=mm:getModel(CSLTypes.SLGMainModel);local search=CSLTypes.DBSearcher.sharedInstance()
local originalCount=model.SelectionHeroInfoDic:get_Count()
local r=assert(model.selectHeroList);assert(r[1]==0,'No successful candidate read')
local task
for i=0,model.taskInfo:get_Count()-1 do local t=model.taskInfo:get_Item(i);if t[1]==r[2] then task=t end end
assert(task and task[3]==0,'Task changed or already dispatched')
local c=assert(search:GetSLGDuHuFuEvent(task[2]))
local clone=CSLNew(CSLTypes.SLGDispatchModel)
clone.selectHeroList=r
clone.TaskNeedPerson=c[8]
clone.heroEquipInfos=model.heroEquipInfos
clone.heroSuitAddDatas=model.heroSuitAddDatas
-- Attribute calculation reads the native owned-hero/equipment caches into this model's private dictionary.
local seen={};local rawHeroes={};local keys=r[3]:GetDictKeys()
for i=0,keys:get_Count()-1 do local list=r[3]:get_Item(keys:get_Item(i))
 for j=0,list:get_Count()-1 do local h=list:get_Item(j);local id=h[1][4]
  if not seen[id] then seen[id]=true;rawHeroes[#rawHeroes+1]=h
   package.loaded.SLGDispatchModel.__instanceDict.RefreshHeroInfoData(clone,h)
  end
 end
end
local function numbers(s)
 local a={};for v in s:gmatch('[^|]+') do a[#a+1]=assert(tonumber(v)) end;return a
end
local types,values,counts=numbers(c[6]),numbers(c[7]),numbers(c[12])
for i=1,4 do local t=clone['t'..i]
 t.type=types[i] or 0;t.typeValue=values[i] or 0;t.personNeedNum=counts[i] or 0;t.personActualNum=0
end
local methods=package.loaded.SLGDispatchModel.__instanceDict
local out={'private_model_only=true','task_id='..r[2],'required_heroes='..clone.TaskNeedPerson,
 'attribute_cards='..clone.heroInfoDatas:get_Count(),'candidate_unique='..#rawHeroes}
local busy=0;local cooling=0;local now=CSLTypes.RefreshTimer.getServerNatureTimeNow()*1000
local armyByGroup={}
if main._myActionState and main._myActionState[1]==0 then
 for _,index in ipairs({2,3}) do local list=main._myActionState[index]
  for i=0,list:get_Count()-1 do local a=list:get_Item(i);armyByGroup[a[15][1]]=a end
 end
end
for _,h in ipairs(rawHeroes) do local card,group=h[1][4],h[1][3];local conf=search:searchHeroInfo(card)
 if h[2]~=0 then
  busy=busy+1;local a=armyByGroup[group]
  out[#out+1]=string.format('busy|card=%d|group=%d|name=%s|status=%d|army_aim=%s|army_phase=%s',
   card,group,CSLTypes.YXSUtils.GBK2UTF8(conf[7]),h[2],a and tostring(a[5]) or 'none',a and tostring(a[4]) or 'none')
 elseif h[3]>now then cooling=cooling+1 end
end
out[#out+1]='busy_count='..busy;out[#out+1]='cooling_count='..cooling
methods.AutoSelectHeros(clone)
local fits=methods.isCanDispatchHeros(clone)
out[#out+1]='native_conditions_satisfied='..tostring(fits)
local selected=clone.SelectionHeroInfoDic:GetDictKeys();local selectedCount=0
for i=0,selected:get_Count()-1 do local h=clone.SelectionHeroInfoDic:get_Item(selected:get_Item(i))
 if h then selectedCount=selectedCount+1
  local id=h[1][4];local conf=search:searchHeroInfo(id);local a=clone.heroInfoDatas:get_Item(id)
  assert(h[2]==0 and h[3]<=now,'Native planner included busy/cooling hero')
  out[#out+1]=string.format('selected_copy|card=%d|group=%d|name=%s|stars=%d|level=%d|camp=%d',
   id,h[1][3],CSLTypes.YXSUtils.GBK2UTF8(conf[7]),a.atr1,a.atr2,a.atr3)
 end
end
for i=1,4 do local t=clone['t'..i]
 if t.type~=0 then out[#out+1]=string.format('condition|type=%d|threshold=%d|required=%d|actual=%d',t.type,t.typeValue,t.personNeedNum,t.personActualNum) end
end
assert(model.SelectionHeroInfoDic:get_Count()==originalCount,'Real selection unexpectedly changed')
out[#out+1]='real_selection_count_unchanged='..originalCount
out[#out+1]='copy_selection_count='..selectedCount
return table.concat(out,'\n')
