"""Own the temporary game bridge and its main-thread RPC lifecycle."""
import json
from contextlib import contextmanager
import ctypes
import contextlib
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import frida
from collection_balance import resource_balance
from units import UNIT_NAMES, checked_units
from hero_preferences import checked_heroes
from game_log import GameResponseLog, ResourceMissing, BeaconCapacityUnavailable
from account_lock import acquire_role, ensure_account_available, release_role
from account_store import profile_key
from player_profile_cache import PlayerProfileCache
from fast_recovery import FastRecovery
from collection import CollectionReplan
from monster import HuntReplan
from region_conflict import RegionConflict,RegionRestoreConflict
from hunt_reconnect import SessionUnsent, SessionAccepted, connection_lost, fence_rejected
from bootstrap import ADB, adb, ensure_client_version, root_command, verify_device
from instance_config import DEVICE, SECONDARY

ROOT = Path(__file__).resolve().parent
SUPPORTED_GAME_BUILDS = {'431000017': '4.31.0', '501000073': '5.1.0'}


class GameVersionError(RuntimeError):
    """Report a public package build mismatch before the helper attaches to the game."""


class BarrackUnavailable(RuntimeError):
    """Stop only troop automation when an upgrade or unknown building state prevents safe training."""


WORLD_READINESS_SOURCE = '''
local mm=CSLTypes.ModelManager.sharedInstance()
local main=mm:getModel(CSLTypes.SLGMainModel)
local account=mm:getModel(CSLTypes.MainModel)
local ok,stage=pcall(function()
 local cls=package.loaded.HeroPalaceItem
 return cls and cls.__instanceDict.getCurrentStageName({}) or 'unknown'
end)
stage=ok and tostring(stage):gsub('[^%w_]','') or 'unknown'
local rsp=main and main.mTSLGLoginMapRsp
local uid=account and account.myUserId
local worldUid=type(rsp)=='table' and type(rsp[5])=='table' and rsp[5][1]
local same=uid and worldUid and uid[1]==worldUid[1] and uid[2]==worldUid[2] and uid[3]==worldUid[3] and uid[4]==worldUid[4]
local ready=not not (same and main.mIsMapLoaded==true and rsp[1]==0 and stage~='LoginStage' and stage~='MainHallSceneStage')
return string.format('{"ready":%s,"stage":"%s"}',tostring(ready),stage)
'''


