"""Claim only the user's second completed rescue once; never dispatch or enable recurring collection."""
import json
import subprocess
import sys
import time
from pathlib import Path

import frida

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader
from test_beacon_rescue_once import goods_summary

TARGET=159066
EVIDENCE=ROOT/'analysis/evidence/beacon-rescue-159066-claim-once.json'
SOURCE=r'''
assert(REA_BEACON_CLAIM_TEST==nil,'Claim probe already active')
local api={};REA_BEACON_CLAIM_TEST=api
local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
local bound=main.mTSLGLoginMapRsp;local before
local function check() assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==bound,'Account/world changed') end
function api.query_info()
 check();before=main:getTSLGGetBeaconTowerInfoRsp()
 CSLTypes.SLGMainController.getInstance():sendTSLGGetBeaconTowerInfoReq();return 'query_sent'
end
function api.info()
 check();local r=main:getTSLGGetBeaconTowerInfoRsp()
 if not r or r==before then return '{"ready":false}' end
 assert(r[1]==0,'Beacon query refused')
 local e=main:getTSLGBeaconTowerEventByCommObjID(159066)
 local pos=e and CSLTypes.SLGMapUtils.logicToDisplay(e[1][1])
 local stock=main:getMySLGResource()
 return string.format('{"ready":true,"completed":%d,"found":%s,"state":%d,"config":%d,"x":%d,"y":%d,"food":%.0f,"wood":%.0f,"iron":%.0f}',
  r[3],tostring(e~=nil),e and e[3] or -1,e and e[2] or -1,pos and pos[1] or -1,pos and pos[2] or -1,
  stock[1],stock[2],stock[3])
end
function api.claim_once()
 check();assert(not _G.REA_BEACON_CLAIM_159066_ONCE,'Claim already attempted; never repeat')
 local r=main:getTSLGGetBeaconTowerInfoRsp();assert(r and r~=before and r[1]==0,'Fresh beacon response required')
 local e=assert(main:getTSLGBeaconTowerEventByCommObjID(159066),'Approved rescue absent; nothing claimed')
 local p=CSLTypes.SLGMapUtils.logicToDisplay(e[1][1])
 assert(e[2]==62 and e[3]==3 and p[1]==92 and p[2]==82,'Approved rescue is not ready or identity changed')
 _G.REA_BEACON_CLAIM_159066_ONCE={target_id=159066}
 CSLTypes.SLGMainController.getInstance():sendTSLGGetBeaconTowerEventRewardReq(159066)
 return 'approved_rescue_claim_sent_once'
end
return 'claim_probe_ready'
'''


def main():
    """Check fresh completion, claim one exact event, attribute its receipt and confirm the updated list."""
    if EVIDENCE.exists() and json.loads(EVIDENCE.read_text(encoding='utf-8')).get('attempted'):
        raise RuntimeError('Claim already attempted; inspect evidence instead of resending')
    result=dict(target_id=TARGET,attempted=False,recurring_enabled=False)

    def save():
        """Persist before submission so a transport failure cannot permit accidental duplicate claims."""
        EVIDENCE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

    log=GameResponseLog(ADB)
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],
                                   text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load();created=False

    def info():
        """Send one read request and await its new native response without retransmission."""
        script.exports_sync.query('return REA_BEACON_CLAIM_TEST.query_info()')
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            value=json.loads(script.exports_sync.query('return REA_BEACON_CLAIM_TEST.info()'))
            if value['ready']:
                return value
            time.sleep(.1)
        raise TimeoutError('Fresh beacon confirmation did not arrive; no request repeated')

    try:
        script.exports_sync.query(SOURCE);created=True
        result['before']=info()
        if not (result['before']['found'] and result['before']['state']==3 and result['before']['config']==62):
            raise RuntimeError('Approved rescue is not ready; no claim submitted')
        log.drain();result['attempted']=True;save()
        epoch=script.exports_sync.setcollectenabled(True)
        try:
            result['submitted']=script.exports_sync.query('return REA_BEACON_CLAIM_TEST.claim_once()',
                                                         'collect',1,epoch)
        finally:
            script.exports_sync.setcollectenabled(False)
        sent=False;deadline=time.monotonic()+8
        while time.monotonic()<deadline and 'response' not in result:
            for record in log.drain():
                if record['tag'].startswith('s_11043_'):
                    data=tags(JceReader(record['body']).fields())
                    if sent or data[0]!=TARGET:
                        raise RuntimeError('Concurrent claim traffic; response attribution stopped')
                    sent=True;result['request']=dict(target_id=data[0],time=record['timestamp'])
                elif record['tag'].startswith('r_11043_'):
                    if not sent:
                        raise RuntimeError('Unattributed reward response; never retry')
                    data=tags(JceReader(record['body']).fields())
                    response=dict(ret=data[0],time=record['timestamp'])
                    if data[0]==0:
                        event=tags(data[1]);common=tags(event[0])
                        assert common[1]==TARGET,'Reward response belongs to another event'
                        response.update(event_id=common[1],event_state=event[2],goods=goods_summary(data[2]),level=data.get(3))
                    result['response']=response;save();print('RESPONSE',json.dumps(response,ensure_ascii=False),flush=True)
            if 'response' not in result:
                time.sleep(.15)
        if 'response' not in result:
            raise TimeoutError('Claim outcome unknown; never retry')
        if result['response']['ret']!=0:
            raise RuntimeError('Claim rejected: '+str(result['response']['ret']))
        result['after']=info();save()
        print('AFTER',json.dumps(result['after'],ensure_ascii=False),flush=True)
    except Exception as error:
        result['error']=str(error);save();raise
    finally:
        save()
        try:
            if created:
                script.exports_sync.query('REA_BEACON_CLAIM_TEST=nil;return "probe_removed"')
        finally:
            script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
