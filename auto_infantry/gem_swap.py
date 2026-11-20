"""Client-side 宝具 substitution driven by an independent bridge, usable from the game hall."""
import json
import queue
import subprocess
import threading
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parent

# Only catalogued 主印-style gems; the skill id comes from the game's own gem config row.
GEMS = {'天狼': 49034, '傲剑': 49036, '侠胆': 49037, '不替换': 0}
OFF = '不替换'

# The client answers with ASCII reason keys so no Chinese text crosses the Lua boundary.
REASONS = {'off': '宝具替换未启用', 'armed': '已启用：进入对局后自动替换',
           'not_in_battle': '待命：不在对局中，进入闯关后自动生效',
           'own_hero_not_found': '待命：还没找到我方英雄',
           'no_gem_list': '读不到宝具列表，已停止',
           'no_empty_slot': '没有空着的槽位可填（该英雄已装满）；已停止，不会覆盖已有宝具',
           'not_found': '没有解析到这个英雄名',
           'applied': '已替换', 'reverted': '已还原'}


def gem_id(name):
    """Return the configured gem id for a catalogued name, or 0 for an untouched position."""
    if name is None or name == OFF:
        return 0
    if name not in GEMS:
        raise ValueError('未知宝具：' + str(name))
    return GEMS[name]


def validate_plan(hero_base, first, second):
    """Freeze one hero and up to two gem positions; anything else is refused before touching the game."""
    if type(hero_base) is not int or not 0 < hero_base <= 10000000:
        raise ValueError('请先解析或选择要替换的英雄')
    gems = [gem_id(first), gem_id(second)]
    if not any(gems):
        raise ValueError('至少选择一个宝具')
    if gems[0] and gems[0] == gems[1]:
        raise ValueError('两个主印不能选同一个宝具')
    return {'hero_base': hero_base, 'gems': tuple(gems)}


def describe(snapshot):
    """Translate one client answer into a status line; numeric details are kept explicit."""
    note = snapshot.get('note')
    if note == 'hero_mismatch':
        return f"待命：当前英雄 {snapshot.get('hero')} 不是目标 {snapshot.get('target')}"
    return REASONS.get(note, note or str(snapshot.get('state')))


def hero_hex(name):
    """Pass the hero name as GBK hex so no non-ASCII text crosses the Lua boundary."""
    try:
        return name.strip().encode('gbk').hex().upper()
    except UnicodeEncodeError as error:
        raise ValueError('英雄名包含原生接口不支持的字符') from error


class Bridge:
    """One temporary Frida bridge that only exposes the bounded query used by this feature."""

    def __init__(self, script, session):
        self.script, self.session = script, session

    def query(self, source):
        return json.loads(self.script.exports_sync.query(source))

    def close(self):
        try:
            self.script.unload()
        except Exception:
            pass
        try:
            self.session.detach()
        except Exception:
            pass


