"""Authorized bounded live test of the production trial service: at most two new battles, no revival/retry."""
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import Connection
from trial_service import TrialService


def main():
    """Return from the already-confirmed win, run two layers through production policy, then revoke the gate."""
    c=Connection();service=None;events=[];last=None;wins=set()
    try:
        c.attach()
        print(c.script.exports_sync.query('''
local mm=CSLTypes.ModelManager.sharedInstance()
local sit=mm:getModel(CSLTypes.SLGMainModel):getTSLGSitDownRsp()
local r=mm:getModel(CSLTypes.PVEModel):getTPushPVEResult()
assert(sit and sit[11][6]==16 and r and r[1]==0 and r[2]==true and r[18]==sit[5]and r[19]==sit[6],'No confirmed trial victory to leave')
assert(not mm:getModel(CSLTypes.GameModel):isInGame(),'Battle still active')
package.loaded.SLGMainController.__instanceDict.backToSLGInResult()
return 'returned_from_previous_confirmed_win_without_share'
'''),flush=True)
        c.close();c=Connection();c.open()

        def publish(**event):
            """Retain only trial actions and short stage messages in the bounded test evidence."""
            events.append(event)
            if 'action' in event or 'trial_status' in event:
                print(json.dumps(event,ensure_ascii=False),flush=True)

        owner=SimpleNamespace(guard=threading.RLock(),closing=threading.Event(),connection=c,publish=publish)
        service=TrialService(owner);service.switch(True)
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            service.tick(c)
            view=service.last_snapshot or {}
            state=(service.phase,view.get('next_quest'),view.get('battle_ready'),view.get('result_seq'))
            if state!=last:
                print(json.dumps(dict(phase=state[0],next_quest=state[1],battle_ready=state[2],result_seq=state[3],result=view.get('result')),ensure_ascii=False),flush=True)
                last=state
            if service.phase=='won':
                wins.add(service.quest)
                if len(wins)>=2:
                    # Leave the second confirmed win normally, then stop before any third challenge is possible.
                    service.local_due=0;service.tick(c)
                    service.switch(False)
                    break
            if not service.enabled:
                break
            time.sleep(.12)
        if service.enabled:
            service.switch(False)
        actions=[e for e in events if 'action' in e]
        result=dict(wins=sorted(wins),challenge_count=sum(e['action']=='trial_challenge'for e in actions),
                    skip_count=sum(e['action']=='trial_skip'for e in actions),actions=actions,
                    success=len(wins)==2 and sum(e['action']=='trial_challenge'for e in actions)==2)
        dest=ROOT/'analysis/evidence/trial-continuity-validation.json'
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if not result['success']:
            raise RuntimeError('Continuous two-layer validation did not complete; no automatic retry')
    finally:
        if service is not None:
            service.switch(False)
        c.close()


if __name__=='__main__':
    main()
