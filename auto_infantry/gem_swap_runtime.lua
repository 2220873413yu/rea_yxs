-- Client-side 宝具 substitution for the owned battle hero. It never sends a request, never
-- touches a non-empty slot unless asked, and restores the original slot values on demand.
if REA_GEM_SWAP then REA_GEM_SWAP.close() end
local api = {}
REA_GEM_SWAP = api

local mm = CSLTypes.ModelManager.sharedInstance()

local function json(v)
  local t = type(v)
  if t == 'nil' then return 'null'
  elseif t == 'boolean' or t == 'number' then return tostring(v)
  elseif t == 'string' then
    return '"' .. v:gsub('[%z\1-\31\\"]', function(c) return string.format('\\u%04x', string.byte(c)) end) .. '"'
  end
  assert(t == 'table', 'Unsupported gem swap value')
  local rows = {}
  local array = next(v) == nil or type(next(v)) == 'number'
  if array then
    for _, x in ipairs(v) do rows[#rows + 1] = json(x) end
    return '[' .. table.concat(rows, ',') .. ']'
  end
  for k, x in pairs(v) do rows[#rows + 1] = json(k) .. ':' .. json(x) end
  return '{' .. table.concat(rows, ',') .. '}'
end

local function model(name) return mm:getModel(CSLTypes[name]) end

local function ownHero(game, map)
  local seat = game:getMyServerSeatId()
  for i = 0, map:get_Count() - 1 do
    local hero = map:get_Item(i)
    if hero then
      local ok, value = pcall(function() return hero:getServerSeatID() end)
      if ok and value == seat then return hero, i end
    end
  end
  return nil
end

local state = {
  enabled = false,
  hero_base = 0,
  owners = {},
  applied = {},
  backup = {},
  note = 'off',
  last_key = nil,
}

-- Config row carries everything the game itself reads: skill id, gem type, star and trigger parameter.
local function gemRow(gem)
  local ok, row = pcall(function() return CSLTypes.DBSearcher.sharedInstance():searchGemInfo(gem) end)
  if not ok or type(row) ~= 'table' then return nil end
  return row
end

local function triggerParam(row, gem, heroStar)
  local okay, value = pcall(function() return CSLTypes.ItemsModel.getTriggerRate(gem, 50, heroStar) end)
  if row[2] == 1 and okay and type(value) == 'number' then return value end
  local raw = row[34]
  if type(raw) == 'number' then return raw end
  return 0
end

local function snapshot(hero)
  local out = {}
  local gems = hero:getHeroGemInfo()
  if gems then
    for i = 0, gems:get_Count() - 1 do
      local g = gems:get_Item(i)
      out[#out + 1] = { slot = i, unlock = g.bIsUnLock and true or false, gem = g.iGemID or -1,
                        skill = g.iSkillID or -1, type = g.iGemType or -1,
                        level = g.iLevel or 0, star = g.iStar or 0, param = g.iParam or 0 }
    end
  end
  return out
end

local function emptySlots(gems)
  local rows = {}
  for i = 0, gems:get_Count() - 1 do
    local g = gems:get_Item(i)
    if (g.iGemID or 0) <= 0 or g.bIsUnLock ~= true then rows[#rows + 1] = i end
  end
  return rows
end

local function satisfied(hero)
  local gems = hero:getHeroGemInfo()
  if not gems then return false end
  for _, plan in ipairs(state.owners) do
    local found = false
    for i = 0, gems:get_Count() - 1 do
      local g = gems:get_Item(i)
      if g.iGemID == plan.gem and g.iSkillID == plan.skill then found = true end
    end
    if not found then return false end
  end
  return true
end

-- A gem's skill id only sits in the id pool; the engine still treats the skill instance as an
-- empty shell. Bind the config row and register the object on this hero card so card-play
-- legality actually asks the skill (e.g. 天狼: no limit on using 【杀】).
local function bindSkills(hero)
  local report = {}
  local mgr = CSLTypes.CSkillMgr.sharedInstance()
  local db = CSLTypes.DBSearcher.sharedInstance()
  local list = CSLNew(CSLTypes.CSLList)
  for _, plan in ipairs(state.owners) do
    local okFind, sk = pcall(function() return mgr:FindSkill(plan.skill) end)
    if okFind and sk then
      local okRow, row = pcall(function() return db:searchSkillInfo(plan.skill) end)
      if okRow and row then
        pcall(function() sk:setSkillInfo(row) end)
      end
      pcall(function() list:Add(sk) end)
      report[#report + 1] = 'obj' .. tostring(plan.skill)
    end
  end
  if list:get_Count() > 0 then
    local okAdd = pcall(function() hero:addHeroSkills(list) end)
    report[#report + 1] = 'addHeroSkills=' .. tostring(okAdd)
  end
  pcall(function() hero:initHeroSkillModels() end)
  local okModels, models = pcall(function() return hero:getHeroSkillModels() end)
  if okModels and models then
    local ids = {}
    for i = 0, models:get_Count() - 1 do
      local m = models:get_Item(i)
      local id = '?'
      pcall(function() id = m:getHeroSkillID() end)
      ids[#ids + 1] = tostring(id)
    end
    report[#report + 1] = 'models=' .. table.concat(ids, ',')
  end
  local first = state.owners[1]
  if first then
    local okLimit, limit = pcall(function() return mgr:FindSkill(first.skill):getMaxAddTurnLimit() end)
    report[#report + 1] = 'maxAddTurnLimit=' .. tostring(okLimit and limit)
  end
  state.bind = report
  return report
end

-- Native heroes carry their skills in _heroBaseData.skillIdList/ownSkillIdList; a gem only adds
-- the skill id to the general pool, which card-play legality never consults. Append the id to the
-- same two lists (plain data, no skill objects) so the hero looks like a native carrier.
local function appendOwnSkills(hero)
  local report = {}
  local base = hero._heroBaseData
  if type(base) ~= 'table' then return { 'no_base' } end
  for _, key in ipairs({ 'skillIdList', 'ownSkillIdList' }) do
    local list = base[key]
    if type(list) ~= 'table' then
      report[#report + 1] = key .. '=missing'
    else
      local okAdd = pcall(function()
        for _, plan in ipairs(state.owners) do
          local present = false
          for i = 0, list:get_Count() - 1 do
            if list:get_Item(i) == plan.skill then present = true end
          end
          if not present then list:Add(plan.skill) end
        end
      end)
      report[#report + 1] = key .. '=' .. tostring(okAdd)
    end
  end
  pcall(function() hero:initHeroSkillModels() end)
  local okModels, models = pcall(function() return hero:getHeroSkillModels() end)
  if okModels and models then
    local ids = {}
    for i = 0, models:get_Count() - 1 do
      local m = models:get_Item(i)
      local id = '?'
      pcall(function() id = m:getHeroSkillID() end)
      ids[#ids + 1] = tostring(id)
    end
    report[#report + 1] = 'models=' .. table.concat(ids, ',')
  end
  state.bind = report
  return report
end

-- Fill empty signed slots in order; never overwrite an occupied or locked-with-data slot.
-- quiet=true is used inside the push hook: the game rebuilds skill models right after, so we
-- must not call initHeroSkillModels/notifyHeroGemInfo from inside that same flow.
local function apply(hero, quiet)
  local gems = hero:getHeroGemInfo()
  if not gems then return nil, 'no_gem_list' end
  local free = emptySlots(gems)
  local star = 1
  pcall(function() star = hero:getHeroStar() or 1 end)
  local filled = {}
  for index, plan in ipairs(state.owners) do
    local slot = free[index]
    if slot == nil then return nil, 'no_empty_slot' end
    local g = gems:get_Item(slot)
    state.backup[slot] = { slot = slot, unlock = g.bIsUnLock, gem = g.iGemID, skill = g.iSkillID,
                           type = g.iGemType, level = g.iLevel, star = g.iStar, param = g.iParam }
    g.bIsUnLock = true
    g.iGemID = plan.gem
    g.iSkillID = plan.skill
    g.iGemType = plan.type
    g.iLevel = 50
    g.iStar = plan.star
    g.iParam = plan.param(star)
    filled[#filled + 1] = { slot = slot, gem = plan.gem, skill = plan.skill }
  end
  if not quiet then
    pcall(function() hero:initHeroSkillModels() end)
    pcall(function() hero:notifyHeroGemInfo() end)
  end
  return filled
end

-- Install the push-time hook: the game copies gems (addHeroGems) and then builds skill models
-- inside PVEModel.updatePVEGameHero, so filling slots in between makes the skill part of the
-- very first rule calculation of the battle instead of a late edit.
local hooked = false
local busy = false
local original = {}

local function dict(name)
  local c = package.loaded[name]
  if type(c) ~= 'table' then return nil end
  return c.__instanceDict or c
end

local function tryApply(hero)
  if hooked == false or busy or not state.enabled or #state.owners == 0 then return end
  if hero == nil then return end
  busy = true
  pcall(function()
    local card = hero:getCardID()
    if card == nil or not isTarget(card) then return end
    if satisfied(hero) then return end
    apply(hero, true)
  end)
  busy = false
end

local function install()
  if hooked then return end
  local hc = dict('HeroCardModel')
  if not hc or type(hc.addHeroGems) ~= 'function' or type(hc.initHeroSkillModels) ~= 'function' then return end
  original.addHeroGems = hc.addHeroGems
  original.initHeroSkillModels = hc.initHeroSkillModels
  hc.addHeroGems = function(self, list)
    local result = { original.addHeroGems(self, list) }
    tryApply(self)
    return unpack(result)
  end
  hc.initHeroSkillModels = function(self)
    tryApply(self)
    return original.initHeroSkillModels(self)
  end
  hooked = true
end

local function uninstall()
  if not hooked then return end
  local hc = dict('HeroCardModel')
  if hc then
    if original.addHeroGems then hc.addHeroGems = original.addHeroGems end
    if original.initHeroSkillModels then hc.initHeroSkillModels = original.initHeroSkillModels end
  end
  original.addHeroGems, original.initHeroSkillModels = nil, nil
  hooked = false
end

-- Explicit rules only: gem id 0 means that position is left untouched.
function api.configure(hero_base, gem_a, gem_b, enabled)
  state.enabled = enabled == 1
  state.hero_base = hero_base or 0
  state.owners = {}
  state.last_key = nil
  local function add(gem)
    if type(gem) ~= 'number' or gem <= 0 then return end
    local row = gemRow(gem)
    assert(row, 'Gem config missing for ' .. tostring(gem))
    state.owners[#state.owners + 1] = { gem = gem, skill = row[9], type = row[2], star = row[4],
                                       param = function(star) return triggerParam(row, gem, star) end }
  end
  add(gem_a)
  add(gem_b)
  if state.enabled then install() else uninstall() end
  state.note = state.enabled and 'armed' or 'off'
  return api.status()
end

function api.status()
  return json({ enabled = state.enabled, hero_base = state.hero_base, note = state.note, hook = hooked, bind = state.bind,
                gems = (function() local out = {} for _, p in ipairs(state.owners) do out[#out + 1] = { gem = p.gem, skill = p.skill } end return out end)() })
end

-- Read the hero this battle actually assigned to the local seat, including its current slots.
function api.current_hero()
  local okay, result = pcall(function()
    local game = model('GameModel')
    local map = game and game:get_mapHeros()
    if not map or map:get_Count() == 0 then return { state = 'not_in_battle', note = 'not_in_battle' } end
    local hero = ownHero(game, map)
    if not hero then return { state = 'no_hero', note = 'own_hero_not_found' } end
    local card = hero:getCardID()
    return { state = 'found', hero = card, slots = snapshot(hero) }
  end)
  if not okay then return json({ state = 'error', note = tostring(result) }) end
  return json(result)
end

-- Battle hero ids are star*1000+base, so one configured base matches every star variant.
local function isTarget(card)
  if state.hero_base <= 0 then return true end
  return card == state.hero_base or (card % 1000) == state.hero_base
end

-- Resolve a hero name (passed as GBK hex) through the game's own hero config rows.
function api.resolve_hero(hexname)
  local okay, result = pcall(function()
    if type(hexname) ~= 'string' or #hexname % 2 ~= 0 then return { state = 'failed', note = 'bad_name' } end
    local target = hexname:gsub('..', function(pair) return string.char(tonumber(pair, 16)) end)
    local db = CSLTypes.DBSearcher.sharedInstance()
    local ids = {}
    for id = 1, 20000 do
      local row = db:searchHeroInfo(id)
      if type(row) == 'table' and type(row[7]) == 'string' and row[7] == target then ids[#ids + 1] = id end
    end
    if #ids == 0 then return { state = 'failed', note = 'not_found' } end
    local base = ids[1] % 1000
    return { state = 'found', hero_base = base, ids = ids,
             name_hex = (target:gsub('.', function(c) return string.format('%02X', string.byte(c)) end)) }
  end)
  if not okay then return json({ state = 'error', note = tostring(result) }) end
  return json(result)
end

-- One bounded check driven by the helper loop; returns the observed state instead of raising.
function api.tick()
  if not state.enabled then return json({ state = 'off', note = 'off' }) end
  local okay, result = pcall(function()
    local game = model('GameModel')
    local map = game and game:get_mapHeros()
    if not map or map:get_Count() == 0 then return { state = 'waiting', note = 'not_in_battle' } end
    local hero = ownHero(game, map)
    if not hero then return { state = 'waiting', note = 'own_hero_not_found' } end
    local card = hero:getCardID()
    if state.hero_base > 0 and not isTarget(card) then
      return { state = 'waiting', note = 'hero_mismatch', hero = card, target = state.hero_base }
    end
    if satisfied(hero) then
      state.note = 'applied'
      return { state = 'applied', hero = card, slots = snapshot(hero) }
    end
    local filled, err = apply(hero)
    if not filled then return { state = 'failed', note = err } end
    state.note = 'applied'
    return { state = 'applied', hero = card, slots = snapshot(hero), filled = filled, bind = state.bind }
  end)
  if not okay then
    state.note = tostring(result)
    return json({ state = 'error', note = state.note })
  end
  return json(result)
end

-- Restore every slot this session changed, in place.
function api.revert()
  local okay, result = pcall(function()
    local game = model('GameModel')
    local map = game and game:get_mapHeros()
    if not map or map:get_Count() == 0 then return { state = 'waiting', note = 'not_in_battle' } end
    local hero = ownHero(game, map)
    if not hero then return { state = 'waiting', note = 'own_hero_not_found' } end
    local gems = hero:getHeroGemInfo()
    if not gems then return { state = 'failed', note = 'no_gem_list' } end
    local restored = 0
    for slot, saved in pairs(state.backup) do
      if slot < gems:get_Count() then
        local g = gems:get_Item(slot)
        g.bIsUnLock = saved.unlock
        g.iGemID = saved.gem
        g.iSkillID = saved.skill
        g.iGemType = saved.type
        g.iLevel = saved.level
        g.iStar = saved.star
        g.iParam = saved.param
        restored = restored + 1
      end
    end
    state.backup = {}
    pcall(function() hero:initHeroSkillModels() end)
    pcall(function() hero:notifyHeroGemInfo() end)
    state.note = 'reverted'
    return { state = 'reverted', restored = restored, slots = snapshot(hero) }
  end)
  if not okay then return json({ state = 'error', note = tostring(result) }) end
  return json(result)
end

function api.close()
  state.enabled = false
  state.owners = {}
  state.backup = {}
  uninstall()
  return 'gem_swap_closed'
end

return 'gem_swap_api_installed'
