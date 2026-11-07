"""Summarize existing beacon notifications from the current local game log, without game requests."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records
from connection import ADB


def event_summary(raw, timestamp):
    """Extract event lifecycle fields only, excluding all player identity and login information."""
    e=tags(raw)
    common=tags(e[0])
    return dict(time=timestamp,event_id=common[1],object_type=common[2],config=e[1],
                state=e[2],army=e.get(3,0),start=e.get(4,0),end=e.get(5,0))


def main():
    """Read the already-created current log once more and retain only beacon lifecycle evidence."""
    log=GameResponseLog(ADB)
    data=log.read('exec-out','cat',log.path)
    notifications=[];info=[];claims=0;malformed=0
    for record in read_records(data):
        tag=record['tag']
        if not any(code in tag for code in ('_11042_','_11043_','_11044_')) or tag.startswith('s_'):
            continue
        try:
            fields=tags(JceReader(record['body']).fields())
            if '_11044_' in tag:
                notifications.append(event_summary(fields[0],record['timestamp']))
            elif '_11042_' in tag and fields[0]==0:
                info.extend(event_summary(row['value'],record['timestamp']) for row in fields[3])
            elif '_11043_' in tag and fields[0]==0:
                claims+=1
        except (ValueError,KeyError,TypeError):
            malformed+=1
    result=dict(existing_log_bytes=len(data),notification_count=len(notifications),
                states=sorted({r['state'] for r in notifications+info}),
                existing_successful_claims=claims,decode_errors=malformed,
                nonzero_examples=[r for r in notifications+info if r['state']!=0][-12:])
    (ROOT/'analysis/evidence/beacon-existing-receipts-readonly.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
