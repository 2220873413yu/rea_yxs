"""Read fresh beacon-dispatch tasks and one candidate list without selecting, claiming or refreshing."""
import json
import subprocess
import time
from pathlib import Path

import frida

ROOT=Path(__file__).resolve().parents[1]
ADB=r'E:\leidian\LDPlayer9\adb.exe'
NAMESPACE='REA_BEACON_RESEARCH_20261107'
SOURCE=r'''
local api=assert(REA_BEACON_RESEARCH_20261107)
local mm=CSLTypes.ModelManager.sharedInstance()
local m=mm:getModel(CSLTypes.SLGDispatchModel)
local main=mm:getModel(CSLTypes.SLGMainModel)
local search=CSLTypes.DBSearcher.sharedInstance()
local controller=CSLTypes.SLGDispatchController.getInstance()
local bound=main.mTSLGLoginMapRsp
local oldTasks,oldHeroes,target
local function check() assert(main.mTSLGLoginMapRsp==bound,'World/account changed during research') end
function api.query_tasks()
 check();oldTasks=m.duhufuInfo;controller:sendTSLGDuHuFuGetInfoReq();return 'one_info_query_sent'
end
function api.tasks()
 check();local r=m.duhufuInfo
 if not r or r==oldTasks then return 'pending' end
 assert(r[1]==0,'Task query refused: '..tostring(r[1]))
 local out={'level='..tostring(r[3]),'refresh_count='..tostring(r[4]),'tasks='..m.taskInfo:get_Count(),
  'server_now_seconds='..tostring(CSLTypes.RefreshTimer.getServerNatureTimeNow())}
 for i=0,m.taskInfo:get_Count()-1 do local t=m.taskInfo:get_Item(i);local c=search:GetSLGDuHuFuEvent(t[2])
  if t[3]==0 and not target then target=t[1] end
  local heroes={}
  if t[4] then for j=0,t[4]:get_Count()-1 do heroes[#heroes+1]=tostring(t[4]:get_Item(j)) end end
  out[#out+1]=string.format('task=%d|config=%d|status=%d|end=%s|heroes=%s|name=%s|stars=%s|people=%s|seconds=%s|conditions=%s|thresholds=%s|counts=%s',
   t[1],t[2],t[3],tostring(t[5]),table.concat(heroes,','),CSLTypes.YXSUtils.GBK2UTF8(c[4]),tostring(c[2]),
   tostring(c[8]),tostring(c[9]),tostring(c[6]),tostring(c[7]),tostring(c[12]))
 end
 return table.concat(out,'\n')
end
function api.query_candidates()
 check();if not target then return 'no_unstarted_task' end
 oldHeroes=m.selectHeroList;controller:sendTSLGDuHuFuGetHeroListReq(target);return 'one_candidate_query_sent'
end
function api.candidates()
 check();local r=m.selectHeroList
 if not r or r==oldHeroes then return 'pending' end
 assert(r[1]==0 and r[2]==target,'Candidate response failed or belongs to another task')
 local out={'task='..target};local seen={};local keys=r[3]:GetDictKeys()
 local own={};local armyRsp=main._myActionState
 if armyRsp and armyRsp[1]==0 then local list=armyRsp[2]
  for i=0,list:get_Count()-1 do local a=list:get_Item(i);own[a[15][1]]=a end
 end
 for i=0,keys:get_Count()-1 do local list=r[3]:get_Item(keys:get_Item(i))
  for j=0,list:get_Count()-1 do local h=list:get_Item(j);local card,group=h[1][4],h[1][3]
   if not seen[card] then seen[card]=true;local c=search:searchHeroInfo(card);local army=own[group]
    out[#out+1]=string.format('card=%d|group=%d|name=%s|status=%d|recover_end_ms=%.0f|cached_army_aim=%s|cached_army_phase=%s',
     card,group,CSLTypes.YXSUtils.GBK2UTF8(c[7]),h[2],h[3],army and tostring(army[5]) or 'none',army and tostring(army[4]) or 'none')
   end
  end
 end
 return table.concat(out,'\n')
end
return 'private_readonly_probe_ready'
'''


def main():
    """Use an isolated bridge for two bounded GETs and remove only this probe on completion."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],
                                   text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load();created=False
    result={'dispatch_sent':False,'reward_claimed':False,'task_refresh_sent':False,'spending_gates_enabled':False}

    def call(method):
        """Invoke only a named operation in this temporary read-only namespace."""
        return script.exports_sync.query(f'return {NAMESPACE}.{method}()')

    def wait(method):
        """Wait for one newly received response, without repeating a network request."""
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            value=call(method)
            if value!='pending':
                return value
            time.sleep(.1)
        raise TimeoutError(method+' response timeout; request not repeated')

    try:
        script.exports_sync.query(f'assert({NAMESPACE}==nil);{NAMESPACE}={{}};return "created"')
        created=True;script.exports_sync.query(SOURCE)
        call('query_tasks');result['tasks']=wait('tasks')
        result['candidate_query']=call('query_candidates')
        if result['candidate_query']=='one_candidate_query_sent':
            result['candidates']=wait('candidates')
        path=ROOT/'analysis/evidence/dispatch-current-readonly-20261107.json'
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(result['tasks'])
        print('candidate_rows='+str(len(result.get('candidates','').splitlines())-1))
        print('no_dispatch_no_rewards_no_task_refresh=true')
    finally:
        if created:
            script.exports_sync.query(f'{NAMESPACE}=nil;return "removed"')
        script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