class Connection:
    """Attach to one running process and detach without leaving autonomous work behind."""

    def __init__(self):
        self.session = None
        self.script = None
        self.lock = threading.RLock()
        self.mutex_handle = None
        self.role_handle = None
        self.forward_port = None
        self.role_id = None
        self.hero_generation = 0
        self.collect_generation = 0
        self.hunt_generation = 0
        self.league_generation = 0
        self.beacon_generation = 0
        self.trial_generation = 0
        self.report_generation = 0
        self.response_log = None
        self.league_query_installed = False
        self.map_index_installed = False
        self.profile_cache = PlayerProfileCache()
        self.fast_recovery = FastRecovery()
        self.reconnect_key = None
        self.preserve_reconnect = False
        self.process_identity = None

    def clear_player_profile_cache(self):
        """Clear only current-map public profiles; resolving the scope never queries the server."""
        self.profile_cache.clear(self.map_index_call('context'))

    def _save_player_profile(self,scope,snapshot,identity=None):
        """Cache only confirmed profiles; a local save failure must not discard a successful query."""
        try:self.profile_cache.put(scope,snapshot,identity)
        except Exception as error:
            snapshot=dict(snapshot,cache_warning='资料已取得，但缓存未保存：'+str(error).splitlines()[0][:140])
        return snapshot

    def acquire_owner(self):
        """Allow only one helper connection to own the account's Lua bridge at a time."""
        ensure_account_available()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, True, r'Local\REA_AUTO_INFANTRY_' + DEVICE.replace('-', '_'))
        if not handle:
            raise OSError(ctypes.get_last_error(), 'Cannot acquire helper ownership')
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
            raise RuntimeError('已有一个造兵助手连接，请先关闭原窗口')
        self.mutex_handle = handle

    def attach(self, expected_process=None):
        """Check the installed build before taking ownership of a default-off bridge."""
        ensure_client_version()
        verify_device()
        package = subprocess.check_output([ADB, '-s', DEVICE, 'shell', 'dumpsys', 'package', 'com.qqgame.mic'],
                                          text=True, timeout=8, encoding='utf-8', errors='replace',
                                          creationflags=subprocess.CREATE_NO_WINDOW)
        match = re.search(r'^\s*versionCode=(\d+)(?=\s|$)', package, re.MULTILINE)
        build = match[1] if match else None
        if build not in SUPPORTED_GAME_BUILDS:
            supported = '、'.join(f'{version} ({code})' for code, version in SUPPORTED_GAME_BUILDS.items())
            detected = f'当前构建号 {build}' if build else '未读取到当前构建号'
            raise GameVersionError(f'英雄杀版本不兼容。{detected}，助手支持 {supported}。')
        self.acquire_owner()
        identity = self.read_process_identity()
        if expected_process is not None and identity != expected_process:
            raise RuntimeError('游戏已关闭或重启，取消自动重连')
        if identity is None:
            raise RuntimeError('游戏未运行')
        self.process_identity = identity
        pid = identity[0]
        try:
            port = 27042
            if SECONDARY:
                port = int(adb('forward', 'tcp:0', 'tcp:27042', timeout=5).stdout.strip())
                self.forward_port = port
            else:
                adb('forward', 'tcp:27042', 'tcp:27042', timeout=5)
            device = frida.get_device_manager().add_remote_device(f'127.0.0.1:{port}')
            self.session = device.attach(pid, realm='emulated')
            self.script = self.session.create_script((ROOT / 'bridge.js').read_text(encoding='utf-8'))
            self.script.load()
        except Exception:
            self.close()
            raise

    @staticmethod
    def read_process_identity():
        """Identify this Android boot and game process start, including when a PID has been reused."""
        result = root_command('p=$(pidof com.qqgame.mic) && cat /proc/sys/kernel/random/boot_id && cat /proc/$p/stat',
                              check=False)
        lines = result.stdout.splitlines()
        if result.returncode or len(lines) != 2:
            return None
        pid, _, _ = lines[1].partition(' (')
        _, _, stat = lines[1].rpartition(') ')
        fields = stat.split()
        if not pid.isdecimal() or len(fields) <= 19 or not fields[19].isdecimal():
            return None
        return int(pid), lines[0], int(fields[19])

    def login_call(self, operation='status', recovery_key=None):
        """Read role metadata or bind one verified recovery scope on the game's update thread."""
        if operation not in {'status', 'logout', 'qr', 'bind', 'identity_key'}:
            raise ValueError('Unknown login operation')
        source = ('local operation=' + json.dumps(operation) + '\nlocal recoveryKey=' +
                  (json.dumps(recovery_key) if recovery_key is not None else 'nil') + '\n' +
                  (ROOT / 'login_runtime.lua').read_text(encoding='utf-8'))
        with self.lock:
            value = self.script.exports_sync.query(source)
        if operation == 'status':
            return json.loads(value)
        if operation == 'identity_key':
            state = json.loads(value)
            identity = state['identity_hex']
            if identity and state['open_platform'] in (0, 1) and state['mobile_platform'] in (0, 1):
                return profile_key(dict(openid=bytes.fromhex(identity).decode('utf-8'), role=state, zone=state['identity_zone']))
            return None
        return value

    def open(self, on_status=None, cancel=None, on_account=None, hunt_resume=None):
        """Install fresh account APIs only after map readiness, with all spending gates closed."""
        try:
            if hunt_resume is None:
                self.attach()
            else:
                self.attach(expected_process=hunt_resume['process'])
                self.verify_reconnect_scope(hunt_resume['key'], cancel)
            if on_account is not None:
                account = self.login_call()
                if account.get('logged_in'):
                    self.update_role_owner()
                on_account({**account, 'profile_id': self.role_id})
            if hunt_resume is None:
                self.wait_world_ready(on_status, cancel)
                self.login_call('bind')
            if on_account is not None or SECONDARY:
                self.update_role_owner()
            if SECONDARY and not self.role_id:
                raise RuntimeError('无法核对第二台雷电的当前账号')
            if on_account is not None:
                on_account({**self.login_call(), 'profile_id': self.role_id})
            self.reconnect_key = uuid.uuid4().hex
            source = 'local reconnectKey=' + json.dumps(self.reconnect_key) + '\n' + (ROOT / 'hunt_reconnect_runtime.lua').read_text(encoding='utf-8')
            self.script.exports_sync.query(source)
            self.script.exports_sync.bindsession(True)
            self.script.exports_sync.query('if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.beacon_close then REA_AUTO_INFANTRY.beacon_close() end;'
                                           'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.league_close then '
                                           'REA_AUTO_INFANTRY.league_close() end;'
                                           'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.hunt_close then '
                                           'REA_AUTO_INFANTRY.hunt_close() end;'
                                           'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.collect_close then '
                                           'REA_AUTO_INFANTRY.collect_close() end;return "old_collection_cleared"')
            self.script.exports_sync.query((ROOT / 'runtime.lua').read_text(encoding='utf-8'))
            initial = self.initialize_barracks()
            self.script.exports_sync.query((ROOT / 'hero_runtime.lua').read_text(encoding='utf-8'))
            self.script.exports_sync.query((ROOT / 'collection_runtime.lua').read_text(encoding='utf-8'))
            self.script.exports_sync.query((ROOT / 'monster_runtime.lua').read_text(encoding='utf-8'))
            self.script.exports_sync.query((ROOT / 'league_runtime.lua').read_text(encoding='utf-8'))
            if not SECONDARY:
                self.script.exports_sync.query((ROOT / 'trial_runtime.lua').read_text(encoding='utf-8'))
            self.script.exports_sync.query((ROOT / 'beacon_runtime.lua').read_text(encoding='utf-8'))
            self.script.exports_sync.query((ROOT / 'beacon_actions.lua').read_text(encoding='utf-8'))
            self.script.exports_sync.query((ROOT / 'report_runtime.lua').read_text(encoding='utf-8'))
            return initial
        except Exception:
            self.close()
            raise

    def update_role_owner(self):
        """Reserve the current account while it is active, including before the world loads."""
        role_id = self.login_call('identity_key')
        if role_id != self.role_id:
            handle = acquire_role(role_id) if role_id else None
            release_role(self.role_handle)
            self.role_handle, self.role_id = handle, role_id

    def current_map_scope(self):
        """Read the already-bound role's world identity for local preference storage."""
        source = ('local main=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel);'
                  'assert(REA_HELPER_SESSION_VALID());local scope=main:getTMapGameDataID();'
                  'return string.format("[%d,%d]",scope[2],scope[1])')
        with self.lock:
            return json.loads(self.script.exports_sync.query(source))

    def verify_reconnect_scope(self, key, cancel=None):
        """Confirm the original role and loaded map once, before installing a new connection."""
        if cancel is not None and cancel.is_set():
            raise InterruptedError('重连恢复已取消')
        reason = self.login_call('bind', recovery_key=key)
        if reason != 'session_bound':
            raise RuntimeError({
                'account': '账号已变化，取消任务恢复', 'map': '区服或地图已变化，取消任务恢复',
                'pending': '游戏登录或地图尚未就绪，取消任务恢复',
            }.get(reason, '会话范围未确认，取消任务恢复'))

    def wait_world_ready(self, on_status=None, cancel=None):
        """Wait on local map readiness before binding account data; no game-server requests or auto entry."""
        previous = None
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('已取消等待地图加载')
            state = json.loads(self.script.exports_sync.query(WORLD_READINESS_SOURCE))
            if state['ready']:
                if on_status is not None:
                    on_status('地图已加载，正在查询当前登录账号的数据…')
                return
            message = ('当前在游戏大厅，请进入西游幻境并等待地图加载；助手正在等待，自动功能关闭'
                       if state['stage'] == 'MainHallSceneStage' else
                       '正在等待西游幻境地图加载；自动功能关闭，不会操作游戏')
            if on_status is not None and message != previous:
                on_status(message)
            previous = message
            if cancel is not None:
                cancel.wait(1)
            else:
                time.sleep(1)

    def call(self, operation, unit=411):
        """Invoke only a fixed local operation; never accept arbitrary commands from a UI."""
        if operation not in {'status', 'refresh', 'train', 'speed', 'barrack_probe'}:
            raise ValueError('Unknown infantry operation')
        if type(unit) is not int or unit not in UNIT_NAMES:
            raise ValueError('Unsupported troop identifier')
        with self.lock:
            result = self.script.exports_sync.query(f'return REA_AUTO_INFANTRY.{operation}({unit})',
                                                    'train_speed' if operation == 'speed' else operation == 'train', unit)
            return json.loads(result) if operation in {'status', 'barrack_probe'} else result

    def initialize_barracks(self, timeout=6):
        """Query once with gates closed, require a new successful response, then validate every troop type."""
        previous = self.call('barrack_probe')['barrack_seq']
        self.call('refresh')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            probe = self.call('barrack_probe')
            if probe['barrack_seq'] > previous and probe['received']:
                if probe['ret'] != 0:
                    raise RuntimeError(f"兵营初始化查询失败，服务器返回码：{probe['ret']}")
                states = {unit: self.call('status', unit) for unit in UNIT_NAMES}
                return states[411]
            time.sleep(.15)
        raise TimeoutError('兵营初始化查询超时，未收到新的成功响应；请确认已进入西游幻境并加载完成')

    def set_enabled(self, enabled, units=(411,), use_training_speed=False):
        """Authorize training and optional item use separately; master-off revokes both immediately."""
        if self.script is not None:
            selected = checked_units(units) if enabled else ()
            self.script.exports_sync.setenabled(bool(enabled), list(selected), bool(use_training_speed))

    def set_hero_enabled(self, enabled, heroes=()):
        """Apply only explicitly selected hero IDs and revoke the preceding generation of requests."""
        if self.script is not None:
            selected = checked_heroes(heroes) if enabled else ()
            self.hero_generation = self.script.exports_sync.setheroenabled(bool(enabled), list(selected))

    def hero_call(self, operation, generation=None, hero_id=303):
        """Dispatch fixed operations for one validated identifier, with no arbitrary UI-supplied Lua."""
        if operation not in {'hero_status', 'hero_list', 'hero_refresh', 'hero_speed', 'hero_speed_step', 'hero_view'}:
            raise ValueError('Unknown hero operation')
        checked_heroes((hero_id,))
        argument = str(hero_id) if operation in {'hero_status', 'hero_speed', 'hero_speed_step'} else ''
        with self.lock:
            result = self.script.exports_sync.query(f'return REA_AUTO_INFANTRY.{operation}({argument})',
                                                    'hero' if operation in {'hero_speed','hero_speed_step'} else False, hero_id,
                                                    generation)
            return json.loads(result) if operation in {'hero_status', 'hero_list', 'hero_view','hero_speed_step'} else result

    def hero_view(self):
        """Read existing response/push changes locally; this operation never sends a game request."""
        return self.hero_call('hero_view')

    def refresh_hero(self, timeout=6, hero_id=303):
        """Require new hero and army responses for the requested individual before another item."""
        return self._refresh_heroes('hero_status', hero_id, timeout)

    def refresh_heroes(self, timeout=6):
        """Read the complete authoritative roster without opening a building or spending resources."""
        return self._refresh_heroes('hero_list', 303, timeout)

    def _refresh_heroes(self, operation, hero_id, timeout):
        """Wait for both response generations, sharing the same freshness rule for lists and individuals."""
        before = self.hero_call(operation, hero_id=hero_id)
        self.hero_call('hero_refresh')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.hero_call(operation, hero_id=hero_id)
            if state['hero_seq'] > before['hero_seq'] and state['army_seq'] > before['army_seq']:
                if not state['fresh']:
                    raise RuntimeError('英雄状态刷新耗时过长，暂不恢复')
                return state
            time.sleep(0.15)
        raise TimeoutError('英雄或部队查询超时，自动恢复已停止')

    def recover_hero(self, before, generation, timeout=6):
        """Consume one recovery item and verify the response type/target before authoritative refresh."""
        if self.fast_recovery.uncertain:
            raise RuntimeError('上批快速恢复结果不明，请核对游戏并重新连接助手')
        hero_id = before['hero_id']
        checked_heroes((hero_id,))
        self.hero_call('hero_speed', generation, hero_id=hero_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.hero_call('hero_status', hero_id=hero_id)
            if state['speed_seq'] > before['speed_seq']:
                if (state['speed_ret'] != 0 or state['speed_kind'] != 3 or
                        state['speed_type'] != 500 or state['speed_target'] != hero_id):
                    raise RuntimeError('英雄加速响应失败或不属于请求英雄，已停止；请勿同时手动加速')
                return self.refresh_hero(hero_id=hero_id)
            time.sleep(0.15)
        raise TimeoutError('英雄恢复结果不明，已停止且不会自动重发')

    def recover_hero_fast(self,before,generation,cancelled):
        """Use one shared receipt cursor for a bounded burst, keeping unknown results latched across modes."""
        if self.response_log is None:self.response_log=GameResponseLog(ADB)
        return self.fast_recovery.recover(self,before,generation,cancelled,self.response_log)

    def set_collection_enabled(self, enabled):
        """Revoke queued departures immediately without touching the shared recovery or troop gates."""
        if self.script is not None:
            self.collect_generation = self.script.exports_sync.setcollectenabled(bool(enabled))

    def collection_call(self, operation, arguments=(), generation=None, hero_id=1):
        """Invoke numeric collection operations; scope loads and departures share the revocable collection gate."""
        if operation not in {'collect_candidates', 'collect_query', 'collect_status', 'collect_metrics', 'collect_dispatch',
                             'collect_push_status', 'collect_schedule', 'collect_region_plan', 'collect_region_query',
                             'collect_region_read', 'collect_balance_state'}:
            raise ValueError('Unknown collection operation')
        if any(type(value) is not int or value < 0 or value > 100000000 for value in arguments):
            raise ValueError('Invalid collection parameters')
        source = 'return REA_AUTO_INFANTRY.' + operation + '(' + ','.join(map(str, arguments)) + ')'
        with self.lock:
            result = self.script.exports_sync.query(source, 'collect' if operation in {'collect_dispatch','collect_region_query'} else False,
                                                    hero_id, generation)
            return json.loads(result) if operation in {'collect_candidates', 'collect_status', 'collect_metrics',
                'collect_push_status', 'collect_schedule', 'collect_region_plan', 'collect_region_read',
                'collect_balance_state'} else result

    def collection_balance(self, cancelled):
        """Estimate existing ordinary trips once per decision, then reconcile stock and armies after the reads.

        The existing resource query supplies each resident's server maximum or a marching hero's
        target-specific load. All spending gates stay unchanged; this method owns no timer.
        """
        if cancelled():
            raise InterruptedError('采集已关闭，停止收益查询')
        roster = None
        try:
            snapshot = self.collection_call('collect_balance_state')
        except Exception as error:
            if 'Fresh army state is required for resource balancing' not in str(error) or cancelled():
                raise
            # Slow region/barrack reads can expire the pre-planning snapshot; refresh this read once only.
            roster = self.refresh_heroes()
            snapshot = self.collection_call('collect_balance_state')
        metrics = {}
        queried = False
        for army in snapshot['armies']:
            if army['aim'] != 1 or army['state'] in (7, 9) or army['target_id'] in metrics:
                continue
            if cancelled():
                raise InterruptedError('采集已关闭，停止收益查询')
            queried = True
            try:
                metrics[army['target_id']] = self.query_collection(army['target_id'])
            except ResourceMissing:
                # This is an existing trip, not a new candidate: never delete a saved coordinate here.
                metrics[army['target_id']] = {}
        if cancelled():
            raise InterruptedError('采集已关闭，停止分配')
        if queried:
            roster = self.refresh_heroes()
        snapshot = self.collection_call('collect_balance_state')
        return {'balance': resource_balance(snapshot, metrics), 'roster': roster}

    def collection_push_sequence(self):
        """Read the passive own-army notification marker locally; this sends no game-server request."""
        return self.collection_call('collect_push_status')['seq']

    def set_hunt_enabled(self, enabled):
        """Immediately revoke queued hunting departures and skips without touching other switches."""
        if self.script is not None:
            self.hunt_generation = self.script.exports_sync.sethuntenabled(bool(enabled))

    def hunt_call(self, operation, arguments=(), generation=None, hero_id=1):
        """Gate numeric hunting operations and refresh once only for explicit pre-send stale guards."""
        readable = {'hunt_candidates', 'hunt_schedule', 'hunt_watch', 'hunt_status', 'hunt_metrics',
                    'hunt_scan_plan', 'hunt_region_state', 'hunt_region_read', 'hunt_refresh_clock'}
        operations = readable | {'hunt_query', 'hunt_cancel_query', 'hunt_dispatch', 'hunt_ack', 'hunt_resume', 'hunt_release',
                                 'hunt_skip', 'hunt_region_query'}
        if operation not in operations or any(type(v) is not int or not 0 <= v <= 100000000 for v in arguments):
            raise ValueError('Invalid hunting operation or arguments')
        source = 'return REA_AUTO_INFANTRY.' + operation + '(' + ','.join(map(str, arguments)) + ')'
        for attempt in range(2):
            try:
                with self.lock:
                    gated = operation in {'hunt_dispatch', 'hunt_skip'} or (operation == 'hunt_region_query' and generation is not None)
                    value = self.script.exports_sync.query(source, 'hunt' if gated else False,
                                                           hero_id, generation)
                return json.loads(value) if operation in readable else value
            except Exception as error:
                if operation=='hunt_region_read' and 'HUNT_REGION_CONFLICT:' in str(error):
                    raise RegionConflict('读取前地图区域再次改变，需重新核对') from error
                # These exact Lua guards precede all native callbacks and submission markers.
                # Never retry a dispatch, transport timeout, server refusal or ambiguous skip.
                guard = {'hunt_schedule': 'Fresh own-army response required',
                         'hunt_skip': 'Fresh busy hero required'}.get(operation)
                if attempt or guard is None or guard not in str(error):
                    raise
                self.refresh_heroes()

    def _load_hunt_region(self, x, y, timeout=6, generation=None, collection_generation=None):
        """Await the matching new response within one bounded deadline, tolerating interleaved foreign areas."""
        before = self.hunt_call('hunt_region_state')
        if collection_generation is not None:
            self.collection_call('collect_region_query', (x, y), collection_generation)
        elif generation is None:
            self.hunt_call('hunt_region_query', (x, y))
        else:
            self.hunt_call('hunt_region_query', (x, y), generation)
        deadline = time.monotonic() + timeout
        foreign=None
        while time.monotonic() < deadline:
            state = self.hunt_call('hunt_region_state')
            if state['seq'] > before['seq']:
                if (state['last_x'], state['last_y'], state['view_x'], state['view_y']) != (x, y, x, y):
                    foreign=(state['last_x'],state['last_y'])
                else:return state
            time.sleep(.1)
        if foreign is not None:
            raise RegionConflict(f'区域核对冲突：预期({x},{y})，最近收到{foreign}；本次未采用异区数据')
        raise TimeoutError('地图区域查询超时，未继续扫描或出征')

    @contextmanager
    def _hunt_region_scope(self, x, y, generation=None, collection_generation=None):
        """Restore only our temporary view, respect a newly loaded camera area and never mask a primary action error."""
        original = self.hunt_call('hunt_region_state')
        origin = (original['view_x'], original['view_y'])
        if any(type(v) is not int or v < 0 for v in origin):
            raise RuntimeError('原地图区域未知，未开始区域查询')
        state=None
        primary=None
        try:
            state = self._load_hunt_region(x, y, generation=generation, collection_generation=collection_generation)
            yield state
        except BaseException as error:
            primary=error
            raise
        finally:
            try:
                latest = self.hunt_call('hunt_region_state')
                camera = (latest.get('camera_x'), latest.get('camera_y'))
                camera_moved = (all(type(v) is int and v >= 0 for v in camera) and
                                camera != (original.get('camera_x'), original.get('camera_y')))
                native_view_loaded=(state is not None and latest['seq']>state['seq'] and camera_moved and
                                    (latest['view_x'],latest['view_y'])!=(x,y))
                # Native camera loading already took ownership; do not race it with an exact-center restore.
                if not native_view_loaded and (origin != (x, y) or camera_moved):
                    self._load_hunt_region(*(camera if camera_moved else origin))
            except Exception as cleanup:
                if primary is None:
                    if isinstance(cleanup,(RegionConflict,TimeoutError)):
                        raise RegionRestoreConflict('恢复地图区域未确认：'+str(cleanup)) from cleanup
                    raise
                # In particular, an unknown dispatch/skip must remain the primary error and cannot be retried.

    def query_hunt_region(self, region, radius, generation=None):
        """Retry only a conflicted read once; post-read restoration failures never replay a successful operation."""
        x, y = region['x'], region['y']
        for attempt in range(2):
            try:
                with self._hunt_region_scope(x, y, generation) as state:
                    return self.hunt_call('hunt_region_read', (radius, state['seq'], x, y))
            except RegionRestoreConflict:raise
            except RegionConflict:
                if attempt:raise

    @contextmanager
    def hunt_target_region(self, target, radius, generation=None):
        """Reload an uncached catalog target through final dispatch checks; discovery records alone never authorize it."""
        rows = self.hunt_call('hunt_candidates', (radius,))
        if any(all(row[k] == target[k] for k in ('target_id', 'config_id', 'x', 'y')) for row in rows):
            yield
        else:
            with self._hunt_region_scope(target['logic_x'], target['logic_y'], generation):
                yield

    def query_monster(self, target_id, timeout=6):
        """Refresh expired eligibility once during this target check, never treating stale reads as busy heroes."""
        for attempt in range(2):
            metrics = self._query_monster_once(target_id, timeout)
            own_fresh = metrics['own_state_fresh']
            if own_fresh and metrics['target']['fresh']:
                return metrics
            if attempt:
                raise RuntimeError('打野查询数据持续过期，未出征；请检查游戏响应是否缓慢')
            if not own_fresh:
                self.refresh_heroes()
            # The hero refresh can outlive target freshness: require another exact-target reply too.

    def _query_monster_once(self, target_id, timeout):
        """Await one exact target's new detail/candidate replies and always release popup suppression."""
        before = self.hunt_call('hunt_status')
        try:
            self.hunt_call('hunt_query', (target_id,))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state = self.hunt_call('hunt_status')
                if (state['target_id'] == target_id and state['ready'] and
                        state['detail_seq'] > before['detail_seq'] and state['available_seq'] > before['available_seq']):
                    if state['detail_ret'] != 0 or state['available_ret'] != 0:
                        raise RuntimeError(f"野怪查询失败：{state['detail_ret']} / {state['available_ret']}")
                    return self.hunt_call('hunt_metrics')
                time.sleep(.1)
            raise TimeoutError('野怪详情或可用英雄查询超时，未派出')
        finally:
            self.hunt_call('hunt_cancel_query')

    def dispatch_hunt(self, target, formation, radius, generation):
        """Send one guarded formation, match its server receipt, and bind the confirmed army for later skip."""
        if self.response_log is None:
            self.response_log = GameResponseLog(ADB)
        self.response_log.drain()
        hero_id, target_id = formation['hero_id'], target['target_id']
        try:
            outcome=self.hunt_call('hunt_dispatch', (target_id, hero_id, formation['soldier_id'], formation['followers'],
                                            target['detail_seq'], target['available_seq'], radius, target['x'], target['y']),
                           generation, hero_id)
        except Exception as error:
            if fence_rejected(error):raise SessionUnsent(str(error)) from error
            raise
        if outcome in ('hunt_replan:hero','hunt_replan:stale','hunt_replan:action'):
            raise HuntReplan('打野英雄或资料已变化，原生确认尚未发送出征请求')
        receipt = self.response_log.wait_hunt(hero_id, target_id)
        try:
            roster = self.refresh_heroes()
            self.hunt_call('hunt_ack', (target_id, hero_id, receipt['army_id']))
        except Exception as error:
            if connection_lost(error):raise SessionAccepted(error, receipt) from error
            raise
        return receipt, roster

    def skip_hunt(self, active, generation):
        """Submit the native skip once and attribute the quick-combat response to the tracked army."""
        if self.response_log is None:
            self.response_log = GameResponseLog(ADB)
        self.response_log.drain()
        try:
            self.hunt_call('hunt_skip', (active['target_id'], active['hero_id'], active['army_id']), generation, active['hero_id'])
        except Exception as error:
            if fence_rejected(error):raise SessionUnsent(str(error)) from error
            raise
        return self.response_log.wait_hunt_skip(active['army_id'], active['target_id'])

    def set_league_enabled(self, enabled):
        """Revoke alliance mining independently of ordinary mining, hunting and recovery."""
        if self.script is not None:
            self.league_generation = self.script.exports_sync.setleagueenabled(bool(enabled))

    def set_beacon_enabled(self, enabled):
        """Revoke beacon actions and preparation reads without changing any other feature switch."""
        if self.script is not None:
            self.beacon_generation = self.script.exports_sync.setbeaconenabled(bool(enabled))

    def configure_beacon(self, kinds):
        """Close the old epoch before applying the explicitly selected native event types."""
        from beacon_preferences import checked_types
        kinds=checked_types(kinds)
        self.set_beacon_enabled(False)
        self.beacon_call('beacon_configure',(sum(2**(k-1) for k in kinds),))

    def query_beacon_scout(self,event_id,generation,cancelled=None):
        """Send one stock GET, then wait only on the local matching response."""
        if cancelled and cancelled():raise InterruptedError('烽火台侦察检查已取消')
        self.beacon_call('beacon_scout_query',(event_id,),generation)
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            if cancelled and cancelled():raise InterruptedError('烽火台侦察检查已取消')
            result=self.beacon_call('beacon_scout_result',(event_id,))
            if result['ready']:return result
            time.sleep(.1)
        raise TimeoutError('斥候库存查询超时，未重复发送')

    def beacon_call(self, operation, arguments=(), generation=None, hero_id=1):
        """Expose only fixed beacon operations and gate all actions plus target-candidate queries by run epoch."""
        readable = {'beacon_watch', 'beacon_snapshot', 'beacon_candidates_result', 'beacon_scout_result','beacon_target_result'}
        gated = {'beacon_dispatch', 'beacon_recall', 'beacon_claim', 'beacon_candidates_query', 'beacon_scout', 'beacon_skip', 'beacon_scout_query','beacon_target_query'}
        if operation not in readable | gated | {'beacon_info_query', 'beacon_cancel_query', 'beacon_ack', 'beacon_configure','beacon_rejected'}:
            raise ValueError('Invalid beacon operation')
        if any(type(v) is not int or not (0 if operation=='beacon_configure' else 1) <= v <= 100000000 for v in arguments):
            raise ValueError('Invalid beacon arguments')
        source = 'return REA_AUTO_INFANTRY.' + operation + '(' + ','.join(map(str, arguments)) + ')'
        with self.lock:
            value = self.script.exports_sync.query(source, 'beacon' if operation in gated else False,
                                                   hero_id, generation)
        return json.loads(value) if operation in readable | {'beacon_dispatch', 'beacon_scout'} else value

    def _wait_beacon_read(self, operation, cancelled=None, timeout=6):
        """Wait only on local caches after one GET; cancellation prevents all dependent operations."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancelled and cancelled():
                raise InterruptedError('烽火台检查已取消')
            value = self.beacon_call(operation)
            if value['ready']:
                return value
            time.sleep(.1)
        raise TimeoutError('烽火台查询超时，未重复发送')

    def query_beacon(self, cancelled=None):
        """Fetch one fresh event list; create the response log before taking any time-sensitive snapshots."""
        if cancelled and cancelled():
            raise InterruptedError('烽火台检查已取消')
        if self.response_log is None:
            self.response_log = GameResponseLog(ADB)
        self.beacon_call('beacon_info_query')
        return self._wait_beacon_read('beacon_snapshot', cancelled)

    def query_beacon_candidates(self, event_id, generation, cancelled=None):
        """Fetch the exact event's detail then native availability without a popup or recovery request."""
        if cancelled and cancelled():
            raise InterruptedError('烽火台选将已取消')
        try:
            self.beacon_call('beacon_target_query',(event_id,),generation)
            self._wait_beacon_read('beacon_target_result',cancelled)
            if cancelled and cancelled():raise InterruptedError('烽火台选将已取消')
            self.beacon_call('beacon_candidates_query', (event_id,), generation)
            return self._wait_beacon_read('beacon_candidates_result', cancelled)
        except Exception:
            self.beacon_call('beacon_cancel_query')
            raise

    def beacon_action(self, operation, event_id, generation, hero_id=1, army_id=None):
        """Submit one selected event action, require its exact receipt and confirm resulting server state."""
        if operation not in {'dispatch', 'recall', 'claim', 'scout', 'skip'}:
            raise ValueError('Invalid beacon action')
        if self.response_log is None:
            raise RuntimeError('烽火台响应日志未准备')
        arguments = (event_id, hero_id) if operation == 'dispatch' else (
            (event_id, hero_id, army_id) if operation in {'recall','skip'} else (event_id,))
        self.response_log.drain()
        result = self.beacon_call('beacon_' + operation, arguments, generation, hero_id)
        if operation=='dispatch' and isinstance(result,dict) and result.get('not_sent') is True:
            if result.get('reason')=='capacity_full' and result.get('event_id')==event_id:
                raise BeaconCapacityUnavailable('发令前确认烽火台额度已满，本次未发送')
            raise RuntimeError('烽火台本地出征结果无法确认，不重发')
        if operation=='skip':
            receipt=self.response_log.wait_hunt_skip(army_id,event_id,expected_aim=45)
            if not receipt['won']:
                raise RuntimeError('烽火台战斗未获胜，已停止')
        elif operation=='scout':
            receipt=self.response_log.wait_beacon_scout(result['logic_x'],result['logic_y'])
        else:
            receipt = self.response_log.wait_beacon(operation, event_id, hero_id, army_id)
        roster = self.refresh_heroes()
        if operation == 'dispatch':
            self.beacon_call('beacon_ack', (event_id, hero_id, receipt['army_id']))
        snapshot = self.query_beacon()
        event = next((e for e in snapshot['events'] if e['event_id'] == event_id), None)
        if operation == 'recall' and (event is None or event['state'] != 3):
            raise RuntimeError('撤回成功但救援完成未确认，不重复撤回')
        if operation == 'claim' and event is not None:
            raise RuntimeError('领奖成功但事件释放未确认，不重复领奖')
        return receipt, snapshot, roster

    def league_call(self, operation, arguments=(), generation=None, hero_id=1):
        """Gate alliance operations and refresh once only when the read-only own-army snapshot is rejected."""
        readable = {'league_watch', 'league_build_result', 'league_mine_result', 'league_metrics', 'league_schedule',
                    'league_heroes_result'}
        if operation not in readable | {'league_build_query', 'league_mine_query', 'league_cancel_query',
                                       'league_dispatch', 'league_ack', 'league_heroes_query'}:
            raise ValueError('Invalid alliance operation')
        if any(type(v) is not int or not 0 < v <= 100000000 for v in arguments):
            raise ValueError('Invalid alliance arguments')
        source = 'return REA_AUTO_INFANTRY.' + operation + '(' + ','.join(map(str, arguments)) + ')'
        for attempt in range(2):
            try:
                with self.lock:
                    value = self.script.exports_sync.query(source, 'league' if operation == 'league_dispatch' else False,
                                                           hero_id, generation)
                return json.loads(value) if operation in readable or operation == 'league_dispatch' else value
            except Exception as error:
                # This exact guard is in league_schedule, which reads but never submits an army.
                if attempt or operation != 'league_schedule' or 'Fresh own armies required' not in str(error):
                    raise
                self.refresh_heroes()

    def query_league(self, timeout=6):
        """Discover the current mine from a new own-building response, then read exact target metrics once."""
        def wait_result(operation):
            """Wait for arrival in local model caches without resending the server request."""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                result = self.league_call(operation)
                if result['ready']:
                    return result
                time.sleep(.1)
            raise TimeoutError('联盟采集查询超时，未派出')
        try:
            self.league_call('league_build_query')
            building = wait_result('league_build_result')
            if not building['found']:
                return {'mine': None, 'heroes': []}
            self.league_call('league_mine_query', (building['target_id'],))
            wait_result('league_mine_result')
            metrics = self.league_call('league_metrics')
            mine = metrics['mine']
            if (mine['stock'] > 0 and mine['occupied'] < mine['capacity'] and
                    not mine['own_present'] and mine['visible']):
                self.league_call('league_heroes_query')
                wait_result('league_heroes_result')
            return self.league_call('league_metrics')
        finally:
            self.league_call('league_cancel_query')

    def dispatch_league(self, target_id, hero_id, generation):
        """Submit once, match the exact server receipt and confirm the accepted army before any later send."""
        if self.response_log is None:
            raise RuntimeError('联盟采集响应日志尚未准备')
        self.response_log.drain()
        plan = self.league_call('league_dispatch', (target_id, hero_id), generation, hero_id)
        receipt = self.response_log.wait_league(hero_id, target_id, plan['secondary_target'])
        roster = self.refresh_heroes()
        self.league_call('league_ack', (target_id, hero_id, receipt['army_id']))
        return receipt, roster

    def collection_candidates(self, kind, level, radius):
        """Read only loaded resource points; never expand the map silently or select an enemy army."""
        return self.collection_call('collect_candidates', (kind, level, radius))

    def collection_list_candidates(self, coordinates, generation, cancelled=None, *, known_rows=(), skip_regions=(), max_regions=None):
        """Locate missing saved points in bounded region batches, preserving caller-owned discovery across checks."""
        saved = set(map(tuple, coordinates))
        found = {}
        def merge(rows):
            """Merge only requested coordinates so overlapping area replies cannot add unintended targets."""
            for row in rows:
                point = (row['x'], row['y'])
                if point in saved:
                    found[point] = row
        merge(known_rows)
        merge(self.collection_candidates(0, 0, 0))
        missing = sorted(saved - found.keys())
        loaded = 0
        checked = []
        if missing and not (cancelled and cancelled()):
            plan = self.collection_call('collect_region_plan', tuple(value for p in missing for value in p))
            for region in plan['regions']:
                if cancelled and cancelled():
                    break
                if (region['x'],region['y']) in skip_regions:
                    continue
                if max_regions is not None and loaded >= max_regions:
                    break
                if all(tuple(p) in found for p in region['coordinates']):
                    continue
                x, y = region['x'], region['y']
                with self._hunt_region_scope(x, y, collection_generation=generation) as state:
                    if cancelled and cancelled():
                        break
                    merge(self.collection_call('collect_region_read', (state['seq'], x, y)))
                    loaded += 1
                    checked.append((x,y))
        return {'rows': list(found.values()), 'regions_loaded': loaded, 'regions_checked': checked}

    def query_collection_candidate(self, target_id):
        """Drain old traffic before refreshing activity, then read the target without a second pre-query drain."""
        roster = None
        def refresh_activity():
            """Start the short eligibility window only after slow historical log preparation has finished."""
            nonlocal roster
            roster = self.refresh_heroes()
        metrics = self.query_collection(target_id, before_query=refresh_activity)
        return metrics, roster

    def query_collection(self, target_id, timeout=6, *, before_query=None):
        """Match a resource wire reply, then await fresh native data; only an attributed6001 means missing."""
        if self.response_log is None:
            self.response_log = GameResponseLog(ADB)
        self.response_log.drain()
        if before_query is not None:
            before_query()
        before = self.collection_call('collect_status')
        self.collection_call('collect_query', (target_id,))
        try:
            self.response_log.wait_resource_detail(target_id, timeout)
        except ResourceMissing:
            # A late reply from a previous world/account cannot delete a coordinate in the current session.
            self.collection_call('collect_status')
            raise
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.collection_call('collect_status')
            if state.get('observer_error'):
                raise RuntimeError('采集响应结构异常，未派出')
            if (state['ready'] and state['target_id'] == target_id and
                    state['detail_seq'] > before['detail_seq'] and state['available_seq'] > before['available_seq']):
                if state['fresh']:
                    metrics = self.collection_call('collect_metrics')
                    if metrics['target'].get('fresh'):
                        return metrics
            time.sleep(.1)
        raise TimeoutError('采集目标或选将数据查询超时，未派出')

    def dispatch_collection(self, metrics, hero_id, generation):
        """Check the local roster and send with the same recovery setting used to rank heroes."""
        checked_heroes((hero_id,))
        target = metrics['target']
        if self.response_log is None:
            raise RuntimeError('采集响应日志尚未准备，未派出')
        try:
            before = self.hero_call('hero_list')
        except Exception as error:
            if connection_lost(error):
                raise SessionUnsent(error) from error
            raise
        hero = next((row for row in before['heroes'] if row['hero_id'] == hero_id), None)
        if (hero is None or not hero.get('found') or not hero.get('fresh') or not hero.get('army_known') or
                hero.get('busy') or hero.get('hero_state') != 0 or hero.get('remaining_ms',1)>0):
            reason=('hero_missing' if hero is None else 'hero_stale' if not hero.get('fresh') else
                    'army_unknown' if not hero.get('army_known') else 'hero_busy' if hero.get('busy') or hero.get('hero_state')!=0
                    else 'hero_cooling')
            raise CollectionReplan('采集英雄尚未就绪（'+reason+'），尚未发送出征请求',reason=reason)
        # query_collection drained before its reads. Keep that cursor: a competing dispatch must be detected,
        # not erased, and another ADB drain here could expire both resource and hero evidence.
        arguments = (target['target_id'], hero_id, target['kind'], target['level'],
                     target['detail_seq'], target['available_seq'], target['scope_radius'], target['x'], target['y'],
                     int(bool(target.get('balance_guard'))), int(target.get('use_hero_recovery') is True))
        try:
            outcome = self.collection_call('collect_dispatch', arguments, generation, hero_id)
        except Exception as error:
            if fence_rejected(error):
                raise SessionUnsent(error) from error
            raise
        if outcome in ('collection_replan:hero_state','collection_replan:stale','collection_replan:selection'):
            reason=outcome.split(':',1)[1]
            label={'hero_state':'英雄或部队状态变化','stale':'资源或选将详情已过期','selection':'最快采集英雄已变化'}[reason]
            raise CollectionReplan(label+'，尚未发送出征请求',reason=reason)
        receipt = self.response_log.wait_collection(hero_id, target['target_id'])
        try:
            roster = self.refresh_heroes()
            schedule = self.collection_call('collect_schedule')
        except Exception as error:
            if connection_lost(error):
                raise SessionAccepted(error, receipt) from error
            raise
        hero = next((row for row in roster['heroes'] if row['hero_id'] == hero_id), None)
        if hero is None or not hero['fresh'] or not hero['army_known'] or (not hero['busy'] and hero['hero_state'] == 0):
            raise RuntimeError('服务器已接受，但英雄出征状态未确认，已停止且不重复派出')
        if not any(row.get('army_id') == receipt['army_id'] and row.get('hero_id') == hero_id and
                   row.get('aim') == 1 and row.get('target_id') == target['target_id'] and
                   row.get('state') in (2, 3, 6) for row in schedule['stages']):
            raise RuntimeError('服务器已接受，但采集队伍及目标未确认，已停止且不重复派出')
        return receipt, roster

    def prepare_collection(self):
        """Prepare log ownership and refresh all barrack species before hero/target queries begin."""
        if self.response_log is None:
            self.response_log = GameResponseLog(ADB)
        # The barrack response includes all species; 411 only selects the response-generation probe.
        self.refresh(411)

    def refresh(self, unit=411, timeout=6):
        """Wait for a new server barrack response; a timeout never repeats spending commands."""
        previous = self.call('status', unit)['barrack_seq']
        self.call('refresh', unit)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.call('status', unit)
            if state['barrack_seq'] > previous:
                return state
            time.sleep(0.15)
        raise TimeoutError('No new barrack response; stopped')

    def action(self, operation, unit=411, timeout=6):
        """Check building availability before spending, then require an attributed successful response."""
        if operation not in {'train', 'speed'}:
            raise ValueError('Only training and acceleration are spending actions')
        sequence = 'train_seq' if operation == 'train' else 'speed_seq'
        result = 'train_ret' if operation == 'train' else 'speed_ret'
        response_unit = 'train_unit' if operation == 'train' else 'speed_unit'
        before = self.call('status', unit)
        if before.get('upgrade_known') is not True or before.get('upgrading') is not False:
            raise BarrackUnavailable('兵营正在升级或升级状态未确认，自动造兵已关闭；请升级完成后重新开启')
        previous = before[sequence]
        if operation == 'train':
            if self.response_log is None:
                self.response_log = GameResponseLog(ADB)
            self.response_log.drain()
        try:
            self.call(operation, unit)
        except Exception as error:
            if 'REA_BARRACK_TRAINING_UNAVAILABLE' in str(error):
                raise BarrackUnavailable('发送前发现兵营升级中或状态未确认，自动造兵已关闭') from error
            raise
        if operation == 'train':
            self.response_log.wait_training(unit, timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.call('status', unit)
            if state[sequence] > previous:
                if state[result] != 0:
                    raise RuntimeError(f'{operation} rejected by server: {state[result]}')
                if state[response_unit] != unit:
                    raise RuntimeError('响应兵种与请求不一致，已停止；请勿同时手动训练或加速')
                return self.refresh(unit)
            time.sleep(0.15)
        raise TimeoutError(f'{operation} result uncertain; do not repeat automatically')

    def set_trial_enabled(self, enabled):
        """Revoke queued trial reads and mutations immediately; no other feature can authorize this gate."""
        if self.script is not None:
            self.trial_generation = self.script.exports_sync.settrialenabled(bool(enabled))

    def trial_call(self, operation, arguments=(), generation=None):
        """Submit a fixed native trial operation with bounded numeric parameters, never UI-provided Lua."""
        operations = {'begin','query_profile','query_available','select','challenge','skip','ack','return_after_win','status'}
        if operation not in operations or any(type(v) is not int or not 0 <= v <= 100000000 for v in arguments):
            raise ValueError('Invalid trial operation or parameters')
        source = 'return REA_TRIAL.' + operation + '(' + ','.join(map(str, arguments)) + ')'
        spending = False if operation in {'ack','status'} else 'trial'
        with self.lock:
            value = self.script.exports_sync.query(source, spending, 1, generation)
        return value if operation == 'ack' else json.loads(value)

    def trial_action(self, operation, generation, cancelled):
        """Attribute one native trial acknowledgement; successful skip requests still require a separate win/lose push."""
        from trial_receipts import wait_trial_receipt, TrialRejected
        if cancelled():
            raise InterruptedError('试炼已关闭，尚未发送请求')
        if operation == 'return_after_win':
            return self.trial_call(operation, generation=generation)
        if self.response_log is None:
            self.response_log = GameResponseLog(ADB)
        self.response_log.drain()
        receipt = self.trial_call(operation, generation=generation)
        kind = {'query_profile':'profile','query_available':'available'}.get(operation, operation)
        ret = wait_trial_receipt(self.response_log, kind, receipt, cancelled)
        self.trial_call('ack', (receipt['code'], ret))
        if ret != 0:
            raise TrialRejected(kind, ret)
        return {**receipt, 'ret':ret}


    def set_report_enabled(self, enabled):
        """Immediately revoke queued timer-owned military report requests without changing other gates."""
        if self.script is not None:
            self.report_generation = self.script.exports_sync.setreportenabled(bool(enabled))

    def player_call(self, operation, target):
        """Invoke one fixed public-profile adapter operation, with no arbitrary Lua or spending permission."""
        from player_query import validate_player_id
        if operation not in {'resolve', 'lookup', 'profile', 'snapshot', 'identity'}:
            raise ValueError('Invalid player query operation')
        target = validate_player_id(target)
        with self.lock:
            value = self.script.exports_sync.query(f'return {getattr(self,"player_api","REA_PLAYER_QUERY")}.{operation}({target})')
        return json.loads(value)

    def _install_player_adapter(self):
        """Install idempotent navigation attribution before exposing the public-profile adapter."""
        self.script.exports_sync.query((ROOT/'player_query_ui.lua').read_text(encoding='utf-8'))
        self.script.exports_sync.query('REA_PLAYER_QUERY_UI.claim();return "profile_ui_owned"')
        self.script.exports_sync.query((ROOT/'player_query_runtime.lua').read_text(encoding='utf-8'))

    @contextmanager
    def _player_query_scope(self, cancelled):
        """Cancel helper work on native manual queries and always release local operation ownership."""
        def check():
            """Reuse existing receipt waits; this local check never sends a server request."""
            if cancelled():return True
            with self.lock:
                self.script.exports_sync.query('if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.check()end;return "checked"')
            return False
        try:
            yield check
        except RuntimeError as exc:
            # A decoded server rejection completes the outstanding request; a timeout does not.
            if '服务器拒绝' in str(exc) and self.script is not None:
                with contextlib.suppress(Exception),self.lock:
                    self.script.exports_sync.query('if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.finish(true)end;return "rejected"')
            raise
        finally:
            if self.script is not None:
                with contextlib.suppress(Exception),self.lock:
                    self.script.exports_sync.query('if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.finish()end;return "finished"')

    def league_query_call(self, operation, value=0):
        """Allow only bounded manual league browsing operations and session-local member handles."""
        operations={'leagues','league_snapshot','roster','roster_snapshot','member','member_snapshot','member_identity'}
        if operation not in operations or type(value) is not int or not 0<=value<=9007199254740991:
            raise ValueError('Invalid league browsing operation')
        with self.lock:
            result=self.script.exports_sync.query(f'return REA_LEAGUE_QUERY.{operation}({value})')
        return json.loads(result)

    def query_league_members(self, operation, value, cancelled):
        """Install passive adapters lazily, then execute exactly one manually requested browsing exchange."""
        from league_query import query_league
        if operation not in {'leagues','roster','member'} or type(value)is not int or not 0<=value<=9007199254740991:
            raise ValueError('Invalid league browsing operation')
        if cancelled():raise InterruptedError('联盟查询已取消')
        if not self.league_query_installed:
            with self.lock:
                self._install_player_adapter()
                self.script.exports_sync.query((ROOT/'league_query_runtime.lua').read_text(encoding='utf-8'))
            self.league_query_installed=True
        scope=identity=None
        if operation=='member':
            scope=self.map_index_call('context');identity=self.league_query_call('member_identity',value)
            cached=self.profile_cache.get(scope,identity=identity)
            if cached is not None:return cached
        with self._player_query_scope(cancelled) as check:
            snapshot=query_league(self,GameResponseLog(ADB),operation,value,check)
        return self._save_player_profile(scope,snapshot,identity)if operation=='member'else snapshot

    def ensure_map_index(self):
        """Install passive map/index adapters once; installation never sends a region or player request."""
        if not self.map_index_installed:
            with self.lock:
                self._install_player_adapter()
                self.script.exports_sync.query((ROOT/'map_index_runtime.lua').read_text(encoding='utf-8'))
            self.map_index_installed=True

    def map_index_call(self, operation, arguments=()):
        """Read only fixed local map-index operations, with numeric exact-region attribution parameters."""
        if operation not in {'context','plan','cached','region_read','profile_snapshot'} or any(
                type(v)is not int or not 0<=v<=100000000 for v in arguments):
            raise ValueError('Invalid map index operation')
        self.ensure_map_index()
        with self.lock:
            result=self.script.exports_sync.query('return REA_MAP_INDEX.'+operation+'('+','.join(map(str,arguments))+')')
        return json.loads(result)

    def query_map_index_region(self, region, cancelled):
        """Reuse the existing bounded regional read/restore scope without changing camera or spending gates."""
        if cancelled():raise InterruptedError('搜索已停止')
        x,y=region['x'],region['y']
        with self._hunt_region_scope(x,y)as state:
            return self.map_index_call('region_read',(state['seq'],x,y))

    def query_map_index_player(self, scope, row, cancelled):
        """Use the exact-identity local cache first; keep misses silent and cancel concurrent native browsing."""
        from map_index_store import checked_player,scope_key
        checked_player(row)
        if cancelled():raise InterruptedError('玩家查询已取消')
        self.ensure_map_index()
        if scope_key(self.map_index_call('context'))!=scope_key(scope):raise RuntimeError('地图已改变，请重新加载本地记录')
        cached=self.profile_cache.get(scope,identity=row['identity'])
        if cached is not None:return cached
        with self._player_query_scope(cancelled) as check:
            snapshot=self._query_map_index_player(scope,row,check)
        return self._save_player_profile(scope,snapshot,row['identity'])

    def _query_map_index_player(self, scope, row, cancelled):
        """Fetch one saved player's fresh profile only after a click and exact current-map validation."""
        from map_index_store import checked_player,scope_key
        from player_query import wait_player_receipt
        checked_player(row)
        if cancelled():raise InterruptedError('玩家查询已取消')
        if scope_key(self.map_index_call('context'))!=scope_key(scope):raise RuntimeError('地图已改变，请重新加载本地记录')
        uin,openid,platform,mobile=row['identity']
        # Decimal byte escapes are Lua-safe even for quotes, backslashes and non-ASCII identity text.
        quoted='"'+''.join('\\%03d'%b for b in openid.encode('utf-8'))+'"'
        source=f'return REA_MAP_INDEX.profile({{{uin},{quoted},{platform},{mobile}}})'
        log=GameResponseLog(ADB);log.drain()
        if cancelled():raise InterruptedError('玩家查询已取消')
        with self.lock:meta=json.loads(self.script.exports_sync.query(source))
        wait_player_receipt(log,meta['code'],0,cancelled,owner=True)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if cancelled():raise InterruptedError('玩家查询已取消')
            result=self.map_index_call('profile_snapshot')
            if result['ready']:return result
            time.sleep(.1)
        raise TimeoutError('玩家资料未能确认，未显示旧数据')

    def query_player(self, target, cancelled):
        """Reuse a scoped public-ID cache or query once and bind its resolved identity for later member exports."""
        from player_query import query_player, validate_player_id
        target = validate_player_id(target)
        if cancelled():
            raise InterruptedError('玩家查询已取消')
        scope=self.map_index_call('context')
        cached=self.profile_cache.get(scope,user_id=target)
        if cached is not None:return cached
        with self.lock:
            self._install_player_adapter()
        with self._player_query_scope(cancelled) as check:
            snapshot=query_player(self, GameResponseLog(ADB), target, check)
            identity=self.player_call('identity',target)
        return self._save_player_profile(scope,snapshot,identity)

    def report_call(self, operation, generation=None):
        """Invoke only fixed report operations; both list refresh and receive require this timer's gate."""
        if operation not in {'refresh','confirm','claim'}:
            raise ValueError('Invalid military report operation')
        with self.lock:
            value=self.script.exports_sync.query('return REA_REPORT.'+operation+'()',
                False if operation=='confirm'else'report',1,generation)
        return json.loads(value)

    def report_request(self, operation, generation, cancelled):
        """Submit a single native operation and wait for its exact request/response, never resending."""
        from report_receipts import wait_report_receipt, ReportResponseLog
        if cancelled():raise InterruptedError('自动领取军报已关闭，未发送')
        report_log=ReportResponseLog(ADB)
        report_log.drain()
        self.report_call(operation,generation)
        return wait_report_receipt(report_log,operation,cancelled)

    def refresh_reports(self, generation, cancelled):
        """Confirm one full list response and its new native cache; local waiting creates no extra requests."""
        self.report_request('refresh',generation,cancelled)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if cancelled():raise InterruptedError('自动领取军报已关闭')
            snapshot=self.report_call('confirm')
            if snapshot['ready']:return snapshot
            time.sleep(.1)
        raise TimeoutError('军报响应成功但列表未更新；停止，不重发')

    def claim_reports(self, generation, cancelled):
        """Receive all eligible ground-world report rewards only after a fresh list and explicit timer permission."""
        return self.report_request('claim',generation,cancelled)

    def close(self):
        """Remove the caller API, detach hooks, and release the process even after an RPC failure."""
        if self.script is not None:
            # Restore native browsing before other feature teardown can fail independently.
            with contextlib.suppress(Exception):
                self.script.exports_sync.query('if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.close()end;return "profile_ui_restored"')
            try:
                self.set_enabled(False)
                self.set_hero_enabled(False)
                self.set_collection_enabled(False)
                self.set_hunt_enabled(False)
                self.set_league_enabled(False)
                self.set_beacon_enabled(False)
                self.set_trial_enabled(False)
                self.set_report_enabled(False)
                self.script.exports_sync.bindsession(False)
                if not self.preserve_reconnect:
                    self.script.exports_sync.query('if REA_HUNT_RECONNECT then REA_HUNT_RECONNECT.close();REA_HUNT_RECONNECT=nil end;return "reconnect_witness_closed"')
                self.script.exports_sync.query('if REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.close()end;REA_MAP_INDEX=nil;REA_LEAGUE_QUERY=nil;REA_PLAYER_QUERY=nil;REA_REPORT=nil;if REA_TRIAL then REA_TRIAL.close();REA_TRIAL=nil end;'
                                               'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.beacon_close then REA_AUTO_INFANTRY.beacon_close() end;'
                                               'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.league_close then '
                                               'REA_AUTO_INFANTRY.league_close() end;'
                                               'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.hunt_close then '
                                               'REA_AUTO_INFANTRY.hunt_close() end;'
                                               'if REA_AUTO_INFANTRY and REA_AUTO_INFANTRY.collect_close then '
                                               'REA_AUTO_INFANTRY.collect_close() end;_G.REA_AUTO_INFANTRY=nil;'
                                               '_G.REA_HELPER_SESSION_VALID=nil; return "closed"')
                self.script.exports_sync.close()
            except Exception:
                pass
            finally:
                with contextlib.suppress(Exception):
                    self.script.unload()
                self.script = None
        if self.session is not None:
            with contextlib.suppress(Exception):
                self.session.detach()
            self.session = None
        if self.forward_port is not None:
            port, self.forward_port = self.forward_port, None
            with contextlib.suppress(Exception):
                frida.get_device_manager().remove_remote_device(f'127.0.0.1:{port}')
            with contextlib.suppress(Exception):
                adb('forward', '--remove', f'tcp:{port}', timeout=5)
        release_role(self.role_handle)
        self.role_handle = None
        self.role_id = None
        if self.mutex_handle is not None:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.ReleaseMutex(self.mutex_handle)
            kernel.CloseHandle(self.mutex_handle)
            self.mutex_handle = None