def attach_bridge(adb='E:\\leidian\\LDPlayer14\\adb.exe', device='emulator-5554'):
    """Attach without waiting for the world map: the hall and a battle share one Lua VM."""
    flags = subprocess.CREATE_NO_WINDOW
    subprocess.run([adb, '-s', device, 'forward', 'tcp:27042', 'tcp:27042'], capture_output=True,
                   check=True, timeout=5, creationflags=flags)
    pid = int(subprocess.check_output([adb, '-s', device, 'shell', 'pidof', 'com.qqgame.mic'],
                                      text=True, timeout=5, creationflags=flags).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    try:
        script = session.create_script((ROOT / 'bridge.js').read_text(encoding='utf-8'))
        script.load()
        script.exports_sync.query((ROOT / 'gem_swap_runtime.lua').read_text(encoding='utf-8'))
    except Exception:
        session.detach()
        raise
    return Bridge(script, session)


class GemSwapSession:
    """Own one rule set and its own bridge, so the feature never depends on world readiness."""

    def __init__(self, events, attach=None, interval=0.8):
        self.events = events
        self.attach = attach or attach_bridge
        self.interval = interval
        self.commands = queue.Queue()
        self.guard = threading.Lock()
        self.enabled = False
        self.plan = None
        self.closed = False
        self.thread = None
        self.bridge = None
        self.last_text = None

    # -- public API -----------------------------------------------------------------
    def arm(self, hero_base, first, second, name=''):
        """Validate locally, then hand the frozen rules to the worker thread."""
        plan = validate_plan(hero_base, first, second)
        plan['name'] = name
        with self.guard:
            if self.closed:
                raise RuntimeError('助手正在关闭，未启用宝具替换')
            self.plan = plan
            self.commands.put(('arm', plan))
            self._start()
        self.event(gem_swap_enabled=True, gem_swap_status=f"已启用：{name or plan['hero_base']} 进入对局后自动替换")

    def disarm(self):
        """Stop applying immediately; the current battle keeps whatever was already written."""
        with self.guard:
            self.enabled = False
            self.plan = None
            self.commands.put(('disarm', None))
        self.event(gem_swap_enabled=False, gem_swap_status='宝具替换关闭；已改过的槽位可用「还原本次替换」写回')

    def probe(self):
        """Read the hero this battle assigned to my seat, so a target can be named mid-battle."""
        with self.guard:
            self._start()
            self.commands.put(('probe', None))

    def resolve(self, name):
        """Resolve a hero name to its identifier using the game's own config table."""
        if not name or not name.strip():
            raise ValueError('请输入英雄名')
        payload = hero_hex(name)
        with self.guard:
            self._start()
            self.commands.put(('resolve', payload))

    def revert(self):
        """Restore every slot this session changed and stay disarmed."""
        with self.guard:
            self.enabled = False
            self._start()
            self.commands.put(('revert', None))

    def close(self):
        """Release the owned bridge; replaced slots die with the battle or the reconnect."""
        with self.guard:
            self.closed = True
            self.enabled = False
            self.commands.put(('close', None))

    # -- worker ---------------------------------------------------------------------
    def event(self, **payload):
        if not self.closed:
            self.events.put(payload)

    def _start(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _bridge(self):
        if self.bridge is None:
            self.bridge = self.attach()
        return self.bridge

    def _drop_bridge(self):
        bridge, self.bridge = self.bridge, None
        if bridge is not None:
            try:
                bridge.close()
            except Exception:
                pass

    def _run(self):
        try:
            while True:
                try:
                    command, payload = self.commands.get(timeout=self.interval if self.enabled else .5)
                except queue.Empty:
                    command, payload = ('tick', None) if self.enabled else (None, None)
                if command == 'close':
                    break
                try:
                    self._handle(command, payload)
                except Exception as error:
                    self.enabled = False
                    self._drop_bridge()
                    self.event(gem_swap_enabled=False,
                               gem_swap_status='宝具替换已停止：' + str(error).splitlines()[0][:200])
        finally:
            self._drop_bridge()

    def _handle(self, command, payload):
        if command is None:
            return
        if command == 'tick':
            snapshot = self._bridge().query('return REA_GEM_SWAP.tick()')
            self._report(snapshot)
        elif command == 'arm':
            self.bridge = self._bridge()
            self.bridge.query(f"return REA_GEM_SWAP.configure({payload['hero_base']},{payload['gems'][0]},"
                              f"{payload['gems'][1]},1)")
            self.enabled = True
        elif command == 'disarm':
            if self.bridge is not None:
                self.bridge.query('return REA_GEM_SWAP.configure(0,0,0,0)')
            self.enabled = False
        elif command == 'probe':
            snapshot = self._bridge().query('return REA_GEM_SWAP.current_hero()')
            self.event(gem_swap_current_hero=snapshot,
                       gem_swap_status=(f"当前对局英雄：{snapshot['hero']}" if snapshot.get('state') == 'found'
                                        else describe(snapshot)))
        elif command == 'resolve':
            snapshot = self._bridge().query(f'return REA_GEM_SWAP.resolve_hero("{payload}")')
            if snapshot.get('state') == 'found':
                self.event(gem_swap_resolved=snapshot, gem_swap_status=f"已解析：{snapshot['ids']}")
            else:
                self.event(gem_swap_status=describe(snapshot))
        elif command == 'revert':
            snapshot = self._bridge().query('return REA_GEM_SWAP.revert()')
            self.event(gem_swap_slots=snapshot.get('slots') or [],
                       gem_swap_status='已还原' if snapshot.get('state') == 'reverted' else describe(snapshot))

    def _report(self, snapshot):
        state = snapshot.get('state')
        if state == 'applied':
            filled = snapshot.get('filled') or snapshot.get('gems') or []
            detail = ', '.join(f"{g.get('gem')}/{g.get('skill')}" for g in filled)
            self._status('已替换' + ('：' + detail if detail else ''), gem_swap_slots=snapshot.get('slots') or [])
        elif state in ('failed', 'error'):
            self.enabled = False
            self._status('替换失败：' + describe(snapshot), enabled=False)
        elif state == 'waiting':
            self._status(describe(snapshot))

    def _status(self, text, enabled=None, **extra):
        """Publish only a changed status line so a steady tick does not churn the panel."""
        with self.guard:
            changed = text != self.last_text
            self.last_text = text
        if changed or enabled is not None:
            payload = {'gem_swap_status': text, **extra}
            if enabled is not None:
                payload['gem_swap_enabled'] = enabled
            self.event(**payload)
