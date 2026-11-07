-- Inspect the already-installed helper's cached target detail only; no query or callback replacement.
local out={};local api=REA_AUTO_INFANTRY
if not api or not api.collect_metrics then return 'No existing collection cache reader' end
local detail,available
for i=1,30 do local name,value=debug.getupvalue(api.collect_metrics,i);if not name then break end
 if name=='detail' then detail=value elseif name=='available' then available=value end
end
if detail then
 out[#out+1]='target_id='..tostring(detail[2][1][1][2])..' remaining='..tostring(detail[2][1][6])
 local rows=detail[2][2]
 for i=0,rows:get_Count()-1 do local r=rows:get_Item(i)
  out[#out+1]=string.format('collector army=%s hero=%s count=%s maximum=%s',tostring(r[1][1]),
   tostring(r[1][15][1]),tostring(r[2]),tostring(r[3]))
 end
end
if available then out[#out+1]='target_hero_rows='..tostring(available[4]:get_Count()) end
return #out>0 and table.concat(out,'\n') or 'No cached target detail'
