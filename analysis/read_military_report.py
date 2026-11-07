"""Read-only native report research; detach this probe without changing the running helper's globals."""
import subprocess
import sys
from pathlib import Path
import frida

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from account_lock import ensure_account_available
from connection import ADB


def main():
    """Run an explicitly supplied local inspection chunk with all action gates closed and no account rebinding."""
    ensure_account_available()
    subprocess.run([ADB,'-s','emulator-5554','forward','tcp:27042','tcp:27042'],capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    pid=int(subprocess.check_output([ADB,'-s','emulator-5554','shell','pidof','com.qqgame.mic'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=None
    try:
        script=session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'));script.load()
        value=script.exports_sync.query(Path(sys.argv[1]).read_text(encoding='utf-8'))
        if len(sys.argv)>2:
            Path(sys.argv[2]).write_text(value,encoding='utf-8')
        else:
            print(value)
    finally:
        if script is not None:
            script.exports_sync.close();script.unload()
        session.detach()


if __name__=='__main__':
    main()
