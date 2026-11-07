"""Compare three equal-level resource targets using read-only11020/11012 requests only."""
import json
import re
import subprocess
import time
from pathlib import Path

import frida

from analyze_training_log import read_records, JceReader

ROOT = Path(__file__).resolve().parents[1]
ADB = r'E:\leidian\LDPlayer9\adb.exe'
DEVICE = 'emulator-5554'


def adb_output(*arguments):
    """Read one bounded ADB result without shell expansion or exposing unrelated log contents."""
    return subprocess.check_output([ADB, '-s', DEVICE, *arguments], timeout=10)


def fields_map(fields):
    """Map a decoded JCE struct by numeric tag, retaining nested records for exact field access."""
    return {field['tag']: field['value'] for field in fields}


def record_end(record):
    """Calculate the end of a complete framed log record, excluding any concurrent partial tail."""
    return record['offset'] + 1 + len(record['tag']) + 1 + len(record['timestamp']) + 4 + len(record['body'])


class ResponseLog:
    """Follow only new records, waiting for the requested protocol and resource ID without resubmission."""

    def __init__(self):
        folder = '/storage/emulated/0/Android/data/com.qqgame.mic/files/YXS/net/2026_11_05'
        names = adb_output('shell', 'ls', '-t', folder).decode('ascii').split()
        name = next(value for value in names if re.fullmatch(r'\d{2}_\d{2}_\d{2}', value))
        self.path = folder + '/' + name
        baseline = read_records(adb_output('exec-out', 'cat', self.path))
        self.cursor = record_end(baseline[-1]) if baseline else 4

    def wait(self, protocol, target, timeout=6):
        """Return a matching server response; timeout or rejection never repeats the request."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tail = adb_output('exec-out', 'tail', '-c', '+' + str(self.cursor + 1), self.path)
            records = read_records(bytes.fromhex('0100ffff') + tail)
            if records:
                self.cursor += record_end(records[-1]) - 4
            for record in records:
                if not record['tag'].startswith(f'r_{protocol}_'):
                    continue
                fields = fields_map(JceReader(record['body']).fields())
                if fields[0] != 0:
                    raise RuntimeError(f'Read-only protocol{protocol} rejected: {fields[0]}')
                if protocol == 11012:
                    actual = fields[1]
                else:
                    detail = fields_map(fields[1])
                    point = fields_map(detail[0])
                    common = fields_map(point[0])
                    actual = common[1]
                if actual == target:
                    return record, fields
            time.sleep(0.1)
        raise TimeoutError(f'No matching response for read-only protocol{protocol}, target{target}')


def main():
    """Query target details and hero metrics for iron/wood/grain, never invoking11010 or item use."""
    targets = json.loads((ROOT / 'analysis/evidence/resource-speed-targets.json').read_text(encoding='utf-8'))
    assert len(targets) == 3 and {row['kind'] for row in targets} == {1, 2, 3}
    assert next(row for row in targets if row['kind'] == 3)['id'] == 2792
    pid = int(adb_output('shell', 'pidof', 'com.qqgame.mic').split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    result = []
    sent = set()
    try:
        # Private local environment: the live assistant's API and spending switches are untouched.
        runtime = (ROOT / 'auto_infantry/hero_runtime.lua').read_text(encoding='utf-8')
        source = ('local env=setmetatable({REA_AUTO_INFANTRY={}},{__index=_G});'
                  'local f=assert(loadstring(' + json.dumps(runtime) + '));setfenv(f,env);f();'
                  'return env.REA_AUTO_INFANTRY.hero_list()')
        roster = json.loads(script.exports_sync.query(source))
        names = {hero['hero_id']: hero['name'] for hero in roster['heroes']}
        log = ResponseLog()
        for target in targets:
            target_id = target['id']
            assert type(target_id) is int and target_id > 0
            assert (11020, target_id) not in sent
            sent.add((11020, target_id))
            detail_source = ('local controller=assert(package.loaded.SLGMainController.__instanceDict._instance);'
                             f'controller:sendTSLGResourceInfo({target_id});return "detail_query_sent"')
            script.exports_sync.query(detail_source)
            detail_record, detail = log.wait(11020, target_id)
            point = fields_map(fields_map(detail[1])[0])
            assert point[1] == target['config'], 'Resource configuration changed'
            assert (11012, target_id) not in sent
            sent.add((11012, target_id))
            source = (f'package.loaded.SLGMainController.__instanceDict.sendTSLGGetAvailHeroListReq({target_id},1,0,0);'
                      'return "hero_metrics_query_sent"')
            script.exports_sync.query(source)
            response, payload = log.wait(11012, target_id)
            assert payload[2] == 1, 'Unexpected collection action type'
            heroes = []
            for entry in payload[3]:
                data = fields_map(entry['value'])
                info = fields_map(data[0])
                brief = fields_map(info[0])
                hero_id = brief[2]
                heroes.append(dict(hero_id=hero_id, name=names.get(hero_id, str(hero_id)), level=brief[0],
                                   stars=brief[1], hero_state=info[1], recovery_end_ms=info[2],
                                   cost_seconds=data[2], power=data[3], load=data[4], speed_per_minute=data[5],
                                   special_restriction=data.get(8, 0)))
            result.append(dict(target=target, detail_response=detail_record['tag'], response=response['tag'],
                               timestamp=response['timestamp'], config=point[1], cached_or_reported_quantity=point.get(5),
                               heroes=heroes))
            top = sorted(heroes, key=lambda hero: (-hero['speed_per_minute'], -hero['load'], hero['hero_id']))[:5]
            print(json.dumps(dict(kind=target['kind'], point=[target['x'], target['y']],
                                  hero_count=len(heroes), fastest=top), ensure_ascii=True))
        output = dict(resource_queries_only=True, dispatch_sent=False, queries=sorted(sent), comparisons=result)
        (ROOT / 'analysis/evidence/resource-speed-comparison.json').write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        try:
            script.exports_sync.close()
        finally:
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
