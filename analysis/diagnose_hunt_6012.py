"""Inspect recorded hunt requests and preceding hero candidates without sending game actions."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog,tags
from game_protocol import JceReader,read_records


def main():
    """Keep only aim3 formation fields and the matching hero's cooldown/options/power, excluding user identity."""
    log=GameResponseLog(ADB);rows=[];available={};pending=None
    for r in read_records(log.read('exec-out','cat',log.path)):
        if not r['tag'].startswith(('s_11010_','r_11010_','r_11012_')):continue
        d=tags(JceReader(r['body']).fields())
        if r['tag'].startswith('r_11012_') and d.get(0)==0 and d.get(2)==3:
            available={}
            for entry in d.get(3,[]):
                h=tags(entry['value']);hero=tags(h[0]);identity=tags(hero[0])
                available[identity[2]]={'state':hero.get(1),'cooldown_end':hero.get(2),'base_power':h.get(3),
                                      'per_soldier':h.get(6),'soldiers':[tags(s['value']) for s in h.get(1,[])]}
        elif r['tag'].startswith('s_11010_'):
            pending=None
            if d.get(1)!=3:continue
            army=tags(d[0]);hid=army[0]
            pending={'time':r['timestamp'],'hero':hid,'target':d.get(3),'soldiers':[tags(s['value']) for s in army.get(1,[])],
                     'available':available.get(hid),'position':tags(d[2]) if isinstance(d.get(2),list) else d.get(2)}
        elif r['tag'].startswith('r_11010_') and pending:
            pending['ret']=d[0];rows.append(pending);pending=None
    result=rows[-12:]
    Path(__file__).with_name('evidence').joinpath('hunt-6012-diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
