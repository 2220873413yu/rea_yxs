"""Capture one verified role or restore one encrypted SDK profile through the tested restart workflow."""
import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import xml.etree.ElementTree as ET
import frida

from connection import Connection
from account_store import AccountError, TicketExpired, AUTH_KEYS, decode_sdk, validate_profile
from account_transport import AccountTransport, SDK_PREF, cancelled
from account_lock import account_operation, acquire_role, release_role

SOURCE = (Path(__file__).with_name('account_auth_guard.lua').read_text(encoding='utf-8') + '\n' +
          Path(__file__).with_name('account_runtime.lua').read_text(encoding='utf-8'))


class AccountService:
    """Keep every credential-bearing value private to this serial service and its encrypted store."""

    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport or AccountTransport()
        self.paused_auto = None

    @staticmethod
    def call(connection, operation, mobile=0, open_platform=0, resume_auto=0):
        """Submit only fixed operations and integer platform enums; no UI-supplied Lua or token interpolation."""
        if operation not in {'ready', 'pause', 'identity', 'watch', 'restore', 'qr', 'cancel_auth', 'resume', 'auth_cleanup'}:
            raise AccountError('未知账号操作')
        if any(type(v) is not int or v not in (0, 1) for v in (mobile, open_platform, resume_auto)):
            raise AccountError('登录平台参数无效')
        source = f'local operation={json.dumps(operation)};local mobile={mobile};local open_platform={open_platform};local resume_auto={resume_auto}\n' + SOURCE
        with connection.lock:
            value = connection.script.exports_sync.query(source)
        return json.loads(value) if operation in {'identity', 'watch'} else value

    @contextmanager
    def connection(self, cancel):
        """Retry only local bridge startup before yielding; never replay an authentication after the caller starts."""
        self.transport.wait_modules(cancel)
        connection = Connection()
        try:
            deadline, attached = time.monotonic() + 90, False
            while True:
                cancelled(cancel)
                try:
                    if not attached:
                        connection.attach()
                        attached = True
                    if self.call(connection, 'ready') == 'ready':
                        break
                except (frida.RPCException, frida.InvalidOperationError):
                    # Emulator modules can be mapped before this Frida realm or the Lua update loop is usable.
                    connection.close()
                    connection, attached = Connection(), False
                if time.monotonic() >= deadline:
                    raise AccountError('游戏登录模块尚未就绪，请等待登录页加载完成后重试')
                cancel.wait(1)
            yield connection
        except (AccountError, InterruptedError):
            raise
        except Exception:
            # Frida and SDK errors may contain internal values; never forward arbitrary exception text.
            raise AccountError('账号连接未完成，请确认游戏已加载；未自动重试认证') from None
        finally:
            connection.close()

    def identity(self, connection):
        """Decode private SDK identity in memory; callers must never publish or log this result."""
        value = self.call(connection, 'identity')
        try:
            value['openid'] = bytes.fromhex(value.pop('openid_hex')).decode('utf-8')
            value['token'] = bytes.fromhex(value.pop('access_token_hex'))
        except (ValueError, UnicodeDecodeError):
            raise AccountError('SDK账号数据无法读取，未保存') from None
        return value

    def capture(self, connection, original_auto=None):
        """Build a single-account snapshot from a successful server role; prune only the in-memory backup."""
        role = connection.login_call()
        identity = self.identity(connection)
        if (not role['logged_in'] or role['ret'] != 0 or not identity['server_matches'] or
                role['open_platform'] not in (0, 1) or role['mobile_platform'] not in (0, 1) or
                identity['sdk_platform'] != (1 if role['open_platform'] == 0 else 2) or not identity['token']):
            raise AccountError('请先成功登录角色再保存；未使用旧角色缓存')
        data = self.transport.snapshot_database()
        db = sqlite3.connect(':memory:')
        try:
            db.execute('pragma temp_store=MEMORY')
            db.row_factory = sqlite3.Row
            db.deserialize(data)
            selected = 'qq_login_info' if role['open_platform'] else 'wx_login_info'
            other = 'wx_login_info' if role['open_platform'] else 'qq_login_info'
            rows = [dict(row) for row in db.execute('select rowid as record_id,* from ' + selected)]
            matches = [row for row in rows if identity['openid'] in (row['open_id'], decode_sdk(row['open_id']))]
            if len(matches) != 1 or not matches[0]['access_token']:
                raise AccountError('SDK存储与当前角色不一致，未保存票据')
            db.execute('delete from ' + other)
            db.execute('delete from ' + selected + ' where rowid<>?', (matches[0]['record_id'],))
            db.commit()
            db.execute('vacuum')
            snapshot = bytearray(db.serialize())
            snapshot[18:20] = b'\x01\x01'
            snapshot = bytes(snapshot)
        except sqlite3.Error:
            raise AccountError('SDK票据快照校验失败，原账号未替换') from None
        finally:
            db.close()
        try:
            preferences = ET.fromstring(self.transport.read(SDK_PREF))
            entries = [ET.tostring(node, encoding='unicode') for node in preferences
                       if decode_sdk(node.attrib.get('name', '')) in AUTH_KEYS]
        except ET.ParseError:
            raise AccountError('SDK登录选择信息无法读取，未保存') from None
        # Detect a concurrent manual switch/refresh before committing the snapshot.
        after = self.identity(connection)
        if after['openid'] != identity['openid'] or after['token'] != identity['token']:
            raise AccountError('保存期间登录上下文发生变化，请停止手动切号后重试')
        value = dict(format=2, role=role, openid=identity['openid'], zone=identity['zone'],
                     database=base64.b64encode(snapshot).decode(), auth_preferences=entries,
                     no_auto_login=identity['auto_login'] if original_auto is None else original_auto,
                     db_sha256=hashlib.sha256(snapshot).hexdigest(),
                     sdk_access_token_sha256=hashlib.sha256(identity['token']).hexdigest())
        validate_profile(value)
        return value

    def save_current(self, cancel):
        """Save only a fully authenticated role, returning a public record rather than its credentials."""
        with account_operation():
            with self.connection(cancel) as connection:
                value = self.capture(connection)
                cancelled(cancel)
                return self.store.save(value)

    def _agreement(self, connection, cancel, publish):
        """Wait for the user's actual native checkbox, checking local state only and never accepting it ourselves."""
        state = connection.login_call()
        if state['stage'] != 'LoginStage' or state['logged_in']:
            raise AccountError('重启后未停在登录页，未发起认证，请重新切换')
        if not state['agreement']:
            publish(status='请在模拟器手动勾选用户协议；助手等待确认，不需要点登录按钮或重新扫码',
                    account_status='等待本人勾选登录协议；自动功能关闭')
        deadline = time.monotonic() + 300
        while not state['agreement']:
            cancelled(cancel)
            if time.monotonic() >= deadline:
                raise AccountError('等待协议确认超时，未发起认证；请重新点击切换或扫码')
            cancel.wait(1)
            state = connection.login_call()
            if state['stage'] != 'LoginStage' or state['logged_in']:
                raise AccountError('等待协议期间登录界面已变化，请重新读取当前账号')

    def _authenticated(self, connection, cancel, publish, profile=None, mobile=0, open_platform=0):
        """Stop at the first native refusal or identity mismatch; saved tickets and retry policy stay unchanged."""
        deadline, invalid_since = time.monotonic() + (60 if profile is not None else 180), None
        while time.monotonic() < deadline:
            cancelled(cancel)
            state = connection.login_call()
            watch = self.call(connection, 'watch')
            if watch.get('auth_error'):
                raise AccountError('登录身份上下文不一致，已停止；未重试认证，也未覆盖原票据')
            ret = watch.get('auth_ret', -999)
            if ret not in (-999, 0):
                reason = '身份校验失败' if ret == 2 else '登录被拒绝'
                raise AccountError(f'游戏服务器{reason}（错误码：{ret}），已停止；未自动重试，原票据保留')
            if state['logged_in'] and state['ret'] == 0:
                if not watch.get('auth_sent') or not watch.get('identity_matched') or ret != 0:
                    raise AccountError('本次登录的身份或服务器响应尚未确认，未保存票据')
                identity = self.identity(connection)
                if (state['mobile_platform'] != mobile or state['open_platform'] != open_platform or
                        not identity['server_matches'] or (profile and (identity['openid'] != profile['openid'] or
                        identity['zone'] != profile.get('zone', 1)))):
                    raise AccountError('服务器返回的账号或平台与选中记录不一致，自动功能保持关闭')
                return state
            if not watch['has_token'] or watch['sdk_platform'] not in (1, 2):
                invalid_since = invalid_since or time.monotonic()
                if time.monotonic() - invalid_since >= 5 and profile is not None:
                    raise TicketExpired('票据失效或认证被拒绝，请选择对应平台重新扫码；不会自动重试')
            else:
                invalid_since = None
            cancel.wait(1)
        if profile is not None:
            raise TicketExpired('恢复登录未完成，票据可能失效，请重新扫码；没有自动重试')
        raise AccountError('扫码授权未完成或登录超时，原有票据未覆盖；请核对游戏提示后重试')

    def login(self, cancel, publish, profile_id=None, qr_context=None):
        """Restart once, restore the selected platform, authenticate once and save only a server-confirmed identity."""
        with account_operation():
            handle = acquire_role(profile_id) if profile_id else None
            try:
                return self._login(cancel, publish, profile_id, qr_context)
            finally:
                release_role(handle)

    def _login(self, cancel, publish, profile_id, qr_context):
        """Restart with exclusive ownership; reuse a persisted pause without depending on a broken old Lua realm."""
        profile = self.store.load(profile_id) if profile_id else None
        if profile is not None and profile.get('ticket_status') == '需要重新扫码':
            raise TicketExpired('此账号票据已标记失效，请选择对应平台重新扫码；未重启或重复登录')
        if profile is not None:
            mobile, open_platform = profile['role']['mobile_platform'], profile['role']['open_platform']
        else:
            if not isinstance(qr_context, tuple) or len(qr_context) != 2 or any(type(v) is not int or v not in (0, 1) for v in qr_context):
                raise AccountError('请选择扫码登录的平台')
            mobile, open_platform = qr_context
        publish(status='正在准备重启客户端，自动功能全部关闭…')
        cancelled(cancel)
        if self.transport.startup_auto_paused() is True:
            previous_auto=1
            publish(status='已确认启动自动登录处于关闭状态，直接重启客户端；尚未发起认证…')
        else:
            publish(status='正在连接旧客户端以暂停启动自动登录，尚未重启或发起认证…')
            with self.connection(cancel) as connection:
                previous_auto = int(self.call(connection, 'pause'))
        if self.paused_auto is None:
            self.paused_auto = previous_auto
        original_auto = profile['no_auto_login'] if profile else self.paused_auto
        cancelled(cancel)
        self.transport.restart(cancel, profile)
        publish(status='客户端已重启，正在等待游戏模块加载；尚未发起认证…')
        try:
            with self.connection(cancel) as connection:
                try:
                    return self._finish_login(connection, cancel, publish, profile, mobile, open_platform, original_auto)
                except Exception:
                    self.paused_auto = original_auto
                    try:
                        self.call(connection, 'cancel_auth')
                    except Exception:
                        pass
                    raise
        except TicketExpired:
            if profile_id:
                try:
                    self.store.mark_scan_required(profile_id)
                except AccountError:
                    pass
            raise

    def _finish_login(self, connection, cancel, publish, profile, mobile, open_platform, original_auto):
        """Complete one requested authentication and update ciphertext only after server identity confirmation."""
        self._agreement(connection, cancel, publish)
        if profile is not None:
            identity = self.identity(connection)
            if identity['openid'] != profile['openid'] or identity['sdk_platform'] != (1 if open_platform == 0 else 2) or not identity['token']:
                raise TicketExpired('保存的SDK票据无法恢复，请重新扫码登录')
        cancelled(cancel)
        accepted = self.call(connection, 'restore' if profile else 'qr', mobile, open_platform, original_auto)
        if profile is not None and accepted != 'true':
            raise TicketExpired('SDK未接受本地票据，请重新扫码登录')
        publish(status='票据已提交，正在等待服务器确认…' if profile else '二维码已请求，请扫码并在手机确认授权…')
        state = self._authenticated(connection, cancel, publish, profile, mobile, open_platform)
        self.call(connection, 'auth_cleanup')
        if profile is None:
            self.call(connection, 'resume', mobile, open_platform, original_auto)
        self.paused_auto = None
        value = self.capture(connection, original_auto)
        cancelled(cancel)
        record = self.store.save(value, '最近登录成功')
        return state, record
