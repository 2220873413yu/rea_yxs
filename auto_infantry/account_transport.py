"""Bounded, in-memory Android SDK storage transfer; no credential-bearing Windows temporary files."""
import base64
import shlex
import socket
import struct
import subprocess
import time
import xml.etree.ElementTree as ET

from bootstrap import ADB, verify_device
from instance_config import DEVICE
from account_store import AccountError, AUTH_KEYS, MAX_DATABASE, decode_sdk, validate_profile

SDK_DB = '/data/data/com.qqgame.mic/databases/WEGAMEDB2'
SDK_PREF = '/data/data/com.qqgame.mic/shared_prefs/msdk_setting.xml'
GAME_SETTING = '/storage/emulated/0/Android/data/com.qqgame.mic/files/YXS/Setting'
FILES = {SDK_DB, SDK_DB + '-wal', SDK_DB + '-shm', SDK_PREF}


def cancelled(cancel):
    """Cancel between safe transaction phases, never between SDK database and preference commits."""
    if cancel is not None and cancel.is_set():
        raise InterruptedError('账号操作已取消，自动功能保持关闭')


def merge_wal(database, wal):
    """Apply only checksum-valid committed SQLite frames; stale/partial WAL tails are never replayed."""
    if not database.startswith(b'SQLite format 3\0') or len(database) > MAX_DATABASE:
        raise AccountError('SDK数据库格式异常，未保存')
    blob = bytearray(database)
    if wal:
        if len(wal) < 32 or len(wal) > MAX_DATABASE:
            raise AccountError('SDK数据库日志大小异常，未保存')
        magic, _, page = struct.unpack_from('>III', wal)
        if magic not in (0x377F0682, 0x377F0683) or page not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
            raise AccountError('SDK数据库日志格式异常，未保存')
        endian = '<' if magic == 0x377F0682 else '>'

        def checksum(data, seed=(0, 0)):
            """Use SQLite's ordered 32-bit rolling checksum over the header or frame payload."""
            a, b = seed
            for off in range(0, len(data), 8):
                x, y = struct.unpack_from(endian + 'II', data, off)
                a = (a + x + b) & 0xffffffff
                b = (b + y + a) & 0xffffffff
            return a, b

        seed = checksum(wal[:24])
        if seed != struct.unpack_from('>II', wal, 24):
            raise AccountError('SDK数据库日志校验失败，请稍后重新保存')
        frames, committed, pages = [], 0, 0
        for off in range(32, len(wal) - page - 23, page + 24):
            if wal[off + 8:off + 16] != wal[16:24]:
                break
            number, size = struct.unpack_from('>II', wal, off)
            if not 0 < number <= MAX_DATABASE // page or size > MAX_DATABASE // page:
                raise AccountError('SDK数据库日志页数异常')
            data = wal[off + 24:off + 24 + page]
            current = checksum(wal[off:off + 8] + data, seed)
            if current != struct.unpack_from('>II', wal, off + 16):
                break
            seed = current
            frames.append((number, data))
            if size:
                committed, pages = len(frames), size
        for number, data in frames[:committed]:
            if len(blob) < number * page:
                blob.extend(b'\0' * (number * page - len(blob)))
            blob[(number - 1) * page:number * page] = data
        if committed:
            del blob[pages * page:]
    blob[18:20] = b'\x01\x01'
    return bytes(blob)


