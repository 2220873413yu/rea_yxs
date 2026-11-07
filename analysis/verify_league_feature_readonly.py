"""Verify production league reads under a private API with all bridge spending gates left closed."""
import json
import subprocess
import sys
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB, Connection


def main():
    """Install the actual read modules temporarily, take one snapshot and restore all callbacks."""
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                     text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    result = {'spending_enabled': False, 'departure_attempted': False}

    def query(source, spending=False, *_):
        """Select the private API for existing Connection read methods, never a product spending gate."""
        assert spending in (False, None), 'This verifier cannot enable spending'
        return script.exports_sync.query(source.replace('REA_AUTO_INFANTRY.', 'REA_LEAGUE_VERIFY.'))

    connection = Connection()
    # Use real parsing/waiting methods with a private Lua endpoint; no helper ownership is replaced.
    from unittest.mock import Mock
    connection.script = Mock()
    connection.script.exports_sync.query.side_effect = query
    try:
        query('assert(REA_LEAGUE_VERIFY==nil);REA_LEAGUE_VERIFY={};return "created"')
        for name in ('hero_runtime.lua', 'league_runtime.lua'):
            source = (ROOT / 'auto_infantry' / name).read_text(encoding='utf-8')
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_LEAGUE_VERIFY},{__index=_G});'
                                      'local f=assert(loadstring(' + json.dumps(source, ensure_ascii=False) + '));'
                                      'setfenv(f,env);return f()')
        connection.refresh_heroes()
        metrics = connection.query_league()
        connection.refresh_heroes()
        if metrics['mine'] is not None:
            metrics = connection.league_call('league_metrics')
        result['mine'] = metrics['mine']
        result['schedule'] = connection.league_call('league_schedule')
        result['ready_heroes'] = sorted((h for h in metrics['heroes'] if h['ready']),
                                         key=lambda h: (-h['speed'], -h['load'], h['travel_seconds']))[:3]
        before = connection.league_call('league_watch')
        time.sleep(1)
        result['passive_watch'] = {'before': before, 'after': connection.league_call('league_watch')}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        try:
            query('if REA_LEAGUE_VERIFY and REA_LEAGUE_VERIFY.league_close then '
                  'REA_LEAGUE_VERIFY.league_close() end;REA_LEAGUE_VERIFY=nil;return "closed"')
        finally:
            script.exports_sync.close()
            script.unload()
            session.detach()
            (ROOT / 'analysis/evidence/league-feature-readonly.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
