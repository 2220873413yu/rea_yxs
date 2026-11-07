"""Validate the new API in an isolated namespace with every spending gate disabled."""
import json
import subprocess
import sys
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from hero_recovery import recovery_decision


def main():
    """Load an isolated API, issue only two state queries, and remove the validation namespace."""
    adb = r'E:\leidian\LDPlayer9\adb.exe'
    pid = int(subprocess.check_output([adb, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'], text=True).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    try:
        source = (ROOT / 'auto_infantry/hero_runtime.lua').read_text(encoding='utf-8')
        installation = ('assert(REA_HERO_VALIDATION==nil); '
                        'local env=setmetatable({REA_AUTO_INFANTRY={}},{__index=_G}); '
                        'local f=assert(loadstring(' + json.dumps(source, ensure_ascii=False) + ')); '
                        'setfenv(f,env);f();REA_HERO_VALIDATION=env.REA_AUTO_INFANTRY; '
                        'return REA_HERO_VALIDATION.hero_status()')
        before = json.loads(script.exports_sync.query(installation))
        script.exports_sync.query('return REA_HERO_VALIDATION.hero_refresh()')
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            after = json.loads(script.exports_sync.query('return REA_HERO_VALIDATION.hero_status()'))
            if after['hero_seq'] > before['hero_seq'] and after['army_seq'] > before['army_seq']:
                break
            time.sleep(0.15)
        else:
            raise TimeoutError('Fresh hero/army response not observed')
        assert after['fresh'] and after['found'], after
        assert before['items'] == after['items'], 'Recovery inventory changed during read-only validation'
        result = dict(before=before, after=after, decision=recovery_decision(after), spending_sent=False)
        output = ROOT / 'analysis/evidence/hero-runtime-validation.json'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        try:
            script.exports_sync.query('REA_HERO_VALIDATION=nil;return "removed"')
            script.exports_sync.close()
        finally:
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
