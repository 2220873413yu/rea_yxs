"""Read two cached nearby monsters from the server without moving the map or sending combat requests."""
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
    """Capture native read responses, evaluate pure combat hints, and always restore callbacks."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,
        creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    result={'monsters':[],'spending_enabled':False}
    center='local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMapObjectModel);return tostring(m.screenCenter[1])..","..tostring(m.screenCenter[2])'
    try:
        result['center_before']=script.exports_sync.query(center)
        script.exports_sync.query('assert(REA_MONSTER_READONLY==nil);REA_MONSTER_READONLY={};return "created"')
        for path in (ROOT/'auto_infantry/hero_runtime.lua',ROOT/'analysis/monster_readonly_probe.lua'):
            chunk=path.read_text(encoding='utf-8')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_MONSTER_READONLY},{__index=_G});local f=assert(loadstring('+json.dumps(chunk,ensure_ascii=False)+'));setfenv(f,env);return f()')
        for target in (152468,152783):
            script.exports_sync.query('return REA_MONSTER_READONLY.hero_refresh()')
            script.exports_sync.query(f'return REA_MONSTER_READONLY.monster_query({target})')
            end=time.monotonic()+6
            while time.monotonic()<end:
                data=json.loads(script.exports_sync.query('return REA_MONSTER_READONLY.monster_result()'))
                if data['ready']:
                    result['monsters'].append(data)
                    ranked=sorted((h for h in data['heroes'] if not h['busy'] and h['hero_state']==0),key=lambda h:-h['power'])
                    print(json.dumps({'detail':data['detail'],'quest_strings':data['quest_strings'],'top_options':ranked[:5]},ensure_ascii=False),flush=True)
                    break
                time.sleep(.15)
            else:
                raise TimeoutError(f'Read queries for monster{target} did not produce matching responses')
        result['center_after']=script.exports_sync.query(center)
        print('CENTER',result['center_before'],result['center_after'],flush=True)
    finally:
        (ROOT/'analysis/evidence/monster-live-readonly.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            script.exports_sync.query('if REA_MONSTER_READONLY and REA_MONSTER_READONLY.monster_close then REA_MONSTER_READONLY.monster_close() end;REA_MONSTER_READONLY=nil;return "closed"')
        finally:
            script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
