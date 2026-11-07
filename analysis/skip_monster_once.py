"""Use the game's normal skip action once for the already-authorized experiment army."""
import json
import subprocess
import sys
import time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog,tags
from game_protocol import JceReader

READ=r'''
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local a=m:getMyArmyInfoByHeroGroupId(427)
local _,ids=debug.getupvalue(package.loaded.SLGMainController.__instanceDict.sendTSLGSitDownClientReq,4)
return string.format('{"found":%s,"army":%d,"stage":%d,"target":%d,"protocol":%d,"monthcard":%s}',tostring(a~=nil),a and a[1] or 0,a and a[4] or 0,a and a[6] or 0,ids.E_SVR_MSG_ID_SLG_SITDOWN,tostring(m:isSLGMonthCardEnabled()))
'''
SEND=r'''
assert(REA_SKIP_99184_ONCE==nil,'Skip already submitted; never retry')
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local a=m:getMyArmyInfoByHeroGroupId(427)
assert(a and a[1]==154777 and a[4]==3 and a[5]==3 and a[6]==152468,'Experiment army is not waiting to enter combat')
assert(m:isSLGMonthCardEnabled(),'Native skip entitlement unavailable')
local _,click=debug.getupvalue(package.loaded.SLGSitdownPromptDialog.__instanceDict.Start,3)
REA_SKIP_99184_ONCE=true
click({mTArmyInfo=a})
return 'native_skip_submitted_once'
'''

def main():
    """Submit exactly one native skip and retain only return codes and experiment army phases."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'));script.load()
    result={}
    try:
        result['before']=json.loads(script.exports_sync.query(READ));print(json.dumps(result['before']),flush=True)
        log=GameResponseLog(ADB)
        epoch=script.exports_sync.setcollectenabled(True)
        try: result['submission']=script.exports_sync.query(SEND,'collect',427,epoch)
        finally: script.exports_sync.setcollectenabled(False)
        deadline=time.monotonic()+8;sent=False
        while time.monotonic()<deadline:
            for r in log.drain():
                p=result['before']['protocol']
                if r['tag'].startswith(f's_{p}_'): sent=True
                elif r['tag'].startswith(f'r_{p}_') and sent:
                    d=tags(JceReader(r['body']).fields());result['ret']=d[0]
            if 'ret' in result: break
            time.sleep(.2)
        result['after']=json.loads(script.exports_sync.query(READ))
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        (ROOT/'analysis/evidence/monster-skip-once.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        script.exports_sync.close();script.unload();session.detach()

if __name__=='__main__':main()
