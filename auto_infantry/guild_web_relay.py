"""Accept live webpage submissions while this assistant owns an eligible game session."""
from contextlib import suppress
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from typing import Callable
import uuid
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from account_lock import ensure_account_available
from account_store import crypt_profile
from guild_invite import native_invite_scope

ORIGIN = 'https://yxs-guild-invite.mightyblueberry2.chatgpt.site'
KEY_FILE = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'REA_YXS' / 'web-guild-invite.dpapi'
POLL_SECONDS = 1.5
CLAIM_SECONDS = 40
LOOPBACK_HTTP = build_opener(ProxyHandler({}))


@dataclass(frozen=True)
class WebInvite:
    """Bind a claimed job to the relay's active account and a finite send window."""
    scope: tuple[Callable[[str], str], str]
    stopped: threading.Event
    send_before: float
    reply: queue.Queue


def connector_request(key, action, client, **fields):
    """Keep local relay credentials on loopback while using HTTPS for remote relays."""
    payload = json.dumps(dict(client=client, **fields)).encode('utf-8')
    origin = relay_origin()
    request = Request(f'{origin}/connector/{action}', data=payload, method='POST',
                      headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                               'Accept': 'application/json', 'User-Agent': 'REA-YXS-Guild-Invite/1.0'})
    open_request = LOOPBACK_HTTP.open if origin.startswith('http://') else urlopen
    with open_request(request, timeout=3) as response:
        return json.loads(response.read(4096))


def relay_origin():
    """Use HTTPS remotely and allow explicit IPv4 loopback for a relay on this computer."""
    configured = os.environ.get('YXS_GUILD_RELAY_ORIGIN', ORIGIN)
    origin = urlsplit(configured)
    local = origin.scheme == 'http' and origin.hostname == '127.0.0.1' and origin.port is not None
    if ((origin.scheme != 'https' and not local) or not origin.hostname or origin.username is not None or
            origin.path not in {'', '/'} or origin.query or origin.fragment):
        raise ValueError('网页接单地址应为 HTTPS 站点地址或本机回环地址')
    return f'{origin.scheme}://{origin.netloc}'


def public_receipt(status):
    """Return the confirmed outcome without exposing local exceptions or account metadata."""
    if status == '游戏回执：邀请成功':
        return {'state': 'success'}
    code = re.fullmatch(r'游戏回执：邀请失败（(-?[0-9]+)）', status)
    if code:
        return {'state': 'failed', 'code': int(code[1])}
    if status.startswith('未发送邀请：'):
        return {'state': 'unavailable'}
    return {'state': 'unknown'}


class GuildWebRelay:
    """Poll only the web relay while active and hand each claim to the existing one-shot sender."""

    def __init__(self, session, events):
        self.session = session
        self.events = events
        self.stop_event = threading.Event()
        self.stop_event.set()
        self.worker = None

    def active(self):
        """Report whether the owner currently allows webpage invitations."""
        return not self.stop_event.is_set()

    def pending_shutdown(self):
        """Report whether the connector thread is releasing its presence."""
        return self.worker is not None and self.worker.is_alive()

    def start(self):
        """Enable one connector for this game session using its machine-encrypted relay key."""
        if self.pending_shutdown():
            raise RuntimeError('上一次网页接单正在停止，请稍后再开启')
        try:
            relay_origin()
        except ValueError as error:
            raise RuntimeError('网页接单地址应为 HTTPS 站点地址或本机回环地址') from error
        try:
            key = crypt_profile(KEY_FILE.read_bytes(), decrypt=True).decode('ascii')
        except Exception as error:
            raise RuntimeError('本机网页接单配置不可用') from error
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run, args=(key, self.stop_event), daemon=True)
        self.worker.start()

    def stop(self):
        """Revoke new native submissions and let the worker report any existing receipt."""
        self.stop_event.set()

    def _status(self, message):
        """Update the owner's panel through its Tk event queue."""
        self.events.put({'guild_web_status': message})

    def _run(self, key, stopped):
        """Advertise presence only while the same eligible game session can accept a new job."""
        client = str(uuid.uuid4())
        available = None
        status = '网页接单已关闭。'
        try:
            with native_invite_scope() as (query, scope):
                while not stopped.is_set():
                    if query(f'return {scope}.check()') != 'same':
                        break
                    try:
                        ensure_account_available()
                        ready = not self.session.pending_shutdown() and query(f'return {scope}.ready()') == 'ready'
                    except Exception:
                        ready = False
                    if ready and not stopped.is_set():
                        started = time.monotonic()
                        try:
                            response = connector_request(key, 'poll', client)
                        except (OSError, ValueError):
                            if available is not None:
                                self._status('暂时无法连接网页，正在等待连接恢复。')
                            available = None
                        else:
                            if available is not True:
                                self._status('网页接单在线，等待访客提交。')
                            available = True
                            if response.get('job') is not None:
                                self._process(key, client, response['job'], started, (query, scope), stopped)
                    elif available is not False:
                        with suppress(OSError, ValueError):
                            connector_request(key, 'offline', client)
                        available = False
                        self._status('网页暂不可用，等待游戏联网并确认公会邀请权限。')
                    stopped.wait(POLL_SECONDS)
        except Exception:
            if not stopped.is_set():
                status = '网页接单已关闭，游戏或公会会话不可用。请确认当前账号后重新开启。'
        finally:
            stopped.set()
            with suppress(OSError, ValueError):
                connector_request(key, 'offline', client)
            self._status(status)

    def _process(self, key, client, job, started, scope, stopped):
        """Handle one live claim and report its result without resubmitting the invitation."""
        deadline = started + CLAIM_SECONDS
        web = WebInvite(scope, stopped, deadline - 12, queue.Queue(maxsize=1))
        result = {'state': 'unavailable'}
        if not stopped.is_set() and time.monotonic() < web.send_before:
            try:
                self.session.submit(job['target'], web=web)
            except (RuntimeError, ValueError):
                pass
            else:
                try:
                    result = public_receipt(web.reply.get(timeout=max(0, deadline - time.monotonic() - 3)))
                except queue.Empty:
                    result = {'state': 'unknown'}
        try:
            connector_request(key, 'result', client, id=job['id'], **result)
        except (OSError, ValueError):
            self._status('网页回执未送达。请查看下方游戏回执。')
