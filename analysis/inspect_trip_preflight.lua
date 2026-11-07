-- Read only active observer-owned trip data; never alter selection or invoke a sender.
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local out={}
local seen={}
local count=0
local function inspect(node,depth)
 if type(node)~='table' or seen[node] or depth>8 or count>8000 then return end
 seen[node]=true;count=count+1
 local content=rawget(node,'_content')
 local choices=rawget(node,'_chooseData')
 if type(content)=='table' and type(choices)=='table' then
  out[#out+1]='FOUND_SELECTION'
  for i=1,14 do local v=rawget(content,i);if type(v)=='number' or type(v)=='boolean' then out[#out+1]='CONTENT '..i..'='..tostring(v) else out[#out+1]='CONTENT '..i..' '..type(v) end end
  local logic=rawget(node,'_logic')
  out[#out+1]='LOGIC '..(type(logic)=='table' and tostring(logic.class and logic.class.name) or type(logic))
  out[#out+1]='SELECTED '..type(rawget(node,'_currentSelectedHero'))
  if choices.get_Count then
   out[#out+1]='CHOICES '..choices:get_Count()
   for i=0,choices:get_Count()-1 do
    local entry=choices:get_Item(i)
    local hero=entry.availHero
    if type(hero)=='table' and type(hero[1])=='table' and type(hero[1][1])=='table' and hero[1][1][3]==303 then
     out[#out+1]='XISHI_FOUND_INDEX '..i
     for k,v in pairs(hero) do if type(k)=='number' then
      if type(v)=='number' then out[#out+1]='HERO '..k..'='..tostring(v)
      elseif type(v)=='table' then for j=1,12 do local x=rawget(v,j);if type(x)=='number' then out[#out+1]='HERO '..k..'.'..j..'='..tostring(x) end end end
     end end
     out[#out+1]='ACTION_STATE '..tostring(entry.actionState)..' SELECT_STATE '..tostring(entry.selectState)
    end
   end
  end
 end
 for k,v in pairs(node) do
  if k~='__instanceDict' and k~='__c' and k~='class' and k~='super' then inspect(v,depth+1) end
 end
end
inspect(main.observers,0)
inspect(main.tmpObservers,0)
out[#out+1]='VISITED '..count
return table.concat(out,'\n')
