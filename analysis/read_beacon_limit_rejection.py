"""Read existing11013 army snapshots around a6395 rejection without issuing game requests."""
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB
from game_protocol import JceReader,read_records
from game_log import tags


def main():
    """Retain only event/army phase evidence and the attributed rejected destination, never account credentials."""
    path='/storage/emulated/0/Android/data/com.qqgame.mic/files/YXS/net/2026_11_07/11_22_51'
    data=subprocess.check_output([ADB,'-s','emulator-5554','exec-out','cat',path],
                                 timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    latest_armies=None;latest_request=None;findings=[]
    for record in read_records(data):
        tag=record['tag']
        if not tag.startswith(('r_11013_','s_11010_','r_11010_')):continue
        d=tags(JceReader(record['body']).fields())
        if tag.startswith('r_11013_') and d.get(0)==0:
            rows=[]
            for row in d.get(1,[]):
                a=tags(row['value'])
                if a.get(5)==45:rows.append(dict(army_id=a[0],state=a[4],target=a[6],end_ms=a[11]))
            latest_armies=dict(time=record['timestamp'],rows=rows)
        elif tag.startswith('s_11010_'):
            latest_request=dict(time=record['timestamp'],aim=d[1],target=d[3])
        elif tag.startswith('r_11010_') and d.get(0)==6395:
            findings.append(dict(rejection_time=record['timestamp'],ret=6395,request=latest_request,own_armies=latest_armies))
    result=dict(findings=findings[-3:])
    (ROOT/'analysis/evidence/beacon-6395-army-receipts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
