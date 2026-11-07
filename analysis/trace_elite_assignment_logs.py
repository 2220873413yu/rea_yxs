"""Trace known elite quest IDs through the existing entry/push records, excluding player identities."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records


def quest_paths(fields, path='root'):
    """Export only exact known elite IDs and their JCE paths, never other numeric identifiers or strings."""
    rows = []
    for field in fields:
        here = f"{path}.tag{field['tag']}"
        value = field['value']
        if type(value) is int and 10101 <= value <= 10120:
            rows.append({'path': here, 'value': value, 'wire_type': field['wire_type']})
        elif isinstance(value, list):
            rows.extend(quest_paths(value, here))
    return rows


def main():
    """Inspect one actual entry window and compare earlier existing entries without sending requests."""
    log = GameResponseLog(ADB)
    records = read_records(log.read('exec-out', 'cat', log.path))
    rows = []
    entry_history = []
    in_entry = False
    for r in records:
        near = '[2026-11-06 21:59:2' in r['timestamp']
        is_entry = r['tag'].startswith(('s_10001_', 'r_10001_'))
        if not near and not is_entry:
            continue
        try:
            fields = JceReader(r['body']).fields()
            paths = quest_paths(fields)
            if near:
                rows.append({'time': r['timestamp'], 'tag': r['tag'], 'bytes': len(r['body']),
                             'quest_paths': paths,
                             'top_fields': [{'tag': x['tag'], 'wire': x['wire_type']} for x in fields]})
            if is_entry and paths:
                entry_history.append({'time': r['timestamp'], 'tag': r['tag'], 'quest_paths': paths})
        except (ValueError, KeyError, TypeError):
            if near:
                rows.append({'time': r['timestamp'], 'tag': r['tag'], 'decode': 'unavailable'})
    result = {'game_requests_sent': 0, 'entry_window': rows, 'entry_history': entry_history[-40:]}
    (ROOT / 'analysis/evidence/elite-assignment-log-paths.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
