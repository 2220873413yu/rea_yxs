"""Load private collection observers and perform only read-only target/hero queries."""
import json
import subprocess
import time
import sys
from pathlib import Path
from types import SimpleNamespace

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import Connection, ADB
from game_log import GameResponseLog


class ReadOnlyProxy:
    """Route production read methods into a private API and reject every spending operation."""

    def __init__(self, script):
        self.script = script

    def query(self, source, spending=False, *arguments):
        """Allow only literal read operation calls, with no access to gates or shutdown of the live helper."""
        allowed = ('hero_status', 'hero_list', 'hero_refresh', 'collect_status', 'collect_candidates', 'collect_query', 'collect_metrics')
        assert spending is False and any(source.startswith('return REA_AUTO_INFANTRY.' + name + '(') for name in allowed)
        return self.script.exports_sync.query(source.replace('REA_AUTO_INFANTRY.', 'REA_COLLECT_VERIFY.'), False, *arguments)


def main():
    """Verify native collection response capture, clean up observers, and never enable spending."""
    pid = int(subprocess.check_output([r'E:\leidian\LDPlayer9\adb.exe', '-s', 'emulator-5554',
                                      'shell', 'pidof', 'com.qqgame.mic'], text=True).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    counts_source = ('local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel);'
                     'local s=CSLTypes.SceneNotifier.getInstance();return tostring(m.observers:get_Count())..","..tostring(s.observers:get_Count())')
    before_counts = script.exports_sync.query(counts_source)
    try:
        sources = [(ROOT / 'auto_infantry' / name).read_text(encoding='utf-8')
                   for name in ('hero_runtime.lua', 'collection_runtime.lua')]
        source = 'local env=setmetatable({REA_AUTO_INFANTRY={}},{__index=_G});'
        source += 'REA_COLLECT_VERIFY=env.REA_AUTO_INFANTRY;'
        for chunk in sources:
            source += 'local f=assert(loadstring(' + json.dumps(chunk, ensure_ascii=False) + '));setfenv(f,env);f();'
        source += 'return REA_COLLECT_VERIFY.collect_status()'
        print(script.exports_sync.query(source))
        # Collection needs fresh activity data before considering a hero available.
        script.exports_sync.query('return REA_COLLECT_VERIFY.hero_refresh()')
        script.exports_sync.query('return REA_COLLECT_VERIFY.collect_query(2792)')
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            state = json.loads(script.exports_sync.query('return REA_COLLECT_VERIFY.collect_status()'))
            if state['ready']:
                break
            time.sleep(.15)
        else:
            raise TimeoutError('Native observers did not capture query responses')
        print(json.dumps(state))
        metrics = script.exports_sync.query('return REA_COLLECT_VERIFY.collect_metrics()')
        (ROOT / 'analysis/evidence/collection-native-read-validation.json').write_text(metrics, encoding='utf-8')
        print(metrics[:900])
        connection = Connection()
        connection.script = SimpleNamespace(exports_sync=ReadOnlyProxy(script))
        roster = connection.refresh_heroes()
        log = GameResponseLog(ADB)
        comparisons = []
        for kind in (3, 2, 1):
            rows = connection.collection_candidates(kind, 2, 100)
            assert rows, f'No reference point for{kind}'
            target = min(rows, key=lambda row: (row['distance'], row['target_id']))
            connection.refresh_heroes()
            batch = connection.query_collection(target['target_id'])
            assert batch['target']['fresh'] and batch['target']['kind'] == kind, (kind,batch['target'])
            assert len(batch['heroes']) == len(roster['heroes'])
            comparisons.append(batch)
        (ROOT / 'analysis/evidence/collection-runtime-all-metrics.json').write_text(
            json.dumps(dict(roster=roster, comparisons=comparisons, dispatch_sent=False,
                            production_connection_reads_verified=True), ensure_ascii=False, indent=2), encoding='utf-8')
        dispatch_records = sum(record['tag'].startswith('s_11010_') for record in log.drain())
        print(json.dumps(dict(heroes=len(roster['heroes']), resource_types=len(comparisons), dispatch_sent=False,
                             dispatch_records_seen=dispatch_records, production_connection_reads_verified=True)))
    finally:
        try:
            script.exports_sync.query('if REA_COLLECT_VERIFY then REA_COLLECT_VERIFY.collect_close();'
                                      'REA_COLLECT_VERIFY=nil end;return "cleaned"')
            after_counts = script.exports_sync.query(counts_source)
            assert after_counts == before_counts, (before_counts, after_counts)
            print('Observer cleanup:', before_counts, '->', after_counts)
        finally:
            script.exports_sync.close()
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
