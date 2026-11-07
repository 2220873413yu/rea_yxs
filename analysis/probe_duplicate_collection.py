"""One authorized duplicate-own-resource experiment; normal helper rules remain intact."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import Connection, ADB
from collection import best_collector, quantity_allowed
from game_log import GameResponseLog, tags
from game_protocol import JceReader
from fourth_collection_probe import PrivateProxy


def ready_hero(metrics, roster):
    """Choose a ready hero for the experiment without consuming any cooldown items."""
    return best_collector({**metrics, 'heroes': [h for h in metrics['heroes'] if h['action_state'] == 0]}, roster)


def receipt(log, hero, target):
    """Match one outgoing request and its response, rejecting ambiguous traffic and never retrying."""
    deadline, sent = time.monotonic() + 8, False
    while time.monotonic() < deadline:
        for r in log.drain():
            if r['tag'].startswith('s_11010_'):
                d = tags(JceReader(r['body']).fields())
                assert not sent and tags(d[0])[0] == hero and d[1] == 1 and d[3] == target, 'Concurrent departure'
                sent = True
            elif r['tag'].startswith('r_11010_'):
                assert sent, 'Unowned response'
                d = tags(JceReader(r['body']).fields())
                result = {'ret': d[0], 'timestamp': r['timestamp'], 'hero_id': hero, 'target_id': target}
                if d[0] == 0:
                    army = tags(tags(d[1])[0])
                    assert tags(army[15])[0] == hero and army[6] == target and army[5] == 1
                    result['army_id'] = army[0]
                return result
        time.sleep(.15)
    raise TimeoutError('Unknown result; do not resend')


def main():
    """Prepare one normal army if needed, wait for its server stage, then test one duplicate request."""
    execute = '--execute' in sys.argv
    evidence = {'execute': execute, 'receipts': []}
    path = ROOT / 'analysis/evidence/duplicate-own-collection-test.json'
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
        text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    try:
        script.exports_sync.query('assert(not REA_FOURTH_PROBE);REA_FOURTH_PROBE={};return "created"')
        for name in ('hero_runtime.lua', 'collection_runtime.lua'):
            chunk = (ROOT / 'auto_infantry' / name).read_text(encoding='utf-8')
            if name == 'collection_runtime.lua':
                old = "assert(not own,'An own army is already collecting at this resource')"
                new = "if api.duplicate_test then assert(own and main.IsSameLeague(point[3]),'Duplicate test needs own same-league resource') else " + old + ' end'
                assert chunk.count(old) == 1
                chunk = chunk.replace(old, new)
                old = "assert(methods('SLGResourceCommonDialog').canCollect(\n  {mTSLGResourceInfoRsp=detail,mTNewPlay_Resource=config})==true,'Native collection rules reject this target')"
                new = '''local checkedDetail=detail
 if api.duplicate_test then
  local ownIds={};local collecting=false
  for i=0,detail[2][2]:get_Count()-1 do
   local a=detail[2][2]:get_Item(i)[1]
   if main.checkIsMyArmy(a) then ownIds[a[1]]=true;if a[4]==6 then collecting=true end end
  end
  assert(collecting,'Own army must already be collecting')
  local copy={};for k,v in pairs(detail) do copy[k]=v end
  local field={};for k,v in pairs(detail[2]) do field[k]=v end
  local p={};for k,v in pairs(point) do p[k]=v end
  local ids=CSLNew(CSLTypes.CSLList)
  for i=0,point[4]:get_Count()-1 do local id=point[4]:get_Item(i);if not ownIds[id] then ids:Add(id) end end
  p[4]=ids;field[1]=p;copy[2]=field;checkedDetail=copy
 end
 assert(methods('SLGResourceCommonDialog').canCollect(
  {mTSLGResourceInfoRsp=checkedDetail,mTNewPlay_Resource=config})==true,'Other native collection rules reject target')'''
                assert chunk.count(old) == 1
                chunk = chunk.replace(old, new)
                chunk = chunk.replace('(action==0 or action==5) and h[6]>0 then', 'action==0 and state.remaining_ms<=0 and h[6]>0 then')
                old = 'package.loaded.SLGMainController.__instanceDict.sendTSLGStartArmyTripReq(req)'
                new = "local stage=api.duplicate_test and 'duplicate' or 'baseline';_G.REA_DUPLICATE_ONCE_20261106=_G.REA_DUPLICATE_ONCE_20261106 or {};assert(not _G.REA_DUPLICATE_ONCE_20261106[stage],'This stage was already sent');_G.REA_DUPLICATE_ONCE_20261106[stage]={hero=heroId,target=target};" + old
                assert chunk.count(old) == 1
                chunk = chunk.replace(old, new)
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_FOURTH_PROBE},{__index=_G});local f=assert(loadstring(' + json.dumps(chunk, ensure_ascii=False) + '));setfenv(f,env);return f()')
        con = Connection()
        con.script = SimpleNamespace(exports_sync=PrivateProxy(script))
        roster = con.refresh_heroes()
        evidence['queue_before'] = {k: v for k, v in roster.items() if k.startswith('queue_')}
        assert roster['queue_known'] and roster['queue_limit'] - roster['queue_used'] >= 2
        saved = {tuple(p) for p in json.loads((ROOT / 'auto_infantry/resource_preferences.json').read_text(encoding='utf-8'))['coordinates']}
        rows = sorted([r for r in con.collection_candidates(0, 0, 0) if (r['x'], r['y']) in saved], key=lambda r: r['distance'])
        plan = None
        for row in rows:
            roster = con.refresh_heroes()
            m = con.query_collection(row['target_id'])
            t = m['target']
            hero = ready_hero(m, roster)
            if (t['rules_known'] and t['queue_free'] and t['capacity'] >= 2 and t['occupants'] < t['capacity'] and
                quantity_allowed(t['level'], t['quantity']) and hero and (t['own_present'] or (t['can_collect'] and t['occupants'] == 0))):
                plan = row
                evidence['plan'] = dict(t, hero_id=hero['hero_id'], hero_name=hero['name'])
                break
        assert plan, 'No qualified saved resource and ready hero'
        print('PLAN', json.dumps(evidence, ensure_ascii=False), flush=True)
        if not execute:
            return
        log = GameResponseLog(ADB)
        # Refresh follower inventory once; actual spending still uses only each selected hero's native species.
        script.exports_sync.query('package.loaded.SLGBuildingsController.__instanceDict._instance:sendTSLGGetBarrackReq();return "barracks requested"')
        if not evidence['plan']['own_present']:
            roster = con.refresh_heroes()
            m = con.query_collection(plan['target_id'])
            hero = ready_hero(m, roster)
            assert hero
            t = m['target']
            args = [t['target_id'], hero['hero_id'], t['kind'], t['level'], t['detail_seq'], t['available_seq'], 0, t['x'], t['y']]
            log.drain()
            epoch = script.exports_sync.setcollectenabled(True)
            try:
                script.exports_sync.query('return REA_FOURTH_PROBE.collect_dispatch(' + ','.join(map(str, args)) + ')', 'collect', hero['hero_id'], epoch)
            finally:
                script.exports_sync.setcollectenabled(False)
            r = receipt(log, hero['hero_id'], t['target_id'])
            evidence['receipts'].append(dict(r, stage='baseline'))
            path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print('BASELINE', json.dumps(r), flush=True)
            assert r['ret'] == 0, 'Baseline rejected; no duplicate sent'
            con.refresh_heroes()
            schedule = con.collection_call('collect_schedule')
            a = next(a for a in schedule['stages'] if a['army_id'] == r['army_id'])
            if a['state'] != 6:
                delay = max(0, (a['end_ms'] - schedule['server_now_ms']) / 1000 + 2)
                assert delay <= 180, 'Travel too long; no duplicate sent'
                print('WAIT_SERVER_STAGE_SECONDS', round(delay, 2), flush=True)
                while delay > 0:
                    pause = min(20, delay)
                    time.sleep(pause)
                    delay -= pause
                    print('WAIT_REMAINING', round(delay, 2), flush=True)
        roster = con.refresh_heroes()
        m = con.query_collection(plan['target_id'])
        t = m['target']
        hero = ready_hero(m, roster)
        assert t['own_present'] and not t['can_collect'] and t['occupants'] < t['capacity'] and t['queue_free'] and hero
        evidence['duplicate_preflight'] = dict(t, hero_id=hero['hero_id'], hero_name=hero['name'])
        args = [t['target_id'], hero['hero_id'], t['kind'], t['level'], t['detail_seq'], t['available_seq'], 0, t['x'], t['y']]
        log.drain()
        epoch = script.exports_sync.setcollectenabled(True)
        try:
            script.exports_sync.query('REA_FOURTH_PROBE.duplicate_test=true;return REA_FOURTH_PROBE.collect_dispatch(' + ','.join(map(str, args)) + ')', 'collect', hero['hero_id'], epoch)
        finally:
            script.exports_sync.setcollectenabled(False)
        r = receipt(log, hero['hero_id'], t['target_id'])
        evidence['receipts'].append(dict(r, stage='duplicate'))
        ret = r['ret']
        evidence['error_description'] = script.exports_sync.query('local r=CSLTypes.DBSearcher.sharedInstance():searchHallError(' + str(ret) + ');local out={};if type(r)=="table" then for k,v in pairs(r) do if type(v)=="string" then out[#out+1]=CSLTypes.YXSUtils.GBK2UTF8(v) end end end;return table.concat(out," | ")')
        after = con.refresh_heroes()
        evidence['queue_after'] = {k: v for k, v in after.items() if k.startswith('queue_')}
        evidence['teams_after'] = con.collection_call('collect_schedule')
        evidence['target_after'] = con.query_collection(plan['target_id'])['target']
        print('RESULT', json.dumps(evidence, ensure_ascii=False), flush=True)
    finally:
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            script.exports_sync.setcollectenabled(False)
            script.exports_sync.query('if REA_FOURTH_PROBE then REA_FOURTH_PROBE.collect_close();REA_FOURTH_PROBE=nil end;return "cleaned"')
        finally:
            script.exports_sync.close()
            script.unload()
            session.detach()


if __name__ == '__main__':
    main()
