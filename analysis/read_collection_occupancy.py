"""Read native resource occupancy and relationship decisions without dispatch or recovery."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import Connection, ADB
from fourth_collection_probe import PrivateProxy


def main():
    """Capture bounded saved-point queries and native eligibility, then release private observers."""
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
              text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    evidence = []
    try:
        script.exports_sync.query('assert(REA_FOURTH_PROBE==nil,"Private probe exists");REA_FOURTH_PROBE={};return "created"')
        for name in ('hero_runtime.lua', 'collection_runtime.lua'):
            chunk = (ROOT / 'auto_infantry' / name).read_text(encoding='utf-8')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_FOURTH_PROBE},{__index=_G});'
                'local f=assert(loadstring(' + json.dumps(chunk, ensure_ascii=False) + '));setfenv(f,env);return f()')
        con = Connection()
        con.script = SimpleNamespace(exports_sync=PrivateProxy(script))
        con.refresh_heroes()
        rows = con.collection_candidates(0, 0, 0)
        saved = {tuple(p) for p in json.loads((ROOT / 'auto_infantry/resource_preferences.json').read_text(encoding='utf-8'))['coordinates']}
        candidates = [r for r in rows if (r['x'], r['y']) in saved]
        for point in candidates:
            con.refresh_heroes()
            metrics = con.query_collection(point['target_id'])
            details = script.exports_sync.query((ROOT / 'analysis/read_collection_occupancy_detail.lua').read_text(encoding='utf-8'))
            result = {'target': metrics['target'], 'native_detail': json.loads(details)}
            evidence.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        (ROOT / 'analysis/evidence/collection-occupancy-readonly.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            script.exports_sync.query('if REA_FOURTH_PROBE then REA_FOURTH_PROBE.collect_close();REA_FOURTH_PROBE=nil end;return "closed"')
        finally:
            script.exports_sync.close()
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
