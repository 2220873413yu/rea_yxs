"""Read fresh dispatch tasks/candidates and own army occupancy; no selection or spending methods exist."""
import json
import subprocess
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]
ADB = r'E:\leidian\LDPlayer9\adb.exe'
PROBE = r'''
local api=assert(REA_DISPATCH_CANDIDATES_READONLY)
local mm=CSLTypes.ModelManager.sharedInstance();local m=mm:getModel(CSLTypes.SLGDispatchModel)
local main=mm:getModel(CSLTypes.SLGMainModel);local bound=main.mTSLGLoginMapRsp
local c=CSLTypes.SLGDispatchController.getInstance();local beforeTasks,beforeHeroes,beforeArmies;local target
local function check() assert(main.mTSLGLoginMapRsp==bound,'Account/world changed') end
function api.query_tasks()
 check();beforeTasks=m.duhufuInfo;c:sendTSLGDuHuFuGetInfoReq();return 'sent_once'
end
function api.tasks()
 check();local r=m.duhufuInfo;if not r or r==beforeTasks then return 'pending' end
 assert(r[1]==0,'Dispatch tasks refused: '..tostring(r[1]))
 local best
 for i=0,m.taskInfo:get_Count()-1 do local t=m.taskInfo:get_Item(i)
  if t[3]==0 and (not best or t[1]<best[1]) then best=t end
 end
 assert(best,'No unstarted task available; nothing dispatched')
 target=best[1];local conf=CSLTypes.DBSearcher.sharedInstance():GetSLGDuHuFuEvent(best[2])
 return string.format('task_id=%d\nconfig_id=%d\nname=%s\nconditions=%s\nthresholds=%s\ncounts=%s\npeople=%s',
  target,best[2],CSLTypes.YXSUtils.GBK2UTF8(conf[4]),tostring(conf[6]),tostring(conf[7]),tostring(conf[12]),tostring(conf[8]))
end
function api.query_candidates()
 check();assert(target);beforeHeroes=m.selectHeroList
 c:sendTSLGDuHuFuGetHeroListReq(target)
 return 'sent_once'
end
function api.candidates()
 check();local r=m.selectHeroList;if not r or r==beforeHeroes then return 'pending' end
 assert(r[1]==0 and r[2]==target,'Candidate response failed or foreign task: '..tostring(r[1]))
 local out={'candidate_task='..target};local d=r[3];local keys=d:GetDictKeys();local seen={}
 for i=0,keys:get_Count()-1 do local key=keys:get_Item(i);local list=d:get_Item(key)
  out[#out+1]='bucket='..tostring(key)..',count='..tostring(list:get_Count())
  for j=0,list:get_Count()-1 do local h=list:get_Item(j);local id=h[1][4]
   if not seen[id] then
    seen[id]=true
    local conf=CSLTypes.DBSearcher.sharedInstance():searchHeroInfo(id)
    local name=conf and CSLTypes.YXSUtils.GBK2UTF8(conf[7]) or tostring(id)
    out[#out+1]=string.format('card_id=%d|hero_group=%d|name=%s|status=%d|recover_end_ms=%.0f',id,h[1][3],name,h[2],h[3])
   end
  end
 end
 return table.concat(out,'\n')
end
function api.query_armies()
 check();beforeArmies=main._myActionState
 if main.mIsMapLoaded~=true then return 'not_in_world_map; fresh army query skipped' end
 package.loaded.SLGMainController.__instanceDict.sendTSLGGetAllArmyReq()
 return 'sent_once'
end
function api.armies()
 check();local r=main._myActionState;if not r or r==beforeArmies then return 'pending' end
 assert(r[1]==0,'Army read unsuccessful')
 local out={}
 for _,index in ipairs({2,3}) do local list=r[index]
  for i=0,list:get_Count()-1 do local a=list:get_Item(i)
   out[#out+1]=string.format('army=%d|hero=%d|phase=%d|aim=%d',a[1],a[15][1],a[4],a[5])
  end
 end
 return #out>0 and table.concat(out,'\n') or 'no_active_own_armies'
end
return 'ready'
'''


def main():
    """Issue at most one query per stage, await fresh matching cache responses, and detach afterward."""
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                     text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    result = {'dispatch_sent': False, 'spending_gates_enabled': False}

    def call(method):
        """Expose only named methods of this read-only private probe; no product helper API is replaced."""
        return script.exports_sync.query('return REA_DISPATCH_CANDIDATES_READONLY.' + method + '()')

    def wait(method):
        """Await local receipt for a bounded query without resending it."""
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            value = call(method)
            if value != 'pending':
                return value
            time.sleep(.1)
        raise TimeoutError(method + ' response not received; query not repeated')

    try:
        script.exports_sync.query('assert(REA_DISPATCH_CANDIDATES_READONLY==nil);'
                                  'REA_DISPATCH_CANDIDATES_READONLY={};return "created"')
        script.exports_sync.query(PROBE)
        call('query_tasks'); result['task'] = wait('tasks')
        call('query_candidates'); result['candidates'] = wait('candidates')
        result['army_query'] = call('query_armies')
        if result['army_query'] == 'sent_once':
            result['armies'] = wait('armies')
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        (ROOT / 'analysis/evidence/dispatch-candidates-readonly.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        script.exports_sync.query('REA_DISPATCH_CANDIDATES_READONLY=nil;return "removed"')
        script.exports_sync.close(); script.unload(); session.detach()


if __name__ == '__main__':
    main()
