"""Serialize native login and default-off worker replacement without retaining authentication secrets."""
import threading
import time

from bootstrap import ensure_server
from connection import Connection
from controller import Worker
from pathlib import Path
from account_store import AccountStore
from account_service import AccountService
from hunt_reconnect import log_reconnect


def account_label(state):
    """Decode only the server nickname; native strings may be GBK rather than UTF-8."""
    if not state.get('logged_in'):
        return '当前账号：未登录'
    raw = bytes.fromhex(state.get('nickname_hex', ''))
    try:
        name = raw.decode('utf-8')
    except UnicodeDecodeError:
        name = raw.decode('gb18030', errors='replace')
    platform = {0: '微信', 1: 'QQ'}.get(state['open_platform'], '其他平台')
    mobile = {0: '安卓', 1: 'iOS'}.get(state['mobile_platform'], '未知系统')
    return f"当前角色：{name} · {state['level']}级 · {mobile} {platform}"


class SessionEvents:
    """Tag worker events so an old account cannot update a replacement session's UI."""

    def __init__(self, events, epoch):
        self.events, self.epoch = events, epoch

    def put(self, event):
        """Copy before tagging; the original event may still be used for action logging."""
        self.events.put({**event, 'session_epoch': self.epoch})


class LoginSession:
    """Own at most one worker or login bridge, with cancellation and one-attempt QR login."""

    def __init__(self, events):
        self.events = events
        self.worker = None
        self.epoch = 0
        self.cancel = threading.Event()
        self.guard = threading.RLock()
        self.job = None
        self.closed = False
        self.store = AccountStore()
        self.accounts = AccountService(self.store)

    def request(self, mode='connect', selection=None):
        """Cancel earlier work before serial login, default-off reconnection or local encrypted migration."""
        if mode not in {'connect', 'hunt_reconnect', 'ios_wechat', 'account_save', 'account_switch', 'account_qr',
                        'account_export', 'account_import'}:
            raise ValueError('Unsupported session mode')
        with self.guard:
            if self.closed:
                return
            self.cancel.set()
            previous, old_job = self.worker, self.job
            self.cancel = cancel = threading.Event()
            self.epoch += 1
            epoch = self.epoch
            self.worker = None
            self.job = threading.Thread(target=self._replace, args=(mode, epoch, cancel, previous, old_job, selection), daemon=True)
            self.job.start()

    def _replace(self, mode, epoch, cancel, previous, old_job, selection=None):
        """Join old owners before opening a session; a delayed reconnect uses the existing game process."""
        sink = SessionEvents(self.events, epoch)
        connection = None
        try:
            if previous is not None:
                previous.stop()
                previous.join(timeout=20)
                if previous.is_alive():
                    raise RuntimeError('旧连接仍在退出，请稍后重新读取；尚未发起登录')
            if old_job is not None:
                old_job.join(timeout=20)
                if old_job.is_alive():
                    raise RuntimeError('上次登录操作尚未退出，请稍后重试')
            if cancel.is_set():
                return
            if mode in {'account_export', 'account_import'}:
                # Migration never needs ADB, a running game, SDK writes or an automatic replacement worker.
                from account_migration import export_accounts, import_accounts
                if mode == 'account_export':
                    keys, path, password = selection
                    result = export_accounts(self.store, keys, path, password, cancel)
                    message = f"已加密导出{result['exported']}个账号；密码不会保存"
                else:
                    path, password = selection
                    result = import_accounts(self.store, path, password, cancel)
                    message = f"已导入{result['imported']}个账号，跳过{result['skipped']}个本机已有账号；未自动登录"
                sink.put({'profiles': self.store.list(), 'ready': False,
                          'account_status': '当前游戏账号未切换；自动功能全部关闭',
                          'status': message + '。需要使用时请选择账号切换，票据失效请重新扫码。'})
                return
            if mode != 'hunt_reconnect':
                ensure_server()
                legacy = Path(__file__).resolve().parents[1] / 'analysis/evidence'
                self.store.import_legacy([legacy / 'ios-wechat-ticket-test.dpapi', legacy / 'android-qq-ticket-test.dpapi'])
                sink.put({'profiles': self.store.list()})
            if mode == 'account_save':
                record = self.accounts.save_current(cancel)
                sink.put({'status': '已加密保存当前账号：' + record['name'], 'profiles': self.store.list()})
            elif mode in {'account_switch', 'account_qr'}:
                state, record = self.accounts.login(cancel, lambda **event: sink.put(event),
                    profile_id=selection if mode == 'account_switch' else None,
                    qr_context=selection if mode == 'account_qr' else None)
                sink.put({'account': state, 'profiles': self.store.list(),
                          'status': '已登录并更新票据：' + record['name'] + '；自动功能全部关闭，请进入西游幻境'})
            if mode == 'ios_wechat':
                connection = Connection()
                connection.attach()
                state = connection.login_call()
                if state['stage'] != 'LoginStage':
                    connection.login_call('logout')
                    state = self._wait(connection, cancel, lambda s: s['stage'] == 'LoginStage', 20)
                if not state['agreement']:
                    sink.put({'status': '请本人勾选模拟器登录页的用户协议，再点击「iOS 微信扫码登录」',
                              'account_status': '当前账号：未登录；等待确认协议'})
                    return
                if cancel.is_set():
                    return
                connection.login_call('qr')
                sink.put({'status': '请用苹果角色对应的微信扫码并在手机上授权；完成后请进入西游幻境',
                          'account_status': 'iOS 微信二维码已请求，等待你扫码授权…'})
                state = self._wait(connection, cancel, lambda s: s['logged_in'], 180)
                if state['open_platform'] != 0 or state['mobile_platform'] != 1:
                    raise RuntimeError('登录完成但不是 iOS 微信身份，保持自动功能关闭')
                sink.put({'account_status': account_label(state)})
                connection.close()
                connection = None
            with self.guard:
                if cancel.is_set() or self.closed or epoch != self.epoch:
                    return
                worker = Worker(sink)
                worker.allow_scheduled_hunt = False
                if mode == 'hunt_reconnect':
                    worker.reconnect_plan = selection
                self.worker = worker
                if mode != 'hunt_reconnect':
                    worker.request_hero_refresh()
                    worker.request_collection_attributes()
                worker.start()
        except InterruptedError:
            pass
        except Exception as error:
            if mode == 'hunt_reconnect':
                log_reconnect('helper_reconnect_failed', str(error).splitlines()[0])
            sink.put({'ready': False, 'status': '登录/连接未完成：' + str(error).splitlines()[0],
                      'account_status': '当前账号：尚未完成重新读取，自动功能关闭'})
        finally:
            if connection is not None:
                connection.close()
            sink.put({'login_busy': False})
            sink.put({'profiles': self.store.list()})

    @staticmethod
    def _wait(connection, cancel, predicate, seconds):
        """Read local login cache only; never repeat QR, logout or game-server requests."""
        deadline = time.monotonic() + seconds
        while not cancel.is_set():
            state = connection.login_call()
            if predicate(state):
                return state
            if time.monotonic() >= deadline:
                raise TimeoutError('等待登录超时；没有自动重试，请核对游戏后手动重试')
            cancel.wait(1)
        raise InterruptedError('登录等待已取消')

    def close(self):
        """Cancel login waits and revoke any worker before the control window disappears."""
        with self.guard:
            self.closed = True
            self.cancel.set()
            worker = self.worker
        if worker is not None:
            worker.stop()

    def pending_shutdown(self):
        """Keep Tk alive until a cancelled SDK file transaction and its worker have safely released ownership."""
        return ((self.job is not None and self.job.is_alive() is True) or
                (self.worker is not None and self.worker.is_alive() is True))
