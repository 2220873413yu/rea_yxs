"""Measure existing army status notifications without sending any game requests."""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records


def main():
    """Correlate own-army responses with notification timestamps and print bounded status-only evidence."""
    log = GameResponseLog(ADB)
    records = read_records(log.read('exec-out', 'cat', log.path))
    own = set()
    for record in records:
        if record['tag'].startswith('r_11013_'):
            data = tags(JceReader(record['body']).fields())
            if data.get(0) == 0:
                for entry in data.get(1, []):
                    own.add(tags(entry['value'])[0])
        elif record['tag'].startswith('r_11010_'):
            data = tags(JceReader(record['body']).fields())
            if data.get(0) == 0:
                own.add(tags(tags(data[1])[0])[0])
    all_rows = []
    last = {}
    for record in records:
        if not record['tag'].startswith('r_11011_'):
            continue
        data = tags(JceReader(record['body']).fields())
        army = tags(data[0])
        stamp = record['timestamp'][1:20]
        when = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
        identifier = army[0]
        previous = last.get(identifier)
        row = {'time': stamp, 'army_id': identifier, 'own': identifier in own,
               'state': army.get(4), 'aim': army.get(5), 'command': data.get(1),
               'gap_seconds': (when - previous).total_seconds() if previous else None}
        last[identifier] = when
        all_rows.append(row)
    selected = [row for row in all_rows if row['own']]
    result = {'log_start': records[0]['timestamp'] if records else None,
              'log_end': records[-1]['timestamp'] if records else None,
              'total_pushes': len(all_rows), 'own_pushes': len(selected),
              'own_state_counts': dict(Counter(row['state'] for row in selected)),
              'recent_own': selected[-45:]}
    Path(__file__).with_name('evidence').joinpath('army-push-timing.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
