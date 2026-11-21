"""Deploy the version-matched emulator service and cache it after explicit download."""
import hashlib
import subprocess
import lzma
import os
import re
import shlex
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import frida
from instance_config import DEVICE, DEVICE_ID, EMULATOR_CONFIG, SECONDARY

ROOT = Path(__file__).resolve().parent.parent
FRIDA_VERSION = '17.26.2'
SERVER_NAME = 'rea-frida-server-' + FRIDA_VERSION
SERVER = '/data/local/tmp/' + SERVER_NAME
OLD_SERVER_NAME = 'rea-frida-server-17.25.2'
OLD_SERVER = '/data/local/tmp/' + OLD_SERVER_NAME
LISTEN = '127.0.0.1:27042'
SERVER_ASSET = f'frida-server-{FRIDA_VERSION}-android-x86_64'
SERVER_URL = f'https://github.com/frida/frida/releases/download/{FRIDA_VERSION}/{SERVER_ASSET}.xz'
SERVER_ARCHIVE_SIZE = 44915484
SERVER_ARCHIVE_SHA256 = '1f03e1bd3800618f6e6b4a978b84a7d093a2bdefd42722eb3f27e4c3bbfd2139'


class FridaServerMissing(RuntimeError):
    """Report that both the selected emulator and the local cache lack the service."""


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


ADB = EMULATOR_CONFIG.get('adb') or os.environ.get('REA_ADB') or find_adb()


def online_devices(adb_path):
    """List online emulator serials using the selected ADB executable."""
    result = subprocess.run([adb_path, 'devices'], capture_output=True, check=True, text=True,
                            encoding='utf-8', errors='replace', timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return sorted({fields[0] for line in result.stdout.splitlines() if len(fields := line.split()) >= 2
                   and fields[1] == 'device' and re.fullmatch(r'emulator-[0-9]{4,5}', fields[0])})


def ensure_client_version():
    """Refuse a mixed client/server toolchain before attaching or issuing emulator commands."""
    if frida.__version__ != FRIDA_VERSION:
        raise RuntimeError(f'电脑端 Frida 版本为 {frida.__version__}，需要 {FRIDA_VERSION}；请用助手 Python 环境安装 requirements.txt')


def adb(*arguments, timeout=10, check=True):
    """Run a bounded ADB command against this process's selected emulator."""
    if not Path(ADB).is_file():
        raise RuntimeError('找不到 adb.exe，请在「雷电设置」选择雷电安装目录里的 adb.exe')
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


def download_server(cancel, progress):
    """Fetch the pinned release, verify it and atomically publish the expanded cache file."""
    local = ROOT / '.analysis-tools' / SERVER_ASSET
    if local.is_file():
        return
    local.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='rea-frida-', dir=local.parent) as directory:
        archive = Path(directory) / (SERVER_ASSET + '.xz')
        unpacked = Path(directory) / SERVER_ASSET
        size = 0
        digest = hashlib.sha256()
        with urlopen(SERVER_URL, timeout=15) as response, archive.open('wb') as destination:
            for chunk in iter(lambda: response.read(256 * 1024), b''):
                if cancel.is_set():
                    raise InterruptedError('Frida 下载已取消')
                size += len(chunk)
                if size > SERVER_ARCHIVE_SIZE:
                    raise RuntimeError('Frida 下载文件大小异常')
                destination.write(chunk)
                digest.update(chunk)
                progress(size * 100 // SERVER_ARCHIVE_SIZE)
        if size != SERVER_ARCHIVE_SIZE or digest.hexdigest() != SERVER_ARCHIVE_SHA256:
            raise RuntimeError('Frida 下载文件 SHA-256 校验失败，请重试')
        if cancel.is_set():
            raise InterruptedError('Frida 下载已取消')
        with lzma.open(archive, 'rb') as source, unpacked.open('wb') as destination:
            shutil.copyfileobj(source, destination)
        if cancel.is_set():
            raise InterruptedError('Frida 下载已取消')
        unpacked.replace(local)


def ensure_server():
    """Deploy the pinned service and migrate only our verified old helper; never restart the game or change root."""
    ensure_client_version()
    verify_device()
    state = adb('get-state', check=False)
    if state.returncode or state.stdout.strip() != 'device':
        raise RuntimeError(f'雷电实例 {DEVICE} 未在线。请先启动模拟器，再到「雷电设置」检查主实例和 ADB 路径')
    root = adb('shell', 'su', '-c', 'id')
    if 'uid=0' not in root.stdout:
        raise RuntimeError('模拟器现有 root 不可用，无法连接游戏')
    running = server_pids(SERVER_NAME)
    if running:
        if len(running) != 1:
            raise RuntimeError('存在多个新版 Frida 服务，请先核对；未连接')
        verify_running(running[0])
        return
    if root_command('test -f ' + SERVER, check=False).returncode != 0:
        local = ROOT / '.analysis-tools' / SERVER_ASSET
        if not local.is_file():
            raise FridaServerMissing('缺少 Frida 服务，请点击「下载 Frida」')
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
