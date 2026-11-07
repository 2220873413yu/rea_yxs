-- Inspect co-op checkpoint/room routing declarations only; never join, match, invite or start a game.
local u=require('jit.util');local out={}
for _,name in ipairs({'PVEController','PVEModel','PVEChooseHeroScene','PVEMapScene','PVEMapCity',
 'PVEHeroSelectBossDialog','MatchTherRoomController','MatchTherRoomModel','MatchTherRoomScene',
 'RankMatchController','RankMatchModel','CreateTeamDialog','TeamChooseHeroDialog','ChallengeEntryScene','JoinRoomInputer'}) do
 local c=package.loaded[name]
 if type(c)~='table' then pcall(function() return CSLTypes[name] end);c=package.loaded[name] end
 local d=type(c)=='table' and c.__instanceDict
 out[#out+1]='CLASS '..name..' '..type(d)
 if d then local names={};for k,f in pairs(d) do if type(k)=='string' and type(f)=='function' then names[#names+1]=k end end;table.sort(names)
  for _,k in ipairs(names) do local f=d[k]
   if u.funcinfo(f).bytecodes then
    local ks={};local relevant=k:lower():match('^send') or k:lower():match('^parse')
    for i=-1,-160,-1 do local v=u.funck(f,i);if v==nil then break end
     if type(v)=='string' then
      ks[#ks+1]=v
      if v:find('Room') or v:find('room') or v:find('Quest') or v:find('quest') or v:find('Match') or v:find('好友') or v:find('匹配') or v:find('关隘') or v:lower():find('random') then relevant=true end
     end
    end
    if relevant then out[#out+1]='METHOD '..name..'.'..k..' P='..u.funcinfo(f).params..' '..table.concat(ks,'|') end
   end
  end
 end
end
for _,name in ipairs({'PVEModel','MatchTherRoomModel'}) do
 local ok,m=pcall(function() return CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes[name]) end)
 if ok and type(m)=='table' then for k,v in pairs(m) do
  if type(k)=='string' then out[#out+1]='CACHE '..name..'.'..k..' '..type(v) end
 end end
end
return table.concat(out,'\n')
