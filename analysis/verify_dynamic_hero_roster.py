"""Read the actual dynamic roster in an isolated namespace; never enable a spending gate."""
import json
import subprocess
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Load the roster API privately, query server state, save name/ID evidence, and detach."""
    adb = r'E:\leidian\LDPlayer9\adb.exe'
    pid = int(subprocess.check_output([adb, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'], text=True).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    try:
        source = (ROOT / 'auto_infantry/hero_runtime.lua').read_text(encoding='utf-8')
        installation = ('assert(REA_DYNAMIC_ROSTER_VALIDATION==nil); '
                        'local env=setmetatable({REA_AUTO_INFANTRY={}},{__index=_G}); '
                        'local f=assert(loadstring(' + json.dumps(source, ensure_ascii=False) + ')); '
                        'setfenv(f,env);f();REA_DYNAMIC_ROSTER_VALIDATION=env.REA_AUTO_INFANTRY; '
                        'return REA_DYNAMIC_ROSTER_VALIDATION.hero_list()')
        before = json.loads(script.exports_sync.query(installation))
        start = time.monotonic()
        script.exports_sync.query('return REA_DYNAMIC_ROSTER_VALIDATION.hero_refresh()')
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            roster = json.loads(script.exports_sync.query('return REA_DYNAMIC_ROSTER_VALIDATION.hero_list()'))
            if roster['hero_seq'] > before['hero_seq'] and roster['army_seq'] > before['army_seq']:
                break
            time.sleep(0.15)
        else:
            raise TimeoutError('Fresh roster not observed')
        elapsed = time.monotonic() - start
        ids = [hero['hero_id'] for hero in roster['heroes']]
        assert roster['fresh'] and ids and len(ids) == len(set(ids)), roster
        assert all(hero['name'] and hero['found'] for hero in roster['heroes'])
        assert all(hero.get('confirmed_ms', 0) > 0 and hero.get('activity_label') for hero in roster['heroes'])
        first_view = json.loads(script.exports_sync.query('return REA_DYNAMIC_ROSTER_VALIDATION.hero_view()'))
        unchanged_view = json.loads(script.exports_sync.query('return REA_DYNAMIC_ROSTER_VALIDATION.hero_view()'))
        assert first_view['changed'] and unchanged_view == {'changed': False}
        result = dict(roster=roster, query_seconds=elapsed, recovery_items_before=before['items'],
                      recovery_items_after=roster['items'], spending_sent=False, unchanged_view_suppressed=True)
        (ROOT / 'analysis/evidence/dynamic-hero-roster-validation.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(dict(count=len(ids), query_seconds=round(elapsed, 3),
                             recovery_items_before=before['items'], recovery_items_after=roster['items'],
                             examples=[(hero['hero_id'], hero['name']) for hero in roster['heroes'][:5]],
                             activity_examples=[(hero['name'], hero['activity_label'], hero['confirmed_ms']) for hero in roster['heroes']
                                                if hero['busy'] or hero['hero_state'] != 0],
                             queue={key: roster[key] for key in ('queue_used', 'queue_limit', 'queue_known')},
                             spending_sent=False), ensure_ascii=True))
    finally:
        try:
            script.exports_sync.query('REA_DYNAMIC_ROSTER_VALIDATION=nil;return "removed"')
            script.exports_sync.close()
        finally:
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
