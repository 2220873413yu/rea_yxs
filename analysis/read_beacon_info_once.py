"""Read one fresh beacon-information response; never scout, start a trip or claim a reward."""
import subprocess
import time
from pathlib import Path

import frida

ROOT=Path(__file__).resolve().parents[1]
ADB=r'E:\leidian\LDPlayer9\adb.exe'
SOURCE=r'''
assert(REA_BEACON_INFO_READONLY==nil,'Read-only probe already exists')
local mm=CSLTypes.ModelManager.sharedInstance();local main=mm:getModel(CSLTypes.SLGMainModel)
local bound=main.mTSLGLoginMapRsp;local previous=main:getTSLGGetBeaconTowerInfoRsp()
local s=CSLTypes.DBSearcher.sharedInstance()
REA_BEACON_INFO_READONLY=function()
 assert(main.mIsMapLoaded and main.mTSLGLoginMapRsp==bound,'World changed during read-only query')
 local r=main:getTSLGGetBeaconTowerInfoRsp();if not r or r==previous then return 'pending' end
 assert(r[1]==0,'Beacon information query failed: '..tostring(r[1]))
 local out={string.format('FRESH ret=%d level=%d completed=%d refresh_remaining_seconds=%s max_queue=%d native_full=%s',
  r[1],r[2],r[3],tostring(r[5]),r[6],tostring(main:checkMaxFengHuoTaiArmyCount())),
  'observed_server_seconds='..tostring(CSLTypes.RefreshTimer.getServerTimeNow())}
 for i=0,r[4]:get_Count()-1 do local e=r[4]:get_Item(i);local c=s:searchTMapIntelStation_Event_Map(e[2])
  local pos=CSLTypes.SLGMapUtils.logicToDisplay(e[1][1])
  out[#out+1]=string.format('event=%d config=%d kind=%d object_type=%d state=%d army=%s start=%s end=%s xy=%d,%d',
   e[1][2],e[2],c[2],e[1][3],e[3],tostring(e[4]),tostring(e[5]),tostring(e[6]),pos[1],pos[2])
 end
 return table.concat(out,'\n')
end
CSLTypes.SLGMainController.getInstance():sendTSLGGetBeaconTowerInfoReq()
return 'one_readonly_info_query_sent'
'''


def main():
    """Send11042 once and wait for a distinct successful cache response, keeping all action gates closed."""
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],
                                   text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load();created=False
    try:
        script.exports_sync.query(SOURCE);created=True
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            value=script.exports_sync.query('return REA_BEACON_INFO_READONLY()')
            if value!='pending':
                (ROOT/'analysis/evidence/beacon-fresh-info-readonly.txt').write_text(value,encoding='utf-8')
                print(value);return
            time.sleep(.1)
        raise TimeoutError('Beacon information response timeout; no request repeated')
    finally:
        if created:
            script.exports_sync.query('REA_BEACON_INFO_READONLY=nil;return "probe_removed"')
        script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
