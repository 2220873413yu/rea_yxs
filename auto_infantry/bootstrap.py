"""Start only the bundled, version-matched local instrumentation service when needed."""
import subprocess
import os
import shlex
import time
from pathlib import Path
import frida
from instance_config import DEVICE, DEVICE_ID, SECONDARY

ROOT = Path(__file__).resolve().parent.parent
FRIDA_VERSION = '17.26.2'
SERVER_NAME = 'rea-frida-server-' + FRIDA_VERSION
SERVER = '/data/local/tmp/' + SERVER_NAME
OLD_SERVER_NAME = 'rea-frida-server-17.25.2'
OLD_SERVER = '/data/local/tmp/' + OLD_SERVER_NAME
LISTEN = '127.0.0.1:27042'


def find_adb(configured=None):
    """Honor an explicit ADB path, otherwise prefer installed LDPlayer14 and retain LDPlayer9 support."""
    configured = configured or os.environ.get('REA_ADB')
    if configured:
        if not Path(configured).is_file():
            raise RuntimeError('REA_ADB 指定的 adb.exe 不存在')
        return configured
    for value in (r'E:\leidian\LDPlayer14\adb.exe', r'E:\leidian\LDPlayer9\adb.exe'):
        if Path(value).is_file():
            return value
    return r'E:\leidian\LDPlayer14\adb.exe'


ADB = find_adb()


def ensure_client_version():
    """Refuse a mixed client/server toolchain before attaching or issuing emulator commands."""
    if frida.__version__ != FRIDA_VERSION:
        raise RuntimeError(f'电脑端 Frida 版本为 {frida.__version__}，需要 {FRIDA_VERSION}；请用助手 Python 环境安装 requirements.txt')


def adb(*arguments, timeout=10, check=True):
    """Run a bounded ADB command against this process's selected emulator."""
    return subprocess.run([ADB, '-s', DEVICE, *arguments], capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=timeout,
                          check=check, creationflags=subprocess.CREATE_NO_WINDOW)


def verify_device():
    """Catch a replaced secondary emulator before attaching or writing account files."""
    if SECONDARY and adb('shell', 'settings', 'get', 'secure', 'android_id').stdout.strip().lower() != DEVICE_ID:
        raise RuntimeError('雷电设备身份已变化，请关闭此标签页后重新选择实例')


def root_command(command, check=True):
    """Quote one fixed Android maintenance command; no game-account values enter shell text."""
    return adb('shell', 'su -c ' + shlex.quote(command), check=check)


def server_pids(name):
    """Read only an exact helper process name and reject malformed identifiers before maintenance."""
    values = adb('shell', 'pidof', name, check=False).stdout.split()
    if any(not value.isdigit() or int(value) <= 1 for value in values):
        raise RuntimeError('Frida 服务进程标识无效，未操作进程')
    return values


def verify_running(pid):
    """Check the actual running image, its version and listening arguments rather than trusting a filename."""
    if root_command('readlink /proc/' + pid + '/exe').stdout.strip() != SERVER:
        raise RuntimeError('Frida 服务进程路径不一致，未连接')
    version = root_command('/proc/' + pid + '/exe --version').stdout.strip()
    if version != FRIDA_VERSION:
        raise RuntimeError(f'模拟器端 Frida 版本为 {version}，需要 {FRIDA_VERSION}')
    arguments = root_command('cat /proc/' + pid + '/cmdline').stdout.split('\x00')
    if '-l' not in arguments or arguments.index('-l') + 1 >= len(arguments) or arguments[arguments.index('-l') + 1] != LISTEN:
        raise RuntimeError('Frida 服务监听地址不是 ' + LISTEN + '，未连接')


def ensure_server():
    """Deploy the pinned service and migrate only our verified old helper; never restart the game or change root."""
    ensure_client_version()
    verify_device()
    adb('get-state')
    root = adb('shell', 'su', '-c', 'id')
    if 'uid=0' not in root.stdout:
        raise RuntimeError('模拟器现有 root 不可用，无法连接游戏')
    running = server_pids(SERVER_NAME)
    if running:
        if len(running) != 1:
            raise RuntimeError('存在多个新版 Frida 服务，请先核对；未连接')
        verify_running(running[0])
        return
    local = ROOT / ('.analysis-tools/frida-server-' + FRIDA_VERSION + '-android-x86_64')
    if root_command('test -f ' + SERVER, check=False).returncode != 0:
        if not local.is_file():
            raise RuntimeError('缺少匹配的 Frida 服务文件：' + str(local))
        adb('push', str(local), SERVER, timeout=30)
    root_command('chmod 700 ' + SERVER)
    if root_command(SERVER + ' --version').stdout.strip() != FRIDA_VERSION:
        raise RuntimeError('待启动的 Frida 服务版本不匹配，原服务未停止')
    # Validate the replacement first. Unknown processes are never killed to free a port.
    for pid in server_pids(OLD_SERVER_NAME):
        if root_command('readlink /proc/' + pid + '/exe').stdout.strip() != OLD_SERVER:
            raise RuntimeError('旧 Frida 服务进程路径不一致，未停止进程')
        root_command('kill -TERM ' + pid)
    deadline = time.monotonic() + 4
    while server_pids(OLD_SERVER_NAME):
        if time.monotonic() >= deadline:
            raise RuntimeError('旧 Frida 服务尚未退出，未启动第二个服务')
        time.sleep(.1)
    root_command(SERVER + ' -l ' + LISTEN + ' -D > /data/local/tmp/rea-frida-server.log 2>&1 < /dev/null')
    deadline = time.monotonic() + 4
    while True:
        running = server_pids(SERVER_NAME)
        if len(running) == 1:
            verify_running(running[0])
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('新版 Frida 服务未正常启动，请核对27042端口占用；未连接游戏')
        time.sleep(.1)
