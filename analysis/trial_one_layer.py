"""Explicitly commanded one-layer trial experiment; no background departures, retries, revival or next-floor loop."""
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import Connection
from login_session import account_label

def main():
    """Hold one bridge and accept bounded phase commands, persisting only public trial receipts."""
    c=Connection();record=[]
    try:
        c.attach()
        print(account_label(c.login_call()),flush=True)
        print(c.script.exports_sync.query(Path(__file__).with_suffix('.lua').read_text(encoding='utf-8')),flush=True)
        for line in sys.stdin:
            command=line.strip()
            if command=='close':break
            if command not in {'query_profile','query_available','status','select_three','challenge_once','skip_once'}:
                print('Unsupported command',flush=True);continue
            try:
                value=c.script.exports_sync.query('return REA_TRIAL_ONE_LAYER.'+command+'()')
                if command=='status':
                    value=json.loads(value)
                    for h in value['candidates']+value['selected']:
                        h['name']=bytes.fromhex(h.pop('name_hex')).decode('utf-8')
                print(json.dumps({'command':command,'result':value},ensure_ascii=False),flush=True)
                record.append(dict(at=time.time(),command=command,result=value))
                (Path(__file__).parent/'evidence/trial-one-layer-public.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception:
                print('COMMAND_FAILED_OR_UNCERTAIN; no automatic retry',flush=True)
                raise
    finally:
        if c.script:
            try: print(c.script.exports_sync.query("return REA_TRIAL_ONE_LAYER and REA_TRIAL_ONE_LAYER.close() or 'not_installed'"),flush=True)
            except Exception: pass
        c.close()

if __name__=='__main__':main()
