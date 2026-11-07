"""Read existing room-entry/progress packets, retaining only quest/match/return-code fields."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records


def main():
    """Audit existing latest-file records without sending game requests or exposing user identity fields."""
    log = GameResponseLog(ADB)
    records = read_records(log.read('exec-out', 'cat', log.path))
    rows = []
    pending = None
    for record in records:
        tag = record['tag']
        if not tag.startswith(('s_10001_', 'r_10001_', 'r_130_', 's_130_')):
            continue
        try:
            data = tags(JceReader(record['body']).fields())
            if tag.startswith('s_10001_'):
                pve = tags(data[7]) if isinstance(data.get(7), list) else {}
                pending = None
                quest = pve.get(1)
                if type(quest) is int and quest >= 10000:
                    pending = {'time': record['timestamp'], 'protocol': 10001, 'direction': 'request',
                               'quest_id': quest, 'match_kind': pve.get(2),
                               'scene_type': data.get(4), 'table_id': data.get(2)}
                    rows.append(pending)
            elif tag.startswith('r_10001_') and pending is not None:
                rows.append({'time': record['timestamp'], 'protocol': 10001, 'direction': 'response',
                             'preceding_quest': pending['quest_id'], 'ret': data.get(0)})
                pending = None
            elif tag.startswith('r_130_'):
                rows.append({'time': record['timestamp'], 'protocol': 130, 'direction': 'response',
                             'ret': data.get(0), 'current_quest': data.get(5), 'next_quest': data.get(6)})
        except (ValueError, TypeError, KeyError):
            rows.append({'time': record['timestamp'], 'protocol': tag.split('_')[1], 'decode': 'unavailable'})
    result = {'source': log.path, 'records': len(records), 'matching': rows[-60:], 'new_requests_sent': 0}
    (ROOT / 'analysis/evidence/elite-existing-entry-log.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
