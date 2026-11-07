"""Read the production troop adapter in a private environment without replacing the running helper."""
import json
import subprocess
import sys
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]
ADB = r'E:\leidian\LDPlayer9\adb.exe'


def main():
    """Leave every spending gate closed and export only current barrack upgrade/capacity fields."""
    unit = int(sys.argv[1]) if len(sys.argv) > 1 else 411
    if unit not in (411, 412, 413, 803):
        raise ValueError('Unsupported troop')
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                     text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    try:
        source = (ROOT / 'auto_infantry/runtime.lua').read_text(encoding='utf-8')
        value = script.exports_sync.query('local env=setmetatable({_G={}},{__index=_G});'
            'local f=assert(loadstring(' + json.dumps(source, ensure_ascii=False) + '));setfenv(f,env);f();'
            f'return env._G.REA_AUTO_INFANTRY.status({unit})')
        state = json.loads(value)
        result = {key: state[key] for key in ('soldier_id', 'count', 'deployed', 'limit', 'pending',
                                             'queue_capacity', 'duration_ms', 'remaining_ms', 'upgrade_known', 'upgrading')}
        result['spending_enabled'] = False
        filename = 'scout-training-verified.json' if unit == 803 else 'barrack-upgrade-verified.json'
        (ROOT / 'analysis/evidence' / filename).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        script.exports_sync.close()
        script.unload()
        session.detach()


if __name__ == '__main__':
    main()
