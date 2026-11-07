"""Read recent train requests/responses without issuing a game action."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from game_log import GameResponseLog, tags
from game_protocol import read_records, JceReader
from connection import ADB
log=GameResponseLog(ADB)
records=read_records(log.read('exec-out','cat',log.path))
rows=[]
for r in records:
    if r['tag'].startswith(('s_11029_','r_11029_')):
        d=tags(JceReader(r['body']).fields())
        rows.append({'time':r['timestamp'],'tag':r['tag'],'ret_or_unit':d.get(0),'response_unit':d.get(1)})
e={'path':log.path,'tail':records[-1]['timestamp'],'training':rows[-24:]}
(ROOT/'analysis/evidence/latest-train-audit.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(e,ensure_ascii=False))
