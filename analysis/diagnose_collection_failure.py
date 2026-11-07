"""Read existing trip log records, without sending or retrying a game action."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader, read_records


def main():
    """Print only recent trip payloads and results, excluding unrelated account traffic."""
    log = GameResponseLog(ADB)
    rows = []
    for record in read_records(log.read('exec-out', 'cat', log.path)):
        if record['tag'].startswith(('s_11010_', 'r_11010_')):
            fields = JceReader(record['body']).fields()
            data = tags(fields)
            row = {'time': record['timestamp'], 'tag': record['tag']}
            if record['tag'].startswith('s_'):
                row['request'] = fields
            else:
                row['ret'] = data[0]
            rows.append(row)
    result = rows[-18:]
    Path(__file__).with_name('evidence').joinpath('collection-failed-trip-diagnosis.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{'time': row['time'], 'tag': row['tag'], 'ret': row.get('ret')} for row in result], ensure_ascii=False))
    for record in reversed(read_records(log.read('exec-out', 'cat', log.path))):
        if record['tag'].startswith('r_11012_'):
            data = tags(JceReader(record['body']).fields())
            selected = []
            for entry in data.get(3, []):
                hero = tags(entry['value'])
                identity = tags(tags(hero[0])[0])
                if identity[2] in (242, 305):
                    selected.append(entry)
            availability = {'time': record['timestamp'], 'data': selected}
            Path(__file__).with_name('evidence').joinpath('collection-failed-hero-availability.json').write_text(
                json.dumps(availability, ensure_ascii=False, indent=2), encoding='utf-8')
            for entry in selected:
                hero = tags(entry['value'])
                identity = tags(tags(hero[0])[0])
                print('AVAILABLE ' + json.dumps({'hero_id': identity[2], 'soldiers': hero[1]}, ensure_ascii=False))
            break


if __name__ == '__main__':
    main()
