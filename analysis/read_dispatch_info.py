"""Read one independent dispatch task response; no hero selection, task refresh or reward claim exists here."""
import json
import subprocess
import time
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]
ADB = r'E:\leidian\LDPlayer9\adb.exe'
READ = r'''
local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGDispatchModel)
local r=m.duhufuInfo
if not r then return 'pending' end
local out={'ret='..tostring(r[1]),'task_count='..tostring(m.taskInfo:get_Count())}
for k,v in pairs(r) do if type(k)=='number' and type(v)=='number' then out[#out+1]='INFO '..k..'='..tostring(v) end end
for i=0,m.taskInfo:get_Count()-1 do local t=m.taskInfo:get_Item(i)
 out[#out+1]='TASK '..i
 for k,v in pairs(t) do if type(k)=='number' and type(v)=='number' then out[#out+1]='T '..k..'='..tostring(v) end end
 local ok,c=pcall(function() return CSLTypes.DBSearcher.sharedInstance():GetSLGDuHuFuEvent(t[2]) end)
 if ok and type(c)=='table' then for k,v in pairs(c) do
  if type(k)=='number' and (type(v)=='number' or type(v)=='string') then
   out[#out+1]='C '..k..'='..(type(v)=='string' and CSLTypes.YXSUtils.GBK2UTF8(v) or tostring(v))
  end
 end end
end
return table.concat(out,'\n')
'''


def main():
    """Issue one native GET_INFO request and await only local cache arrival without resending."""
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                     text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    try:
        script.exports_sync.query('local c=CSLTypes.SLGDispatchController.getInstance();'
                                  'c:sendTSLGDuHuFuGetInfoReq();return "info_requested_once"')
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            value = script.exports_sync.query(READ)
            if value != 'pending':
                (ROOT / 'analysis/evidence/dispatch-live-info.txt').write_text(value, encoding='utf-8')
                print(value)
                break
            time.sleep(.1)
        else:
            raise TimeoutError('No dispatch information received; request not repeated')
    finally:
        script.exports_sync.close()
        script.unload()
        session.detach()


if __name__ == '__main__':
    main()
