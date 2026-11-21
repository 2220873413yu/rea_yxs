"""Run one native guild invitation per explicit helper click."""
from contextlib import contextmanager, suppress
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

import frida

from account_lock import ensure_account_available
from connection import ADB, Connection
from instance_config import DEVICE
from game_log import GameResponseLog, tags
from game_protocol import JceReader

ROOT = Path(__file__).resolve().parent
LOOKUP = 1421
INVITE = 1415


def validate_target(value):
    """Keep the original decimal spelling for the native 12-digit field."""
    if not isinstance(value, str):
        raise ValueError('请输入 12 位数字玩家 ID')
    target = value.replace(' ', '')
    if not re.fullmatch('[0-9]{12}', target) or not int(target):
        raise ValueError('请输入 12 位数字玩家 ID')
    return target


def is_record(record, code):
    """Match only the specified request or response in the existing game log."""
    return record['tag'].startswith((f's_{code}_', f'r_{code}_'))


def wait_receipt(log, code, target, cancel, timeout=8):
    """Attribute one response to the matching new request and reject overlapping activity."""
    sent = False
    result = None
    deadline = time.monotonic() + timeout
    while not cancel.is_set() and time.monotonic() < deadline:
        for record in log.drain():
            if code == LOOKUP and is_record(record, INVITE):
                raise RuntimeError('游戏里出现了另一笔邀请，请先在游戏中核对')
            if not is_record(record, code):
                continue
            field = tags(JceReader(record['body']).fields()).get(0)
            if record['tag'].startswith('s_'):
                if sent or type(field) is not int or field != int(target):
                    raise RuntimeError('检测到其他请求，无法核对本次回执')
                sent = True
            else:
                if not sent or result is not None or type(field) is not int:
                    raise RuntimeError('回执无法归属到本次操作')
                result = field
        if result is not None:
            return result
        cancel.wait(.15)
    if cancel.is_set():
        raise InterruptedError('操作已取消')
    raise TimeoutError('未收到可确认的游戏回执')


@contextmanager
def lua_invite_scope(query, required_scope=None):
    """Give one invitation its own Lua state while using the caller's existing bridge."""
    name = '_REA_GUILD_INVITE_' + uuid.uuid4().hex
    source = (ROOT / 'guild_invite_runtime.lua').read_text(encoding='utf-8')
    try:
        query(source.replace('__GUILD_INVITE_API__', name).replace('__GUILD_INVITE_SCOPE__', required_scope or ''))
        yield query, name
    finally:
        with suppress(Exception):
            query(f'{name}=nil;return "closed"')


