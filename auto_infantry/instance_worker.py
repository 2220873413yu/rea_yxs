"""Run the second tab's login and automation through private parent/child pipes."""
import json
import queue
import sys
import threading
import time

from collection import CollectionOptions
from hunt_reconnect import log_reconnect
from instance_config import INSTANCE_DIRECTORY
from login_session import LoginSession
from monster import HuntOptions


def run_action(worker, command):
    """Use the same validated switches and request checks as the first tab."""
    name = command['action']
    enabled = command.get('enabled', False)
    if name == 'enabled':
        worker.switch(enabled, tuple(command['units']), use_training_speed=command['training_speed'])
    elif name == 'collect_enabled':
        if enabled and worker.collection_review_pending:
            raise ValueError('请先在雷电 1 核对采集队伍，再解除暂停')
        options = CollectionOptions(**command['options']) if enabled else None
        if enabled:
            worker.set_recovery_mode(command['mode'])
        worker.switch_collection(enabled, options)
    elif name == 'collect_reviewed':
        with worker.guard:
            if worker.collection_review_pending:
                worker.collection_review_pending = worker.collection.uncertain = False
                worker.publish(collection_review_pending=False, collection_status='已解除暂停，可手动开启自动采集。')
    elif name == 'hero_enabled':
        if enabled:
            worker.set_recovery_mode(command['mode'])
        worker.switch_hero(enabled, tuple(command['heroes']))
    elif name == 'hunt_enabled':
        worker.switch_hunt(enabled, HuntOptions(command['radius']) if enabled else None)
    elif name == 'league_enabled':
        worker.league.switch(enabled)
    elif name == 'beacon_enabled':
        worker.beacon.switch(enabled, tuple(command['kinds']))
    elif name == 'report_enabled':
        worker.report.switch(enabled)
    elif name == 'hunt_auto_start':
        worker.hunt.start_on_refresh(command['hunt_epoch'], HuntOptions(command['radius']))
    else:
        checks = {
            'collect_check': worker.collection.request_check,
            'hunt_check': worker.hunt.request_check,
            'league_check': worker.league.request_check,
            'beacon_check': worker.beacon.request_check,
            'hero_refresh': worker.request_hero_refresh,
            'attributes_refresh': worker.request_collection_attributes,
        }
        checks[name]()


def main():
    """Forward only current-session events and keep delayed reconnect plans inside this process."""
    if INSTANCE_DIRECTORY is None:
        raise RuntimeError('后台进程未指定第二台雷电')
    INSTANCE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    commands = queue.Queue()
    events = queue.Queue()
    session = LoginSession(events)
    disconnected = threading.Event()
    retry = None
    ready = False

    def read_commands():
        """Queue requests while the login worker runs and request shutdown when the parent exits."""
        try:
            for line in sys.stdin:
                commands.put(json.loads(line))
        finally:
            disconnected.set()
            commands.put(None)

    def emit(**event):
        """Publish role metadata and outcomes over stdout, excluding private reconnect data."""
        event.setdefault('session_epoch', session.epoch)
        print(json.dumps(event, ensure_ascii=True), flush=True)

    def open_session(mode='connect', selection=None):
        """Invalidate old commands before changing the active role or reconnecting it."""
        nonlocal retry, ready
        retry = None
        ready = False
        session.request(mode, selection)
        emit(session_reset=True, login_busy=True, ready=False)

    threading.Thread(target=read_commands, daemon=True).start()
    try:
        open_session()
        while True:
            try:
                command = commands.get(timeout=.08)
            except queue.Empty:
                command = {}
            if disconnected.is_set() or command is None or command.get('operation') == 'close':
                return
            if command:
                try:
                    operation = command['operation']
                    if operation == 'session':
                        mode, selection = command['mode'], command.get('selection')
                        if mode not in {'connect', 'account_save', 'account_switch', 'account_qr'}:
                            raise ValueError('第二台雷电不支持此账号操作')
                        if mode == 'account_qr':
                            selection = tuple(selection)
                        open_session(mode, selection)
                    elif operation == 'action' and command['epoch'] == session.epoch and ready and session.worker:
                        run_action(session.worker, command)
                except Exception as error:
                    feature = command.get('action')
                    state = {feature: False} if feature in {'enabled', 'collect_enabled', 'hero_enabled', 'hunt_enabled',
                                                            'league_enabled', 'beacon_enabled', 'report_enabled'} else {}
                    emit(**state, status='操作未完成：' + str(error).splitlines()[0][:200])
            while True:
                try:
                    event = events.get_nowait()
                except queue.Empty:
                    break
                if event.get('session_epoch') != session.epoch:
                    continue
                plan = event.pop('delayed_reconnect', None)
                if plan is not None:
                    if any(reason in plan['reason'] for reason in ('account_identity_changed', 'account_unavailable')):
                        log_reconnect('helper_role_changed', '检测到手动换号，重新读取，自动功能关闭')
                        open_session()
                    else:
                        retry = plan
                        log_reconnect('helper_reconnect_scheduled', plan['reason'])
                        emit(status='连接异常，等待原账号与地图恢复后自动核对一次。')
                    continue
                if 'ready' in event:
                    ready = event['ready']
                emit(**event)
            if retry is not None and time.monotonic() >= retry['deadline']:
                log_reconnect('helper_reconnect_attempt', '等待时间已到，检查原游戏进程与会话')
                open_session('hunt_reconnect', retry)
    finally:
        session.close()
        while session.pending_shutdown():
            time.sleep(.08)


if __name__ == '__main__':
    main()
