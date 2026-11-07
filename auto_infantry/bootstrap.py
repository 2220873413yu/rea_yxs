"""Start only the bundled, version-matched local instrumentation service when needed."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADB = r'E:\leidian\LDPlayer9\adb.exe'
SERVER = '/data/local/tmp/rea-frida-server-17.25.2'


def adb(*arguments, timeout=10, check=True):
    """Run one bounded ADB command without creating a console window."""
    return subprocess.run([ADB, '-s', 'emulator-5554', *arguments], capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=timeout,
                          check=check, creationflags=subprocess.CREATE_NO_WINDOW)


def ensure_server():
    """Reuse the known helper or start its pinned binary; never change root or system settings."""
    adb('get-state')
    if adb('shell', 'pidof', 'rea-frida-server-17.25.2', check=False).stdout.strip():
        return
    root = adb('shell', 'su', '-c', 'id')
    if 'uid=0' not in root.stdout:
        raise RuntimeError('模拟器现有 root 不可用，无法连接游戏')
    local = ROOT / '.analysis-tools/frida-server-17.25.2-android-x86_64'
    if adb('shell', 'test', '-f', SERVER, check=False).returncode != 0:
        adb('push', str(local), SERVER, timeout=30)
    adb('shell', f"su -c 'chmod 700 {SERVER}'")
    adb('shell', f"su -c '{SERVER} -l 127.0.0.1:27042 -D > /data/local/tmp/rea-frida-server.log 2>&1 < /dev/null'")
