"""Resolve one known coordinate against fresh server details without moving the map or dispatching."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import frida

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import Connection,ADB
from collection import best_collector,collection_slot_available,quantity_allowed
from fourth_collection_probe import PrivateProxy


def main():
    """Query the requested resource ID once and restore temporary response observers afterward."""
    target,x,y=map(int,sys.argv[1:4])
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,
        creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    result={}
    center='local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMapObjectModel);return tostring(m.screenCenter[1])..","..tostring(m.screenCenter[2])'
    try:
        result['center_before']=script.exports_sync.query(center)
        script.exports_sync.query('assert(REA_FOURTH_PROBE==nil);REA_FOURTH_PROBE={};return "created"')
        for name in ('hero_runtime.lua','collection_runtime.lua'):
            chunk=(ROOT/'auto_infantry'/name).read_text(encoding='utf-8')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_FOURTH_PROBE},{__index=_G});local f=assert(loadstring('+json.dumps(chunk,ensure_ascii=False)+'));setfenv(f,env);return f()')
        con=Connection()
        con.script=SimpleNamespace(exports_sync=PrivateProxy(script))
        result['in_current_resource_cache']=any(r['x']==x and r['y']==y for r in con.collection_candidates(0,0,0))
        roster=con.refresh_heroes()
        metrics=con.query_collection(target)
        state=metrics['target']
        assert (state['x'],state['y'])==(x,y),'Resource ID no longer matches requested coordinate'
        result['target']=state
        result['resource_rules_allow']=collection_slot_available(state) and quantity_allowed(state['level'],state['quantity'])
        result['best_hero']=best_collector(metrics,roster)
        result['native_facts']=json.loads(script.exports_sync.query('''
local a=REA_FOURTH_PROBE;local detail
for i=1,30 do local n,v=debug.getupvalue(a.collect_status,i);if n=='detail' then detail=v;break end end
local p=detail[2][1];local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local config=CSLTypes.DBSearcher.sharedInstance():searchTNewPlay_Resource_Map(p[2])
local d=package.loaded.SLGResourceCommonDialog.__instanceDict
local ctx={mTSLGResourceInfoRsp=detail,mTNewPlay_Resource=config}
return a.encode_flat_state({visible=d.isVisible(ctx),other_region=d.isInOtherRegion(ctx),
 same_league=main.IsSameLeague(p[3]),allied_league=main.IsAllyLeague(p[3]),enemy_resource=main.isEnemyResourceField(p)})
'''))
        result['center_after']=script.exports_sync.query(center)
        result['dispatch_sent']=False
        (ROOT/f'analysis/evidence/collection-target-{x}-{y}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    finally:
        try:
            script.exports_sync.query('if REA_FOURTH_PROBE then REA_FOURTH_PROBE.collect_close();REA_FOURTH_PROBE=nil end;return "closed"')
        finally:
            script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
