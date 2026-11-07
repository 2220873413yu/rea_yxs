"""Dispatch exactly one user-authorized league mine collector; no automatic mode is installed."""
import json
import subprocess
import sys
import time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog,tags
from game_protocol import JceReader


def main():
    """Read fresh mine/hero data, invoke native defaults once, and require an attributed server receipt."""
    evidence_path=ROOT/'analysis/evidence/league-collect-once.json'
    if evidence_path.exists() and json.loads(evidence_path.read_text(encoding='utf-8')).get('attempted'):
        raise RuntimeError('A departure was already attempted; inspect its outcome instead of rerunning')
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'));script.load()
    result={'attempted':False,'automatic_mode_installed':False}
    def query(source):
        """Run a bounded main-thread read, leaving the departure gate closed except for the single send."""
        return script.exports_sync.query(source)
    def wait(operation):
        """Await only captured in-memory responses without resending read or spending requests."""
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            data=json.loads(query('return REA_LEAGUE_READONLY.'+operation+'()'))
            if data['ready']:return data
            time.sleep(.1)
        raise TimeoutError('No new '+operation+' response; no automatic retry')
    try:
        query('assert(REA_LEAGUE_READONLY==nil);REA_LEAGUE_READONLY={};return "created"')
        for path in (ROOT/'auto_infantry/hero_runtime.lua',ROOT/'analysis/league_readonly_probe.lua'):
            source=path.read_text(encoding='utf-8')
            if path.name=='league_readonly_probe.lua':
                source=source.replace("return 'league_readonly_ready'",(ROOT/'analysis/league_collect_once.lua').read_text(encoding='utf-8'))
            query('local env=setmetatable({REA_AUTO_INFANTRY=REA_LEAGUE_READONLY},{__index=_G});local f=assert(loadstring('+json.dumps(source,ensure_ascii=False)+'));setfenv(f,env);return f()')
        query('return REA_LEAGUE_READONLY.league_build_query()')
        building=wait('league_build_result');mine=building['mine']
        result['building']=building
        assert mine['found'] and (mine['x'],mine['y'])==(125,72) and mine['config_id']==10003
        query('return REA_LEAGUE_READONLY.hero_refresh()')
        query(f"return REA_LEAGUE_READONLY.league_mine_query({mine['target_id']})")
        details=wait('league_mine_result');result['mine_before']=details['mine']
        plan=json.loads(query('local r=REA_LEAGUE_READONLY.league_once_plan();return REA_LEAGUE_READONLY.encode_flat_state(r)'))
        result['plan']=plan;print('PLAN',json.dumps(plan,ensure_ascii=False),flush=True)
        log=GameResponseLog(ADB);log.drain()
        # Persist before submission: a lost RPC response cannot make a second invocation look safe.
        result['attempted']=True;evidence_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        epoch=script.exports_sync.setcollectenabled(True)
        try:
            sent=json.loads(script.exports_sync.query('return REA_LEAGUE_READONLY.league_once_send()','collect',plan['hero_id'],epoch))
            result['submitted']=sent
        finally:script.exports_sync.setcollectenabled(False)
        saw_request=False;deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            for r in log.drain():
                if r['tag'].startswith('s_11010_'):
                    d=tags(JceReader(r['body']).fields());army=tags(d[0])
                    if saw_request or army[0]!=plan['hero_id'] or d[1]!=12 or d[3]!=plan['target_id']:
                        raise RuntimeError('Concurrent/foreign departure; no automatic retry')
                    saw_request=True
                    result['request']={'hero_id':army[0],'aim':d[1],'target_id':d[3],'secondary_target':d.get(4),
                                       'soldiers':[tags(x['value']) for x in army[1]]}
                elif r['tag'].startswith('r_11010_'):
                    if not saw_request:raise RuntimeError('Unattributed departure receipt')
                    d=tags(JceReader(r['body']).fields());receipt={'ret':d[0]}
                    if d[0]==0:
                        a=tags(tags(d[1])[0]);identity=tags(a[15])
                        assert identity[0]==plan['hero_id'] and a[5]==12 and a[6]==plan['target_id']
                        receipt.update(army_id=a[0],hero_id=identity[0],aim=a[5],target_id=a[6],stage=a[4])
                    result['response']=receipt;print('RESPONSE',json.dumps(receipt,ensure_ascii=False),flush=True)
            if 'response' in result:break
            time.sleep(.15)
        if 'response' not in result:raise TimeoutError('Departure outcome unknown; do not retry')
        if result['response']['ret']==0:
            query('return REA_LEAGUE_READONLY.hero_refresh()')
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                s=json.loads(query(f"return REA_LEAGUE_READONLY.league_once_status({plan['hero_id']})"))
                if s['fresh'] and s['army_known'] and s['found']:
                    assert s['army_id']==result['response']['army_id'] and s['aim']==12 and s['target_id']==plan['target_id']
                    result['confirmed']=s;print('CONFIRMED',json.dumps(s,ensure_ascii=False),flush=True);break
                time.sleep(.15)
            else:raise TimeoutError('Server accepted, but own army state not yet confirmed; do not repeat')
    finally:
        evidence_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        try:query('if REA_LEAGUE_READONLY and REA_LEAGUE_READONLY.league_close then REA_LEAGUE_READONLY.league_close() end;REA_LEAGUE_READONLY=nil;return "closed"')
        finally:script.exports_sync.close();script.unload();session.detach()

if __name__=='__main__':main()
