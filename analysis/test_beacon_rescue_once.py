"""Run one authorized rescue, recall after confirmed arrival, and observe return without claiming rewards."""
import json
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import frida

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import Connection, ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader

NAMESPACE='REA_BEACON_RESCUE_TEST'
EVIDENCE=ROOT/'analysis/evidence/beacon-rescue-one-shot.json'


def goods_summary(raw):
    """Keep only reward quantities and item IDs, omitting unrelated player/account fields."""
    goods=tags(raw)
    result={'scalar_nonzero':{str(k):v for k,v in goods.items() if type(v) in (int,float) and v!=0}}
    for key,label in ((5,'items'),(18,'world_resources')):
        if isinstance(goods.get(key),list):
            rows=[]
            for entry in goods[key]:
                if isinstance(entry.get('value'),list):
                    item=tags(entry['value'])
                    if type(item.get(0)) is int and type(item.get(1)) is int:
                        rows.append(dict(id=item[0],count=item[1]))
            result[label]=rows
    return result


class PrivateProxy:
    """Route the connection's read-only hero API to this probe, never the running helper's API."""
    def __init__(self,script):
        self.script=script

    def query(self,source,*args):
        """Replace only the private namespace in already-fixed hero reads."""
        return self.script.exports_sync.query(source.replace('REA_AUTO_INFANTRY',NAMESPACE),*args)


