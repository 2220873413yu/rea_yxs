"""Install isolated production rescue readers, check fresh server state and remove only this probe."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import frida

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB, Connection


class PrivateQueries:
    """Bind Connection's fixed read helpers to an isolated API without touching the running assistant."""

    def __init__(self,exports):
        self.exports=exports

    def query(self,source,*args):
        """Allow only non-spending requests and rewrite the API namespace, not the native models."""
        assert not args or args[0] is False,'Read-only verification cannot open an action gate'
        return self.exports.query(source.replace('REA_AUTO_INFANTRY','REA_BEACON_MODULE_VERIFY'),*args)


def main():
    """Read one event list and fresh hero/army state; never depart, retreat, scout or claim."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],
        text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load();created=False
    try:
        script.exports_sync.query('assert(REA_BEACON_MODULE_VERIFY==nil,"Probe exists");'
                                  'REA_BEACON_MODULE_VERIFY={};return "isolated_api_created"')
        created=True
        for name in ('hero_runtime.lua','beacon_runtime.lua','beacon_actions.lua'):
            source=(ROOT/'auto_infantry'/name).read_text(encoding='utf-8')
            chunk='local env=setmetatable({REA_AUTO_INFANTRY=REA_BEACON_MODULE_VERIFY},{__index=_G});'
            chunk+='local f=assert(loadstring('+json.dumps(source,ensure_ascii=False)+'));setfenv(f,env);return f()'
            print(name,script.exports_sync.query(chunk))
        connection=Connection()
        connection.script=SimpleNamespace(exports_sync=PrivateQueries(script.exports_sync))
        connection.query_beacon()
        roster=connection.refresh_heroes()
        snapshot=connection.beacon_call('beacon_snapshot')
        watch=connection.beacon_call('beacon_watch')
        assert isinstance(watch.get('signature'),str),'Passive watch signature missing'
        connection.beacon_call('beacon_configure',(15,))
        policies=[]
        for kind in (3,4,2):
            event=next((e for e in snapshot['events'] if e['kind']==kind and e['state']==0),None)
            if event is None:continue
            identifier=event['event_id']
            connection.refresh_heroes()
            if kind==2:
                connection.script.exports_sync.query(f'return REA_AUTO_INFANTRY.beacon_scout_query({identifier})')
                deadline=time.monotonic()+6
                while time.monotonic()<deadline:
                    value=connection.beacon_call('beacon_scout_result',(identifier,))
                    if value['ready']:break
                    time.sleep(.1)
                assert value['ready'],'Scout stock response timeout'
            else:
                connection.script.exports_sync.query(f'return REA_AUTO_INFANTRY.beacon_target_query({identifier})')
                connection._wait_beacon_read('beacon_target_result')
                connection.script.exports_sync.query(f'return REA_AUTO_INFANTRY.beacon_candidates_query({identifier})')
                value=connection._wait_beacon_read('beacon_candidates_result')
                hero=next((h for h in value['heroes'] if h['ready']),None)
                if hero:
                    source=('local n=REA_AUTO_INFANTRY.beacon_native;local a=n.available();'
                            'for i=0,a[4]:get_Count()-1 do local h=a[4]:get_Item(i);'
                            f'if h[1][1][3]=={hero["hero_id"]} then local _,count,soldier=n.formation(h,n.event({identifier}));'
                            'return REA_AUTO_INFANTRY.encode_flat_state({count=count,soldier=soldier}) end end')
                    value['native_default']=json.loads(connection.script.exports_sync.query(source))
            policies.append(dict(kind=kind,event_id=identifier,result=value))
            print('policy',kind,'eligible',sum(h['ready'] for h in value.get('heroes',[])) if kind!=2 else value)
        result=dict(mode='read_only_all_action_gates_closed',hero_count=len(roster['heroes']),snapshot=snapshot)
        result['policies']=policies
        result['passive_watch_verified']=True
        path=ROOT/'analysis/evidence/beacon-module-production-readonly.json'
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(ready=snapshot['ready'],queue_used=snapshot['queue_used'],
            queue_limit=snapshot['queue_limit'],event_types=[e['kind'] for e in snapshot['events']],
            hero_count=len(roster['heroes']),own_beacon_armies=len(snapshot['armies'])),ensure_ascii=False))
    finally:
        if created:
            script.exports_sync.query('if REA_BEACON_MODULE_VERIFY.beacon_close then '
                'REA_BEACON_MODULE_VERIFY.beacon_close() end;REA_BEACON_MODULE_VERIFY=nil;return "isolated_probe_removed"')
        script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':main()
