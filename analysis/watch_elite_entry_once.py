"""Observe the single user-authorized UI entry; this watcher never sends a game request."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader


def main():
    """Attribute one newly clicked friend-entry request/reply without selecting a hero or starting battle."""
    log = GameResponseLog(ADB)
    log.drain()
    result = {'observer_sent_requests': 0, 'request': None, 'response': None}
    print('READY: observing new entry only', flush=True)
    deadline = time.monotonic() + 25
    try:
        while time.monotonic() < deadline:
            for record in log.drain():
                tag = record['tag']
                if tag.startswith('s_10001_'):
                    d = tags(JceReader(record['body']).fields())
                    p = tags(d[7]) if isinstance(d.get(7), list) else {}
                    if result['request'] is not None or p.get(1) != 10101 or p.get(2) != 1:
                        raise RuntimeError('Other or duplicate entry observed; do not click again')
                    result['request'] = {'time': record['timestamp'], 'quest_id': p[1], 'match_kind': p[2]}
                elif tag.startswith('r_10001_'):
                    if result['request'] is None:
                        raise RuntimeError('Unattributed entry response; do not click again')
                    d = tags(JceReader(record['body']).fields())
                    result['response'] = {'time': record['timestamp'], 'ret': d.get(0)}
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    return
            time.sleep(.15)
        raise TimeoutError('No attributed entry outcome; do not repeat automatically')
    finally:
        (ROOT / 'analysis/evidence/elite-ui-entry-once.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
