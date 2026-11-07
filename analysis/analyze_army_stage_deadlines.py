"""Correlate existing server army deadlines with later state transitions; no game requests."""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records

TZ = timezone(timedelta(hours=8))


def time_string(milliseconds):
    """Format protocol epoch milliseconds in the user's Asia/Shanghai timezone."""
    return datetime.fromtimestamp(milliseconds / 1000, TZ).isoformat(timespec='milliseconds') if milliseconds else None


def main():
    """Print only stage/army/time data, keeping player identity and unrelated payloads out of evidence."""
    log = GameResponseLog(ADB)
    records = read_records(log.read('exec-out', 'cat', log.path))
    selected = {150554, 150766, 150903, 150906, 150926, 151052, 151106, 151109}
    transitions = []
    snapshots = {}
    for record in records:
        if not record['tag'].startswith(('r_11011_', 'r_11013_', 'r_11010_')):
            continue
        data = tags(JceReader(record['body']).fields())
        if record['tag'].startswith('r_11011_'):
            armies = [tags(data[0])]
        elif data.get(0) != 0:
            continue
        elif record['tag'].startswith('r_11013_'):
            armies = [tags(entry['value']) for entry in data.get(1, [])]
        else:
            armies = [tags(tags(data[1])[0])]
        for army in armies:
            identifier = army[0]
            if identifier not in selected:
                continue
            deadline = army.get(11, 0)
            row = {'received': record['timestamp'][1:20], 'army_id': identifier,
                   'protocol': record['tag'].split('_')[1], 'state': army.get(4), 'aim': army.get(5),
                   'deadline_ms': deadline, 'deadline_local': time_string(deadline)}
            if record['tag'].startswith('r_11011_'):
                transitions.append(row)
            snapshots[(identifier, army.get(4))] = row
    result = {'transitions': transitions, 'latest_per_stage': list(snapshots.values())}
    Path(__file__).with_name('evidence').joinpath('army-stage-deadlines.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
