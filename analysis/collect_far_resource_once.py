"""Dispatch exactly one normal collection to the user-authorized known point, then verify arrival."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import frida

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import Connection,ADB
from collection import best_collector,collection_slot_available,quantity_allowed
from fourth_collection_probe import PrivateProxy


class OnceProxy(PrivateProxy):
    """Allow one guarded collection call; all other calls retain the read-only proxy restriction."""

    def __init__(self,script):
        super().__init__(script)
        self.sent=False

    def query(self,source,spending=False,*args):
        """Reserve a process-global one-shot marker before invoking the unmodified production guard."""
        if spending=='collect':
            assert not self.sent and source.startswith('return REA_AUTO_INFANTRY.collect_dispatch(4472,')
            self.sent=True
            source=source.replace('REA_AUTO_INFANTRY.','REA_FOURTH_PROBE.')
            source="assert(not _G.REA_FAR_TEST_101_134_20261106,'This test was already reserved');_G.REA_FAR_TEST_101_134_20261106=true;"+source
            return self.script.exports_sync.query(source,spending,*args)
        return super().query(source,spending,*args)


def main():
    """Use fresh server eligibility and the current native follower species; never recover or accelerate."""
    evidence={}
    path=ROOT/'analysis/evidence/far-collection-101-134-once.json'
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,
        creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    center='local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMapObjectModel);return tostring(m.screenCenter[1])..","..tostring(m.screenCenter[2])'
    try:
        evidence['center_before']=script.exports_sync.query(center)
        script.exports_sync.query('assert(REA_FOURTH_PROBE==nil);REA_FOURTH_PROBE={};return "created"')
        for name in ('hero_runtime.lua','collection_runtime.lua'):
            chunk=(ROOT/'auto_infantry'/name).read_text(encoding='utf-8')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_FOURTH_PROBE},{__index=_G});local f=assert(loadstring('+json.dumps(chunk,ensure_ascii=False)+'));setfenv(f,env);return f()')
        con=Connection()
        con.script=SimpleNamespace(exports_sync=OnceProxy(script))
        evidence['in_current_resource_cache']=any(r['x']==101 and r['y']==134 for r in con.collection_candidates(0,0,0))
        script.exports_sync.query('package.loaded.SLGBuildingsController.__instanceDict._instance:sendTSLGGetBarrackReq();return "barracks requested"')
        roster=con.refresh_heroes()
        m=con.query_collection(4472)
        t=m['target']
        assert (t['x'],t['y'])==(101,134) and t['queue_free']
        assert collection_slot_available(t) and quantity_allowed(t['level'],t['quantity'])
        hero=best_collector(m,roster)
        assert hero and hero['action_state']==0,'Fastest available hero is not ready; no item will be used'
        evidence['preflight']=dict(t,hero_name=hero['name'],hero_id=hero['hero_id'],travel_seconds=hero['travel_seconds'])
        t['scope_radius']=0
        epoch=script.exports_sync.setcollectenabled(True)
        try:
            receipt,after=con.dispatch_collection(m,hero['hero_id'],epoch)
        finally:
            script.exports_sync.setcollectenabled(False)
        evidence['receipt']=receipt
        evidence['queue_after']={k:v for k,v in after.items() if k.startswith('queue_')}
        schedule=con.collection_call('collect_schedule')
        army=next(r for r in schedule['stages'] if r['army_id']==receipt['army_id'])
        evidence['initial_army']=army
        evidence['center_after_dispatch']=script.exports_sync.query(center)
        path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print('ACCEPTED',json.dumps(evidence,ensure_ascii=False),flush=True)
        if army['state']!=6:
            delay=max(0,(army['end_ms']-schedule['server_now_ms'])/1000+2)
            assert delay<=300,'Departure accepted; longer arrival needs separate observation, never resend'
            while delay>0:
                pause=min(30,delay)
                time.sleep(pause)
                delay-=pause
                print('WAIT_SERVER_ARRIVAL_SECONDS',round(delay,1),flush=True)
        con.refresh_heroes()
        schedule=con.collection_call('collect_schedule')
        evidence['final_army']=next((r for r in schedule['stages'] if r['army_id']==receipt['army_id']),None)
        evidence['target_after']=con.query_collection(4472)['target']
        evidence['collecting_confirmed']=bool(evidence['final_army'] and evidence['final_army']['state']==6 and evidence['target_after']['own_present'])
        evidence['center_after']=script.exports_sync.query(center)
        print('VERIFIED',json.dumps(evidence,ensure_ascii=False),flush=True)
    finally:
        path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            script.exports_sync.setcollectenabled(False)
            script.exports_sync.query('if REA_FOURTH_PROBE then REA_FOURTH_PROBE.collect_close();REA_FOURTH_PROBE=nil end;return "closed"')
        finally:
            script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
