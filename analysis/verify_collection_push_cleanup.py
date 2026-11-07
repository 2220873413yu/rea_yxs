"""Install and immediately remove private observers in one Lua call, without game requests."""
import json
import subprocess
import sys
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB


def main():
    """Verify real model registration and restoration without replacing the running helper API."""
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'], text=True).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT / 'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    try:
        script.load()
        chunk = (ROOT / 'auto_infantry/collection_runtime.lua').read_text(encoding='utf-8')
        source = '''
local manager=CSLTypes.ModelManager.sharedInstance()
local main=manager:getModel(CSLTypes.SLGMainModel)
local trip=manager:getModel(CSLTypes.SLGArmyTripModel)
local scene=CSLTypes.SceneNotifier.getInstance()
local function counts() return main.observers:get_Count()..','..scene.observers:get_Count()..','..trip.observers:get_Count() end
local before=counts()
local original={main.notifyUpdateData,main.notifyStateChange,scene.notifyUpdateData}
local live=assert(REA_AUTO_INFANTRY)
local api={read_hero_state=live.read_hero_state,encode_flat_state=live.encode_flat_state}
local env=setmetatable({REA_AUTO_INFANTRY=api},{__index=_G})
local fn=assert(loadstring(CHUNK))
setfenv(fn,env);fn()
local installed=counts()
local ok,result=pcall(api.collect_push_status)
local scheduleOk,schedule=pcall(api.collect_schedule)
api.collect_close()
assert(counts()==before,'Observer count changed after cleanup')
assert(original[1]==main.notifyUpdateData and original[2]==main.notifyStateChange and original[3]==scene.notifyUpdateData,'Existing helper callbacks changed')
assert(ok,result)
return before..' -> '..installed..' -> '..counts()..' '..result..' schedule_ok='..tostring(scheduleOk)..' '..tostring(schedule)
'''.replace('CHUNK', json.dumps(chunk))
        print(script.exports_sync.query(source))
    finally:
        script.exports_sync.close()
        script.unload()
        session.detach()


if __name__ == '__main__':
    main()