class AccountTransport:
    """Own fixed SDK paths, local ADB operations and one stopped-process restore transaction."""

    def run(self, command, timeout=15):
        """Never put credential values in command arguments or propagate captured SDK output into errors."""
        try:
            result = subprocess.run([ADB, '-s', DEVICE, 'exec-out', command], capture_output=True,
                                    timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            raise AccountError('模拟器操作超时或连接中断，未自动重试登录') from None
        if result.returncode:
            raise AccountError('模拟器文件操作失败，自动功能保持关闭')
        return result.stdout

    def root(self, command):
        """Quote one Android command once; this interface accepts only program-built fixed-path commands."""
        return self.run('su -c ' + shlex.quote(command))

    def read(self, path, optional=False):
        """Wrap binary SDK reads in base64 because this emulator's su expands binary line endings."""
        if path not in FILES | {GAME_SETTING} | {value + '.rea-ticket-restore' for value in FILES}:
            raise AccountError('拒绝读取非账号恢复文件')
        raw = self.root('base64 ' + shlex.quote(path) + (' 2>/dev/null || true' if optional else ''))
        try:
            data = base64.b64decode(raw)
        except ValueError:
            raise AccountError('模拟器文件读取校验失败') from None
        if len(data) > MAX_DATABASE:
            raise AccountError('模拟器账号文件过大，未读取')
        return data

    def snapshot_database(self):
        """Keep SQLite base, journal and all credential bytes in memory only."""
        return merge_wal(self.read(SDK_DB), self.read(SDK_DB + '-wal', True))

    def pid(self):
        """Read local process readiness only; no game-server request is issued."""
        value = self.run("sh -c 'pidof com.qqgame.mic || true'").strip().decode('ascii')
        return value.split()[0] if value else None

    def startup_auto_paused(self):
        """Read the exact persisted startup flag so a paused login screen need not attach its old Lua realm."""
        setting=self.read(GAME_SETTING, optional=True)
        marker=b'mNoAutoLogin'
        if setting.count(marker)!=1:return False
        index=setting.find(marker)+len(marker)
        return setting[index:index+2]==b'\x10\x01'

    def wait_modules(self, cancel, seconds=100):
        """Wait without Frida during unpacking; require stable game/Lua mappings before a new bridge attaches."""
        deadline, stable_pid, stable_at = time.monotonic() + seconds, None, None
        while time.monotonic() < deadline:
            cancelled(cancel)
            pid = self.pid()
            ready = False
            if pid and pid.isdigit():
                maps = self.root('cat /proc/' + pid + '/maps').decode('utf-8', 'replace')
                ready = 'libtolua.so' in maps and 'libil2cpp.so' in maps
            if ready:
                if pid != stable_pid:
                    stable_pid, stable_at = pid, time.monotonic()
                elif time.monotonic() - stable_at >= 4:
                    return
            else:
                stable_pid, stable_at = None, None
            if cancel is not None:
                cancel.wait(1)
            else:
                time.sleep(1)
        raise AccountError('游戏初始化未完成，请等待登录页出现后重试；尚未发起票据登录')

    def _sync_write(self, path, data):
        """Send bytes from memory over the local ADB sync service, not shell stdin or Windows temp files."""
        verify_device()
        if path != '/data/local/tmp/rea-account-transfer':
            raise AccountError('拒绝写入非账号传输文件')
        try:
            with socket.create_connection(('127.0.0.1', 5037), timeout=10) as stream:
                def receive(size):
                    """Bound each local ADB frame and reject a disconnected sync transport."""
                    chunks = []
                    while size:
                        part = stream.recv(size)
                        if not part:
                            raise OSError()
                        chunks.append(part)
                        size -= len(part)
                    return b''.join(chunks)
                for request in (f'host:transport:{DEVICE}'.encode('ascii'), b'sync:'):
                    stream.sendall(f'{len(request):04x}'.encode() + request)
                    if receive(4) != b'OKAY':
                        raise OSError()
                name = (path + ',33152').encode()
                stream.sendall(b'SEND' + struct.pack('<I', len(name)) + name)
                for off in range(0, len(data), 32768):
                    part = data[off:off + 32768]
                    stream.sendall(b'DATA' + struct.pack('<I', len(part)) + part)
                stream.sendall(b'DONE' + struct.pack('<I', int(time.time())))
                if receive(8)[:4] != b'OKAY':
                    raise OSError()
                stream.sendall(b'QUIT\0\0\0\0')
        except OSError:
            raise AccountError('账号文件传输失败，未发起登录') from None

    def _write(self, path, data):
        """Atomically replace one SDK file, preserving original app ownership; callers must have stopped the game."""
        if path not in FILES:
            raise AccountError('拒绝写入非SDK账号文件')
        metadata = self.root('stat -c %u:%g:%a ' + shlex.quote(path if path in {SDK_DB, SDK_PREF} else SDK_DB)).decode().strip()
        pieces = metadata.split(':')
        if len(pieces) != 3 or not all(part.isdigit() for part in pieces):
            raise AccountError('SDK文件权限无法确认，未替换文件')
        uid, gid, mode = pieces
        transfer, temp = '/data/local/tmp/rea-account-transfer', path + '.rea-ticket-restore'
        try:
            self._sync_write(transfer, data)
            self.root('cp ' + transfer + ' ' + shlex.quote(temp) + ' && chmod 600 ' + shlex.quote(temp))
            if self.read(temp) != data:
                raise AccountError('SDK账号文件回读不一致')
            self.root('chown ' + uid + ':' + gid + ' ' + shlex.quote(temp) + ' && chmod ' + mode + ' ' +
                      shlex.quote(temp) + ' && mv -f ' + shlex.quote(temp) + ' ' + shlex.quote(path))
        finally:
            self.root('rm -f ' + transfer + ' ' + shlex.quote(temp))

    def _remove_journal(self):
        """Remove only this SDK database's obsolete WAL/shared-memory files while its process is absent."""
        self.root('rm -f ' + SDK_DB + '-wal ' + SDK_DB + '-shm')

    def launch(self):
        """Open the installed game on the selected emulator using its launcher activity."""
        verify_device()
        output = self.run('am start -n com.qqgame.mic/com.tencent.gcloud.msdk.core.policy.MSDKPolicyActivity '
                          '-a android.intent.action.MAIN -c android.intent.category.LAUNCHER')
        if any(line.startswith((b'Error:', b'Error type ')) for line in output.splitlines()):
            raise AccountError('雷电未能启动英雄杀，请确认该实例已安装支持的游戏版本')

    def restart(self, cancel, profile=None):
        """Restore both SDK files as one stopped-process transaction; roll back on failure before launching."""
        verify_device()
        data = validate_profile(profile) if profile is not None else None
        cancelled(cancel)
        setting = self.read(GAME_SETTING)
        marker = b'mNoAutoLogin'
        index = setting.find(marker)
        if index < 0 or setting[index + len(marker):index + len(marker) + 2] != b'\x10\x01':
            raise AccountError('启动自动登录暂停设置未保存，未重启游戏')
        self.run('am force-stop com.qqgame.mic')
        deadline = time.monotonic() + 8
        while self.pid():
            if time.monotonic() >= deadline:
                raise AccountError('游戏进程尚未退出，未写入账号文件')
            time.sleep(.2)
        cancelled(cancel)
        if profile is not None:
            before = {path: self.read(path, path not in {SDK_DB, SDK_PREF}) for path in FILES}
            try:
                pref = ET.fromstring(before[SDK_PREF])
                for node in list(pref):
                    if decode_sdk(node.attrib.get('name', '')) in AUTH_KEYS:
                        pref.remove(node)
                for item in profile['auth_preferences']:
                    pref.append(ET.fromstring(item))
                self._write(SDK_DB, data)
                self._remove_journal()
                self._write(SDK_PREF, ET.tostring(pref, encoding='utf-8', xml_declaration=True))
            except Exception:
                try:
                    self._write(SDK_DB, before[SDK_DB])
                    self._remove_journal()
                    for path in (SDK_DB + '-wal', SDK_DB + '-shm'):
                        if before[path]:
                            self._write(path, before[path])
                    self._write(SDK_PREF, before[SDK_PREF])
                except Exception:
                    raise AccountError('账号文件恢复失败且回滚未完成，请勿登录，保留加密备份并联系排查') from None
                raise AccountError('账号文件恢复失败，已回滚原SDK数据；请重新启动游戏') from None
        # Finish the file transaction before observing cancellation; launch paused, never authenticate here.
        self.launch()
        cancelled(cancel)
