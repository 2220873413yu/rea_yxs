-- Inspect dispatch lifecycle, notification readers and protocol fields; never invoke business callbacks.
local out={};local u=require('jit.util')
local function dump(label,fn,bytecode)
 if type(fn)~='function' then return end
 local info=u.funcinfo(fn);if not info.bytecodes then return end
 out[#out+1]='FUNCTION '..label..' params='..info.params
 for i=-1,-170,-1 do local v=u.funck(fn,i);if v==nil then break end
  if type(v)=='string' then out[#out+1]='K '..(-i-1)..' '..CSLTypes.YXSUtils.GBK2UTF8(v) end
 end
 for i=0,30 do local v=u.funck(fn,i);if v==nil then break end;out[#out+1]='N '..i..' '..tostring(v) end
 if bytecode then for pc=1,info.bytecodes-1 do local bc=u.funcbc(fn,pc)
  out[#out+1]=string.format('BC %d OP=%d A=%d B=%d C=%d D=%d',pc,bc%256,math.floor(bc/256)%256,
   math.floor(bc/16777216)%256,math.floor(bc/65536)%256,math.floor(bc/65536)%65536)
 end end
end
for _,name in ipairs({'SLGDispatchController','SLGDispatchModel','SLGDispatchDialog',
 'SLGDispatchListTaskItem','SLGDispatchChooseHeroScene','SLGDispatchArmyInfo'}) do
 local cls=package.loaded[name]
 if type(cls)~='table' then pcall(function() return CSLTypes[name] end);cls=package.loaded[name] end
 local d=type(cls)=='table' and cls.__instanceDict
 out[#out+1]='MODULE '..name..' '..type(d)
 if d then for k,f in pairs(d) do
  if type(k)=='string' and (k:match('^parse') or k=='updateSelf' or k=='Update' or k=='AutoDispatch' or
   k=='isDispatchUnlock' or k=='OnDestroy' or k=='UpdateTaskList' or k=='UpdateTask' or
   k:find('Reward') or k:find('DuHuFu') or k:find('Finish') or k:find('Time')) then
   dump(name..'.'..k,f,name=='SLGDispatchController' or k=='isDispatchUnlock' or k=='updateSelf' or k=='Update')
  end
 end end
end
local p=package.loaded.ChatClientProtoDes
for name,d in pairs(p) do if type(name)=='string' and type(d)=='table' and (name:find('DuHuFu') or name:find('DUHUFU')) then
 out[#out+1]='TYPE '..name
 for slot,f in ipairs(d) do if type(f)=='table' then
  out[#out+1]=string.format('FIELD slot=%s tag=%s name=%s struct=%s',slot,tostring(f.tag),tostring(f.name),
   type(f.struct_path)=='table' and table.concat(f.struct_path,'.') or '')
 end end
end end
return table.concat(out,'\n')
