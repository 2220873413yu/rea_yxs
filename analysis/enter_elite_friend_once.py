"""Invoke the user's authorized native friend-entry callback once; never select, ready or start combat."""
import json
import subprocess
import sys
import time
from pathlib import Path
import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader


def main():
    """Reserve a one-shot marker, invoke the real button callback and attribute exactly one response."""
    log = GameResponseLog(ADB)
    log.drain()
    result = {'attempted': False, 'request': None, 'response': None, 'battle_started': False}
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                      text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    try:
        source = '''
assert(_G.REA_ELITE_FRIEND_ENTRY_NOV6==nil,'Already attempted; do not retry')
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.EliteLevelModel)
local p=m:getProgressMsg()
assert(p and p[1]==0 and p[6]==10101,'Current elite group changed; not entered')
assert(type(package.loaded.EliteLevelScene.__instanceDict.onFriendFightBtnCallBack)=='function','Native entry unavailable')
_G.REA_ELITE_FRIEND_ENTRY_NOV6={attempted=true}
package.loaded.EliteLevelScene.__instanceDict.onFriendFightBtnCallBack({mModel=m})
return 'native_friend_callback_invoked_once'
'''
        epoch = script.exports_sync.setcollectenabled(True)
        result['attempted'] = True
        try:
            result['callback'] = script.exports_sync.query(source, 'collect', 1, epoch)
        finally:
            script.exports_sync.setcollectenabled(False)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            for record in log.drain():
                tag = record['tag']
                if tag.startswith('s_10001_'):
                    d = tags(JceReader(record['body']).fields()); p = tags(d[7])
                    if result['request'] is not None or p.get(1) != 10101 or p.get(2) != 1:
                        raise RuntimeError('Unattributed or duplicate entry; do not retry')
                    result['request'] = {'time': record['timestamp'], 'elite_group_id': p[1], 'match_kind': p[2]}
                elif tag.startswith('r_10001_'):
                    if result['request'] is None:
                        raise RuntimeError('Unattributed response; do not retry')
                    d = tags(JceReader(record['body']).fields())
                    result['response'] = {'time': record['timestamp'], 'ret': d.get(0)}
            if result['response'] is not None:
                result['cached_room'] = json.loads(script.exports_sync.query('''
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.EliteLevelModel)
local p=m:getPveInfo()
return string.format('{"quest_id":%d,"match_kind":%d}',p[2],p[3])
'''))
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return
            time.sleep(.15)
        raise TimeoutError('Entry result unknown; never resubmit automatically')
    finally:
        (ROOT / 'analysis/evidence/elite-native-friend-entry-once.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        script.exports_sync.close()
        script.unload()
        session.detach()


if __name__ == '__main__':
    main()
