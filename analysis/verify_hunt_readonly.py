"""Load the production hunt runtime privately and verify discovery/planning with every spending gate off."""
import json
import subprocess
import sys
import time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB
from monster import default_formation


def main():
    """Read one visible target and native formations; always restore callback/observer ownership."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'));script.load()
    result={'spending_enabled':False}
    try:
        script.exports_sync.query('assert(REA_HUNT_VERIFY==nil);REA_HUNT_VERIFY={};return "created"')
        for name in ('hero_runtime.lua','monster_runtime.lua'):
            source=(ROOT/'auto_infantry'/name).read_text(encoding='utf-8')
            if name=='monster_runtime.lua':
                # Private read-only probe: compare the native zero-stock start check with an owned hero's actual default payload.
                source=source.replace("return 'hunt_api_installed'",r'''
function api.verify_native_defaults()
 local rows={}
 for i=0,available[4]:get_Count()-1 do
  local h=available[4]:get_Item(i)
  if h[1][1][3]==110 then
   for _,stock in ipairs({0,h[2]:get_Item(0)[2]}) do
    local copy={};for k,v in pairs(h) do copy[k]=v end
    copy[2]=CSLNew(CSLTypes.CSLList);copy[2]:Add({[1]=h[2]:get_Item(0)[1],[2]=stock})
    local f=defaultFormation(copy,false);local fields={}
    for j=0,f.soldiers:get_Count()-1 do
     local s=f.soldiers:get_Item(j);fields[#fields+1]=encode({soldier_id=s[1],count=s[2],position=s[3]})
    end
    rows[#rows+1]='{"profile":'..encode({hero_id=110,stock=stock,followers=f.followers,start_enabled=f.start_enabled,
     power=f.power,enemy=f.enemy,cap=f.cap,recommendation=f.label})..',"soldiers":['..table.concat(fields,',')..']}'
   end
  end
 end
 return '['..table.concat(rows,',')..']'
end
return 'hunt_api_installed'
''')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_HUNT_VERIFY},{__index=_G});local f=assert(loadstring('+json.dumps(source,ensure_ascii=False)+'));setfenv(f,env);return f()')
        script.exports_sync.query('return REA_HUNT_VERIFY.hero_refresh()')
        end=time.monotonic()+6
        while time.monotonic()<end:
            heroes=json.loads(script.exports_sync.query('return REA_HUNT_VERIFY.hero_list()'))
            if heroes['fresh']:break
            time.sleep(.1)
        result['schedule']=json.loads(script.exports_sync.query('return REA_HUNT_VERIFY.hunt_schedule()'))
        rows=json.loads(script.exports_sync.query('return REA_HUNT_VERIFY.hunt_candidates(20)'))
        result['loaded']=len(rows);result['visible_idle']=sum(r['visible'] and r['idle'] for r in rows)
        target=next((r for r in sorted(rows,key=lambda r:r['distance']) if r['visible'] and r['idle']),None)
        if len(sys.argv)>1:
            target=next((r for r in rows if r['target_id']==int(sys.argv[1])),None)
            if target is None:raise RuntimeError('Requested target is outside the loaded validation scope')
        if target:
            script.exports_sync.query(f"return REA_HUNT_VERIFY.hunt_query({target['target_id']})")
            end=time.monotonic()+6
            while time.monotonic()<end:
                state=json.loads(script.exports_sync.query('return REA_HUNT_VERIFY.hunt_status()'))
                if state['ready']:
                    metrics=json.loads(script.exports_sync.query('return REA_HUNT_VERIFY.hunt_metrics()'))
                    result['target']=metrics['target'];result['plan']=default_formation(metrics)
                    result['formation_rows']=len(metrics['formations'])
                    result['strength_evidence']={k:metrics.get(k) for k in ('strength_known','can_win_full','candidate_heroes','missing_heroes')}
                    result['native_default_validation']=json.loads(script.exports_sync.query('return REA_HUNT_VERIFY.verify_native_defaults()'))
                    break
                time.sleep(.1)
            else:raise TimeoutError('No native query responses')
        print(json.dumps(result,ensure_ascii=False))
    finally:
        (ROOT/'analysis/evidence/hunt-production-readonly.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        try:script.exports_sync.query('if REA_HUNT_VERIFY and REA_HUNT_VERIFY.hunt_close then REA_HUNT_VERIFY.hunt_close() end;REA_HUNT_VERIFY=nil;return "closed"')
        finally:script.exports_sync.close();script.unload();session.detach()

if __name__=='__main__':main()
