"""Inspect existing packet history for training timing and unsolicited barrack responses; never send game actions."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records


def main():
    """Summarize existing training traffic, comparing response times with preceding request records."""
    log = GameResponseLog(ADB)
    records = read_records(log.read('exec-out', 'cat', log.path))
    counts, incoming, request, barracks = Counter(), [], None, []
    outstanding = 0
    for record in records:
        parts = record['tag'].split('_')
        if len(parts) < 3 or parts[1] not in {'11028', '11029', '11030', '11116', '11089'}:
            continue
        kind, protocol = parts[:2]
        counts[kind + '_' + protocol] += 1
        if protocol == '11028':
            if kind == 's':
                outstanding += 1
                request = record['timestamp']
            elif kind == 'r':
                d = tags(JceReader(record['body']).fields())
                row = {'time': record['timestamp'], 'preceding_query': request, 'query_outstanding': outstanding > 0, 'ret': d.get(0), 'units': []}
                outstanding = max(0, outstanding - 1)
                if d.get(0) == 0 and isinstance(d.get(3), list):
                    for pair in d[3]:
                        # JCE dictionary entries retain their key and nested soldier struct.
                        if isinstance(pair, dict):
                            row['units'].append(pair)
                barracks.append(row)
        if kind == 'r' and protocol in {'11029', '11030', '11089', '11116'}:
            incoming.append({'protocol': int(protocol), 'time': record['timestamp']})
    evidence = {'first_record': records[0]['timestamp'] if records else None, 'last_record': records[-1]['timestamp'] if records else None,
                'counts': dict(counts), 'barrack_responses_without_outstanding_query': sum(not r['query_outstanding'] for r in barracks),
                'recent_barracks': barracks[-15:], 'recent_other': incoming[-15:]}
    (ROOT / 'analysis/evidence/training-packet-audit.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in evidence.items() if k != 'recent_barracks'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