@contextmanager
def native_invite_scope():
    """Open a bridge bound to the current game process, login and guild."""
    ensure_account_available()
    process = Connection.read_process_identity()
    if process is None:
        raise RuntimeError('请先在模拟器打开并登录游戏')
    subprocess.run([ADB, '-s', DEVICE, 'forward', 'tcp:27042', 'tcp:27042'],
                   capture_output=True, check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(process[0], realm='emulated')
    script = None
    try:
        script = session.create_script((ROOT / 'bridge.js').read_text(encoding='utf-8'))
        script.load()
        with lua_invite_scope(script.exports_sync.query) as scope:
            yield scope
    finally:
        if script is not None:
            with suppress(Exception):
                script.exports_sync.close()
            with suppress(Exception):
                script.unload()
        with suppress(Exception):
            session.detach()


def invite_once(target, cancel, begin_submission, relay_scope=None):
    """Check the requested ID, invoke the native handler once and return its attributed receipt."""
    target = validate_target(target)
    submitted = False
    try:
        if cancel.is_set():
            raise InterruptedError('操作已取消')
        scope = native_invite_scope() if relay_scope is None else lua_invite_scope(*relay_scope)
        with scope as (query, name):
            def confirm():
                """Record when execution may have reached the native invite handler."""
                nonlocal submitted
                begin_submission()
                if cancel.is_set():
                    raise InterruptedError('操作已取消')
                submitted = True
                outcome = query(f'return {name}.confirm()')
                if outcome.startswith('not_sent:'):
                    submitted = False
                    raise RuntimeError(outcome.removeprefix('not_sent:'))
                if outcome != 'submitted':
                    raise RuntimeError('游戏邀请处理结果无法识别')
            return read_and_invite(target, cancel, query, name, confirm)
    except Exception as error:
        prefix = '邀请结果未确认，未重试：' if submitted else '未发送邀请：'
        detail = (str(error).splitlines() or [type(error).__name__])[0][:210]
        if 'Game Lua update did not run within five seconds' in detail:
            detail = '等待游戏处理超时，请确认游戏仍在运行'
        raise RuntimeError(prefix + detail) from error


def read_and_invite(target, cancel, query, name, confirm):
    """Resolve the player and attribute the native receipt while the same account is active."""
    log = GameResponseLog(ADB)
    log.drain()
    if cancel.is_set():
        raise InterruptedError('操作已取消')
    if query(f'return {name}.prepare("{target}")') != 'prepared':
        raise RuntimeError('无法准备游戏邀请')
    # The preview can return an error for a player who can still receive an invite.
    wait_receipt(log, LOOKUP, target, cancel)
    ensure_account_available()
    if any(is_record(record, LOOKUP) or is_record(record, INVITE) for record in log.drain()):
        raise RuntimeError('游戏中出现其他查询或邀请，请重新准备')
    confirm()
    ret = wait_receipt(log, INVITE, target, cancel)
    query(f'return {name}.check()')
    return '游戏回执：邀请成功' if ret == 0 else f'游戏回执：邀请失败（{ret}）'


class GuildInviteSession:
    """Run one explicitly clicked invitation and revoke pending work on account changes."""

    def __init__(self, events, sender=invite_once):
        self.events = events
        self.sender = sender
        self.guard = threading.Lock()
        self.generation = 0
        self.cancel = threading.Event()
        self.job = None
        self.sending = False
        self.closed = False

    def submit(self, value, web=None):
        """Authorize one ID for this click and reject duplicates while it is in progress."""
        target = validate_target(value)
        with self.guard:
            if self.closed or self.pending_shutdown() or (web is not None and web.stopped.is_set()):
                raise RuntimeError('已有邀请正在处理')
            self.cancel = threading.Event()
            self.sending = False
            if web is not None:
                self.events.put(dict(guild_invite_generation=self.generation, guild_web_received=target))
            self.job = threading.Thread(target=self._run,
                                        args=(target, self.generation, self.cancel, web), daemon=True)
            self.job.start()

    def _run(self, target, generation, cancel, web):
        """Publish progress and receipts under the account generation that authorized this click."""
        def begin_submission():
            """Close the cancellation gate atomically before issuing the native invite."""
            with self.guard:
                if self.closed or cancel.is_set() or generation != self.generation:
                    raise InterruptedError('操作已取消')
                if web is not None and (web.stopped.is_set() or time.monotonic() >= web.send_before):
                    raise InterruptedError('网页请求已失效')
                self.sending = True
                self.events.put(dict(guild_invite_generation=generation, guild_invite_sending=True))

        try:
            if web is None:
                status = self.sender(target, cancel, begin_submission)
            else:
                status = self.sender(target, cancel, begin_submission, relay_scope=web.scope)
        except Exception as error:
            status = (str(error).splitlines() or [type(error).__name__])[0][:240]
        finally:
            with self.guard:
                self.sending = False
        self.events.put(dict(guild_invite_generation=generation, guild_invite_result=status))
        if web is not None:
            web.reply.put_nowait(status)

    def cancel_current(self):
        """Cancel a lookup only while the native invitation is still revocable."""
        with self.guard:
            if self.sending or not self.pending_shutdown():
                return False
            self.cancel.set()
            return True

    def cancel_pending(self):
        """Invalidate results when the account is changing."""
        with self.guard:
            self.generation += 1
            self.cancel.set()

    def close(self):
        """Stop accepting work and invalidate pending lookups before shutdown."""
        with self.guard:
            self.closed = True
            self.generation += 1
            self.cancel.set()

    def pending_shutdown(self):
        """Report local thread lifetime without querying the game."""
        return self.job is not None and self.job.is_alive()
