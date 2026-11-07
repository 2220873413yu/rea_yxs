"""Research own alliance mines through read requests only, keeping all spending gates disabled."""
import json
import subprocess
import sys
import time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB


def main():
    """Refresh own buildings and one mine, summarize metrics, and always remove private callbacks."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'));script.load()
    result={'spending_enabled':False}
    def wait(operation):
        """Poll only the private in-memory capture for a bounded read response; never repeat server queries."""
        end=time.monotonic()+6
        while time.monotonic()<end:
            data=json.loads(script.exports_sync.query('return REA_LEAGUE_READONLY.'+operation+'()'))
            if data['ready']:return data
            time.sleep(.1)
        raise TimeoutError(operation+' did not receive a new response')
    try:
        script.exports_sync.query('assert(REA_LEAGUE_READONLY==nil);REA_LEAGUE_READONLY={};return "created"')
        for path in (ROOT/'auto_infantry/hero_runtime.lua',ROOT/'analysis/league_readonly_probe.lua'):
            source=path.read_text(encoding='utf-8')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_LEAGUE_READONLY},{__index=_G});local f=assert(loadstring('+json.dumps(source,ensure_ascii=False)+'));setfenv(f,env);return f()')
        script.exports_sync.query('return REA_LEAGUE_READONLY.league_build_query()')
        result['buildings']=wait('league_build_result')
        if result['buildings']['mine']['found']:
            target=result['buildings']['mine']['target_id']
            script.exports_sync.query('return REA_LEAGUE_READONLY.hero_refresh()')
            script.exports_sync.query(f'return REA_LEAGUE_READONLY.league_mine_query({target})')
            data=wait('league_mine_result');result['details']=data
            print(json.dumps({'buildings':result['buildings'],'mine':data['mine'],'config':data['config'],'armies':data['armies'],
                              'top_idle':sorted((r for r in data['heroes'] if not r['busy'] and r['hero_state']==0 and r['cooldown_ms']<=0),
                                                key=lambda r:(-r['speed'],-r['load']))[:5]},ensure_ascii=False))
        else:print(json.dumps(result,ensure_ascii=False))
    finally:
        (ROOT/'analysis/evidence/league-mine-live-readonly.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        try:script.exports_sync.query('if REA_LEAGUE_READONLY and REA_LEAGUE_READONLY.league_close then REA_LEAGUE_READONLY.league_close() end;REA_LEAGUE_READONLY=nil;return "closed"')
        finally:script.exports_sync.close();script.unload();session.detach()

if __name__=='__main__':main()
