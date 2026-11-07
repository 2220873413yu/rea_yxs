-- Compact public receipt from the running experiment, preserving all native response ownership checks.
local s=assert(REA_TRIAL_ONE_LAYER).status()
local selected=assert(s:match('"selected":(%b[])'))
local tail=assert(s:match('("battle_ready":.*)'))
return '{"selected":'..selected..','..tail