def main():
    """At most one departure and one recall; uncertain outcomes stop without resending either action."""
    global EVIDENCE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',default='20261107')
    parser.add_argument('--target',type=int)
    options=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]{1,50}',options.run_id):
        raise ValueError('Invalid one-shot experiment identifier')
    if options.target is not None and options.target<=0:
        raise ValueError('Invalid target event identifier')
    if options.run_id!='20261107':
        EVIDENCE=EVIDENCE.with_name('beacon-rescue-one-shot-'+options.run_id+'.json')
    if EVIDENCE.exists() and json.loads(EVIDENCE.read_text(encoding='utf-8')).get('departure_attempted'):
        raise RuntimeError('A rescue departure was already attempted; inspect the recorded outcome, do not rerun')
    result=dict(departure_attempted=False,recall_attempted=False,reward_claim_sent=False,states=[],wire_events=[])

    def save():
        """Persist evidence before actions and after every confirmed phase."""
        EVIDENCE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

    # Read the existing log before fresh game snapshots, so slow file parsing cannot expire a plan.
    log=GameResponseLog(ADB)
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],
                                   text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load();created=False
    connection=Connection();connection.script=SimpleNamespace(exports_sync=PrivateProxy(script))

    def query(source):
        """Read or prepare a fixed Lua operation while spending gates remain closed."""
        return script.exports_sync.query(source)

    def call(operation,args=''):
        """Call only this experiment's private functions."""
        return query(f'return {NAMESPACE}.{operation}({args})')

    def wait_json(operation,args='',timeout=7):
        """Await local cache arrival from a single read request, with no network retransmission."""
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=json.loads(call(operation,args))
            if value.get('ready'):
                return value
            time.sleep(.1)
        raise TimeoutError(operation+' did not receive a new response; not repeated')

    def record_wire():
        """Capture only this test's departure/recall/event lifecycle and detect any reward-claim traffic."""
        for record in log.drain():
            tag=record['tag']
            if not any(code in tag for code in ('_11010_','_11008_','_11043_','_11044_')):
                continue
            d=tags(JceReader(record['body']).fields())
            entry=dict(tag=tag,time=record['timestamp'])
            if '_11043_' in tag:
                entry['observed_claim_traffic']=True
                if tag.startswith('s_'):
                    entry['target_id']=d.get(0)
            elif '_11010_' in tag:
                if tag.startswith('s_'):
                    a=tags(d[0]);entry.update(hero_id=a[0],aim=d[1],target_id=d[3])
                    if entry['hero_id']==result.get('plan',{}).get('hero_id') and entry['target_id']==result['plan']['target_id']:
                        result['departure_request']=entry
                else:
                    entry['ret']=d[0]
                    if d[0]==0:
                        a=tags(tags(d[1])[0]);entry.update(army_id=a[0],hero_id=tags(a[15])[0],
                                                       aim=a[5],target_id=a[6],army_state=a[4],end_ms=a[11])
                    if result.get('departure_request') and (d[0]!=0 or
                        (entry.get('hero_id')==result['plan']['hero_id'] and entry.get('target_id')==result['plan']['target_id'])):
                        result['departure_response']=entry
            elif '_11008_' in tag:
                if tag.startswith('s_'):
                    entry['army_id']=d[0]
                    if d[0]==result.get('army_id'):
                        result['recall_request']=entry
                else:
                    entry.update(ret=d[0],army_id=d.get(1))
                    if isinstance(d.get(2),list):
                        entry['goods']=goods_summary(d[2])
                    if entry.get('army_id')==result.get('army_id'):
                        result['recall_response']=entry
            elif '_11044_' in tag:
                e=tags(d[0]);common=tags(e[0]);entry.update(event_id=common[1],event_state=e[2],
                                                          army_id=e.get(3),start_s=e.get(4),end_s=e.get(5))
            result['wire_events'].append(entry)

    def status(label):
        """Read the native event and army, saving only changed phase snapshots."""
        value=json.loads(call('status',f"{result['army_id']},{result['plan']['hero_id']}"))
        value['label']=label
        if not result['states'] or any(value.get(k)!=result['states'][-1].get(k) for k in
            ('event_state','event_army','army_found','army_state','hero_state','hero_busy','event_end_s')):
            result['states'].append(value);save();print('STATE',json.dumps(value,ensure_ascii=False),flush=True)
        return value

    def refresh_info():
        """Make one explicit beacon confirmation query, not a repeating timer."""
        call('info_query');return wait_json('info_result')

    try:
        settings='run_key='+json.dumps(options.run_id)
        if options.target is not None:
            settings+=',required_target='+str(options.target)
        query(f'assert({NAMESPACE}==nil);{NAMESPACE}={{{settings}}};return "created"');created=True
        for path in (ROOT/'auto_infantry/hero_runtime.lua',ROOT/'analysis/beacon_rescue_once.lua'):
            source=path.read_text(encoding='utf-8')
            query('local env=setmetatable({REA_AUTO_INFANTRY='+NAMESPACE+'},{__index=_G});'
                  'local f=assert(loadstring('+json.dumps(source,ensure_ascii=False)+'));setfenv(f,env);return f()')
        result['event_before']=refresh_info()
        connection.refresh_heroes()
        call('candidates_query')
        result['candidate_target']=wait_json('candidates_debug')
        print('CANDIDATE_TARGET',json.dumps(result['candidate_target']),flush=True)
        deadline=time.monotonic()+7
        while True:
            try:
                result['plan']=json.loads(query(f'local r={NAMESPACE}.plan();return {NAMESPACE}.encode_flat_state(r)'))
                break
            except Exception as error:
                if 'Rescue candidates are missing' not in str(error) or time.monotonic()>=deadline:
                    raise
                time.sleep(.1)
        print('PLAN',json.dumps(result['plan'],ensure_ascii=False),flush=True)
        log.drain();result['departure_attempted']=True;save()
        epoch=script.exports_sync.setcollectenabled(True)
        try:
            result['submitted']=json.loads(script.exports_sync.query(
                f"return {NAMESPACE}.send_once({result['plan']['hero_id']},{result['plan']['target_id']})",
                'collect',result['plan']['hero_id'],epoch))
        finally:
            script.exports_sync.setcollectenabled(False)
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and 'departure_response' not in result:
            record_wire();time.sleep(.15)
        response=result.get('departure_response')
        if response is None:
            raise TimeoutError('Departure result unknown; never send again')
        if response['ret']!=0:
            raise RuntimeError('Rescue rejected: '+str(response['ret']))
        assert response['aim']==result['plan']['aim']
        result['army_id']=response['army_id'];save()
        print('DEPARTURE',json.dumps(response,ensure_ascii=False),flush=True)
        connection.refresh_heroes();state=status('departure_confirmed')
        # Observe local pushes until the accepted server arrival deadline; then confirm once if needed.
        delay=max(1,(response['end_ms']-state['server_now_ms'])/1000+1)
        print('WAIT_ARRIVAL_SECONDS',round(delay,1),flush=True)
        deadline=time.monotonic()+delay
        while time.monotonic()<deadline:
            record_wire();state=status('awaiting_arrival')
            if state.get('event_state') in (2,3):
                break
            time.sleep(min(1,max(.01,deadline-time.monotonic())))
        connection.refresh_heroes();refresh_info();state=status('arrival_server_confirmed')
        if state.get('event_state')==2:
            # Refresh immediately before the irreversible action, after the event query is complete.
            connection.refresh_heroes();log.drain();result['recall_attempted']=True;save()
            epoch=script.exports_sync.setcollectenabled(True)
            try:
                result['recall_submitted']=script.exports_sync.query(
                    f"return {NAMESPACE}.recall_once({result['army_id']},{result['plan']['hero_id']})",
                    'collect',result['plan']['hero_id'],epoch)
            finally:
                script.exports_sync.setcollectenabled(False)
            deadline=time.monotonic()+8
            while time.monotonic()<deadline and 'recall_response' not in result:
                record_wire();time.sleep(.15)
            recall=result.get('recall_response')
            if recall is None:
                raise TimeoutError('Recall result unknown; never send again')
            if recall['ret']!=0:
                raise RuntimeError('Recall rejected: '+str(recall['ret']))
            print('RECALL',json.dumps(recall,ensure_ascii=False),flush=True)
        elif state.get('event_state')!=3:
            raise RuntimeError('Rescue arrival not confirmed; no recall sent')
        connection.refresh_heroes();refresh_info();state=status('after_recall')
        delay=max(1,(state.get('army_end_ms',state['server_now_ms'])-state['server_now_ms'])/1000+1)
        print('WAIT_RETURN_SECONDS',round(delay,1),flush=True)
        deadline=time.monotonic()+delay
        while time.monotonic()<deadline:
            record_wire();state=status('awaiting_return')
            if not state['army_found']:
                break
            time.sleep(min(1,max(.01,deadline-time.monotonic())))
        result['roster_final']=connection.refresh_heroes()
        refresh_info();result['final']=status('return_server_confirmed');record_wire();save()
        print('FINAL',json.dumps(result['final'],ensure_ascii=False),flush=True)
    except Exception as error:
        result['error']=str(error);save();raise
    finally:
        save()
        try:
            if created:
                query(f'if {NAMESPACE} and {NAMESPACE}.close then {NAMESPACE}.close() end;{NAMESPACE}=nil;return "closed"')
        finally:
            script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
