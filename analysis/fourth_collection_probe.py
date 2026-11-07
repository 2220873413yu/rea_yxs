"""Inspect saved collection targets; optionally issue one explicitly bounded fourth-team test."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import Connection, ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader
from collection import best_collector, quantity_allowed


class PrivateProxy:
    """Route read operations to the temporary namespace without touching the live helper."""
    def __init__(self, script):
        self.script = script

    def query(self, source, spending=False, *args):
        """Reject mutation calls through the production connection adapter."""
        assert spending is False
        assert any(source.startswith('return REA_AUTO_INFANTRY.' + name + '(') for name in
                   ('hero_list', 'hero_refresh', 'collect_status', 'collect_query', 'collect_metrics', 'collect_candidates', 'collect_schedule'))
        return self.script.exports_sync.query(source.replace('REA_AUTO_INFANTRY.', 'REA_FOURTH_PROBE.'), False, *args)


def main():
    """Inspect targets with all spending gates off and always restore temporary observers."""
    send = '--send-fourth-once' in sys.argv
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
              text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    evidence = {'send_authorized_mode': send, 'targets': []}
    try:
        script.exports_sync.query('assert(REA_FOURTH_PROBE==nil,"Probe already installed");'
                                  'REA_FOURTH_PROBE={};return "reserved namespace"')
        for name in ('hero_runtime.lua', 'collection_runtime.lua'):
            chunk = (ROOT / 'auto_infantry' / name).read_text(encoding='utf-8')
            if name == 'collection_runtime.lua':
                old = "assert(main:checkMaxCollectionArmyCount()~=true,'Collection queue limit reached')"
                new = "local q=api.read_collection_queue(raw);assert(q.queue_known and q.queue_used==3 and q.queue_limit==3,'Fourth test requires exactly 3/3');assert(not _G.REA_FOURTH_TEST_SENT_20261106,'Fourth test already reserved')"
                assert chunk.count(old) == 1
                chunk = chunk.replace(old, new)
                old = 'package.loaded.SLGMainController.__instanceDict.sendTSLGStartArmyTripReq(req)'
                assert chunk.count(old) == 1
                chunk = chunk.replace(old, '_G.REA_FOURTH_TEST_SENT_20261106={hero_id=heroId,target_id=target};' + old)
            source = 'local env=setmetatable({REA_AUTO_INFANTRY=REA_FOURTH_PROBE},{__index=_G});local f=assert(loadstring(' + json.dumps(chunk, ensure_ascii=False) + '));setfenv(f,env);return f()'
            script.exports_sync.query(source)
        con = Connection()
        con.script = SimpleNamespace(exports_sync=PrivateProxy(script))
        roster = con.refresh_heroes()
        evidence['queue_before'] = {k: roster[k] for k in ('queue_used', 'queue_limit', 'queue_known')}
        evidence['teams_before'] = con.collection_call('collect_schedule')
        if send:
            assert evidence['queue_before'] == {'queue_used': 3, 'queue_limit': 3, 'queue_known': True}, 'Wait until three teams are confirmed before the one-shot test'
        rows = con.collection_candidates(0, 0, 0)
        saved = {tuple(p) for p in json.loads((ROOT / 'auto_infantry/resource_preferences.json').read_text(encoding='utf-8'))['coordinates']}
        print('QUEUE', json.dumps(evidence['queue_before']), flush=True)
        candidates = sorted((r for r in rows if (r['x'], r['y']) in saved), key=lambda r: r['distance'])
        evidence['unloaded'] = sorted(saved - {(r['x'], r['y']) for r in candidates})
        for point in candidates:
            roster = con.refresh_heroes()
            metrics = con.query_collection(point['target_id'])
            hero = best_collector(metrics, roster)
            result = dict(metrics['target'], distance=point['distance'], best=hero)
            evidence['targets'].append(result)
            print('TARGET', json.dumps(result, ensure_ascii=False), flush=True)
            if send and result['can_collect'] and result['occupants'] == 0 and quantity_allowed(result['level'], result['quantity']) and hero and hero['action_state'] == 0:
                assert evidence['queue_before'] == {'queue_used': 3, 'queue_limit': 3, 'queue_known': True}
                log = GameResponseLog(ADB)
                # Log preparation may take time: reacquire all query objects immediately before sending.
                roster = con.refresh_heroes()
                metrics = con.query_collection(point['target_id'])
                hero = best_collector(metrics, roster)
                t = metrics['target']
                assert hero and hero['action_state'] == 0
                args = [t['target_id'], hero['hero_id'], t['kind'], t['level'], t['detail_seq'], t['available_seq'], 0, t['x'], t['y']]
                log.drain()
                epoch = script.exports_sync.setcollectenabled(True)
                try:
                    evidence['send_result'] = script.exports_sync.query('return REA_FOURTH_PROBE.collect_dispatch(' + ','.join(map(str, args)) + ')', 'collect', hero['hero_id'], epoch)
                finally:
                    script.exports_sync.setcollectenabled(False)
                sent = False
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and 'response' not in evidence:
                    for record in log.drain():
                        if record['tag'].startswith('s_11010_'):
                            data = tags(JceReader(record['body']).fields())
                            assert not sent and tags(data[0])[0] == hero['hero_id'] and data[1] == 1 and data[3] == t['target_id'], 'Concurrent departure prevents response attribution'
                            sent = True
                            evidence['request'] = {'hero_id': hero['hero_id'], 'target_id': t['target_id'], 'x': t['x'], 'y': t['y']}
                        elif record['tag'].startswith('r_11010_'):
                            assert sent, 'Unowned response'
                            data = tags(JceReader(record['body']).fields())
                            evidence['response'] = {'ret': data[0], 'timestamp': record['timestamp']}
                            ret = data[0]
                            assert type(ret) is int
                            evidence['response']['native_error'] = script.exports_sync.query(
                                'local r=CSLTypes.DBSearcher.sharedInstance():searchHallError(' + str(ret) + ');'
                                'local out={};if type(r)=="table" then for k,v in pairs(r) do if type(v)=="string" then '
                                'out[#out+1]=tostring(k).."="..CSLTypes.YXSUtils.GBK2UTF8(v) end end end;return table.concat(out," | ")')
                    if 'response' not in evidence:
                        time.sleep(.15)
                evidence['after'] = {k: v for k, v in con.refresh_heroes().items() if k.startswith('queue_')}
                evidence['teams_after'] = con.collection_call('collect_schedule')
                print('RESULT', json.dumps({k: v for k, v in evidence.items() if k != 'targets'}, ensure_ascii=False), flush=True)
                break
        print('UNLOADED', evidence['unloaded'], flush=True)
    finally:
        (ROOT / 'analysis/evidence/fourth-collection-probe.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            script.exports_sync.setcollectenabled(False)
            script.exports_sync.query('if REA_FOURTH_PROBE then REA_FOURTH_PROBE.collect_close();REA_FOURTH_PROBE=nil end;return "cleaned"')
        finally:
            script.exports_sync.close()
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
