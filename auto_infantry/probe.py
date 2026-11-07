"""Inspect the running game's emulated module realm; never send game commands."""
import json
import subprocess
import threading
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parent
ADB = r'E:\leidian\LDPlayer9\adb.exe'


def main():
    """Attach once with a deadline, report module access, and always detach."""
    result = {'frida_version': frida.__version__, 'realm': 'emulated', 'game_commands_sent': 0}
    session = None
    script = None
    cancelled = frida.Cancellable()
    deadline = threading.Timer(25, cancelled.cancel)
    deadline.daemon = True
    deadline.start()
    try:
        process = subprocess.run([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                 capture_output=True, text=True, check=True, timeout=5)
        pid = int(process.stdout.strip().split()[0])
        result['pid'] = pid
        with cancelled:
            device = frida.get_device_manager().add_remote_device('127.0.0.1:27042')
            session = device.attach(pid, realm='emulated')
            script = session.create_script('''
                rpc.exports = {
                    inspect() {
                        return {
                            arch: Process.arch,
                            modules: Process.enumerateModules()
                                .filter(m => /lib(?:tolua|il2cpp|unity)\\.so$/.test(m.name))
                                .map(m => ({name: m.name, base: m.base.toString(), size: m.size})),
                        };
                    }
                };
            ''')
            script.load()
            result['observation'] = script.exports_sync.inspect()
            result['success'] = (result['observation']['arch'] == 'arm64' and
                                 any(m['name'] == 'libtolua.so' for m in result['observation']['modules']))
    except Exception as error:
        result.update(success=False, error_type=type(error).__name__, error=str(error))
    finally:
        deadline.cancel()
        if script is not None:
            try:
                script.unload()
            except Exception as error:
                result['unload_error'] = str(error)
        if session is not None:
            try:
                session.detach()
            except Exception as error:
                result['detach_error'] = str(error)
        (ROOT / 'probe-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
