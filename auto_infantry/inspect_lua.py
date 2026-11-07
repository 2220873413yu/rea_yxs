"""Execute a caller-selected inspection chunk on the game's Lua update thread."""
import json
import subprocess
import sys
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parent
ADB = r'E:\leidian\LDPlayer9\adb.exe'


def main():
    """Load the temporary bridge, run one supplied chunk, then unload and detach."""
    source = Path(sys.argv[1]).read_text(encoding='utf-8')
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
                                     text=True, timeout=5).strip().split()[0])
    device = frida.get_device_manager().add_remote_device('127.0.0.1:27042')
    session = device.attach(pid, realm='emulated')
    script = None
    try:
        script = session.create_script((ROOT / 'bridge.js').read_text(encoding='utf-8'))
        script.on('message', lambda message, data: print(json.dumps(message), file=sys.stderr))
        script.load()
        result = script.exports_sync.query(source)
        print(result)
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(result, encoding='utf-8')
    finally:
        if script is not None:
            try:
                script.exports_sync.close()
            finally:
                script.unload()
        session.detach()


if __name__ == '__main__':
    main()
