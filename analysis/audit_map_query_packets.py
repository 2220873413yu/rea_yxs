"""Inspect existing map-query packets only; no new request, camera move or cache mutation."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog,tags
from game_protocol import JceReader,read_records
log=GameResponseLog(ADB)
records=read_records(log.read('exec-out','cat',log.path))
queries=[]
target_xy=[int(sys.argv[1]),int(sys.argv[2])] if len(sys.argv)>2 else [96,161]
for r in records:
    if r['tag'].startswith('s_11004_'):
        d=tags(JceReader(r['body']).fields())
        pos=tags(d[0])
        queries.append({'time':r['timestamp'],'center_logic':[pos.get(0),pos.get(1)],'range':[d.get(1),d.get(2)]})
    elif r['tag'].startswith('r_11004_') and queries and 'response_shape' not in queries[-1]:
        fields=JceReader(r['body']).fields()
        queries[-1]['response_shape']=[{'tag':f['tag'],'type':f['wire_type'],'size':len(f['value']) if isinstance(f['value'],list) else None} for f in fields]
        if fields and isinstance(fields[0]['value'],list):
            queries[-1]['view_shape']=[{'tag':f['tag'],'type':f['wire_type'],'size':len(f['value']) if isinstance(f['value'],list) else None} for f in fields[0]['value']]
            resources=[]
            for f in fields[0]['value']:
                if f['wire_type']!=9:
                    continue
                for entry in f['value']:
                    if entry['wire_type']!=10:
                        continue
                    obj=tags(entry['value'])
                    if not isinstance(obj.get(1),int) or not 30001<=obj[1]<=32010 or not isinstance(obj.get(0),list):
                        continue
                    common=tags(obj[0])
                    if not isinstance(common.get(0),list):
                        continue
                    pos=tags(common[0])
                    resources.append({'id':common.get(1),'config':obj[1],'coordinate':[pos.get(0),250-pos[1]],'view_field':f['tag']})
            queries[-1]['resource_count']=len(resources)
            queries[-1]['nearest_to_96_161']=sorted(resources,key=lambda p:abs(p['coordinate'][0]-target_xy[0])+abs(p['coordinate'][1]-target_xy[1]))[:3]
            queries[-1]['target_96_161']=[p for p in resources if p['coordinate']==target_xy]
e={'target_coordinate':target_xy,'query_count':len(queries),'examples':queries[-5:],'target_matches':[q for q in queries if q.get('target_96_161')]}
(ROOT/f'analysis/evidence/map-query-packet-audit-{target_xy[0]}-{target_xy[1]}.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'query_count':len(queries),'recent':[{'center':q['center_logic'],'range':q['range'],'resources':q.get('resource_count'),'target':q.get('target_96_161'),'nearest':q.get('nearest_to_96_161')} for q in queries[-5:]],'target_matches':[{'time':q['time'],'center':q['center_logic'],'target':q['target_96_161']} for q in e['target_matches'][-4:]]},ensure_ascii=False))
