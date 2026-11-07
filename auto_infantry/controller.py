"""Bounded infantry decisions and a serial worker for the desktop toggle."""
import json
import math
import threading
import time
from datetime import datetime
from pathlib import Path

from connection import Connection, BarrackUnavailable
from units import UNIT_NAMES, checked_units
from hero_recovery import choose_recovery, verify_recovery
from hero_preferences import checked_heroes
from collection_service import CollectionService
from game_log import TrainingRejected
from monster_service import MonsterService
from league_service import LeagueService
from beacon_service import BeaconService


def owned_soldiers(state):
    """Count available plus army-assigned soldiers; both consume the server's per-species limit."""
    return state['count'] + state.get('deployed', 0)


class RunBudget:
    """Limit one enabled run using its initial real capacity gap, even if troops keep dying."""

    def __init__(self, state):
        self.limit = state['limit']
        gap = max(0, state['limit'] - owned_soldiers(state))
        self.trains = max(0, gap - state['pending'])
        self.speeds = gap * (math.ceil(state['duration_ms'] / 300000) + 1)

    def choose(self, state, use_training_speed=False):
        """Fill normal slots without items, or explicitly accelerate within the initial capacity budget."""
        if state['limit'] != self.limit:
            raise RuntimeError('兵种上限发生变化，已停止')
        if owned_soldiers(state) >= state['limit']:
            return 'complete'
        if not use_training_speed:
            capacity = state.get('queue_capacity')
            if type(capacity) is not int or capacity <= 0 or not 0 <= state['pending'] <= capacity:
                raise RuntimeError('训练位容量未知，已停止')
            if self.trains > 0 and owned_soldiers(state) + state['pending'] < state['limit'] and state['pending'] < capacity:
                return 'train'
            if state['pending'] > 0:
                return 'wait' if state['remaining_ms'] > 0 else 'refresh'
            raise RuntimeError('本轮训练次数已达上限，可能持续损兵；已停止')
        if state['items'] <= 0:
            raise RuntimeError('紫色五分钟训练加速已用完')
        if state['pending'] > 0:
            if state['remaining_ms'] <= 0:
                return 'refresh'
            if self.speeds <= 0:
                raise RuntimeError('本轮加速次数已达上限，已停止')
            return 'speed'
        if self.trains <= 0:
            raise RuntimeError('本轮训练次数已达上限，可能持续损兵；已停止')
        return 'train'

    def consume(self, action):
        """Reserve a spending attempt before submission so failures cannot grant a retry budget."""
        if action == 'train':
            if self.trains <= 0:
                raise RuntimeError('训练次数上限')
            self.trains -= 1
        elif action == 'speed':
            if self.speeds <= 0:
                raise RuntimeError('加速次数上限')
            self.speeds -= 1


class SelectionRun:
    """Keep independent capacity budgets while fairly scheduling only selected troop types."""

    def __init__(self, states, selected):
        self.selected = checked_units(selected)
        self.budgets = {unit: RunBudget(states[unit]) for unit in self.selected}
        self.completed = set()
        self.empty_refreshes = {unit: 0 for unit in self.selected}
        self.cursor = 0
        self.waiting = {}

    def next_unit(self):
        """Skip completed or sleeping troop types so one long training does not block another type."""
        for _ in self.selected:
            unit = self.selected[self.cursor % len(self.selected)]
            self.cursor += 1
            if unit not in self.completed and unit not in self.waiting:
                return unit
        return None


class Worker(threading.Thread):
    """Own one bridge and perform one state-verified action at a time until switched off."""

    def __init__(self, events):
        super().__init__(daemon=True)
        self.events = events
        self.closing = threading.Event()
        self.guard = threading.RLock()
        self.enabled = False
        self.use_training_speed = False
        self.hero_enabled = False
        self.hero_epoch = 0
        self.hero_due = 0
        self.hero_selected = ()
        self.hero_cursor = 0
        self.hero_refresh_requested = threading.Event()
        self.selected = (411,)
        self.epoch = 0
        self.step_delay = 0.3
        self.connection = None
        self.allow_scheduled_hunt = True
        self.log_path = Path(__file__).with_name('actions.jsonl')
        self.collection = CollectionService(self)
        self.hunt = MonsterService(self)
        self.league = LeagueService(self)
        self.beacon = BeaconService(self)
        self.recovery_authorized = ()
        self.hero_view_due = 0
        self.collection_queue_signature = None

    def poll_hero_view(self, connection):
        """Forward changed cached responses and passive pushes to the UI without querying the server."""
        now = time.monotonic()
        if now < self.hero_view_due:
            return
        self.hero_view_due = now + .25
        view = connection.hero_view()
        if view['changed']:
            roster = view['roster']
            self.hunt.observe(roster)
            self.league.observe(roster)
            self.beacon.observe(roster)
            if roster.get('queue_known'):
                signature = (roster['queue_used'], roster['queue_limit'])
                with self.guard:
                    if (self.collection.enabled and self.collection_queue_signature is not None and
                            signature != self.collection_queue_signature and signature[0] < signature[1]):
                        # An already received capacity/occupancy change wakes one confirmation, not a poll loop.
                        self.collection.wakeup.pending = True
                    self.collection_queue_signature = signature
            self.publish(hero_roster=roster)

    def publish(self, **event):
        """Send display updates and append action outcomes without account credentials."""
        self.events.put(event)
        if event.get('action') or event.get('error'):
            with self.log_path.open('a', encoding='utf-8') as log:
                log.write(json.dumps({'time': datetime.now().isoformat(), **event}, ensure_ascii=False) + '\n')

    def switch(self, enabled, selected=None, use_training_speed=False):
        """Freeze troop and item choices for one run; item use is opt-in on every new start."""
        with self.guard:
            if enabled:
                self.selected = checked_units(selected if selected is not None else self.selected)
                self.use_training_speed = bool(use_training_speed)
            self.enabled = bool(enabled) and not self.closing.is_set()
            self.epoch += 1
            if self.connection is not None:
                self.connection.set_enabled(self.enabled, self.selected, self.use_training_speed)

    def stop(self):
        """Revoke all feature action gates before detaching the owned connection."""
        self.closing.set()
        self.hunt.switch(False)
        self.league.switch(False)
        self.beacon.switch(False)
        self.collection.switch(False)
        self.switch_hero(False)
        self.switch(False)

    def wait_for_training(self, run, unit, state):
        """Schedule one server-duration confirmation without polling while this species is waiting."""
        delay = state['remaining_ms'] / 1000 + 3
        run.waiting[unit] = time.monotonic() + delay
        next_check = datetime.fromtimestamp(time.time() + delay).strftime('%H:%M:%S')
        self.publish(state=state, status=f'{UNIT_NAMES[unit]}正常训练中；下次检查 {next_check}（等待期间不查询兵营）')

    def switch_hero(self, enabled, selected=None):
        """Freeze an explicit hero selection and revoke all operations from the previous run."""
        with self.guard:
            if enabled:
                heroes = checked_heroes(selected if selected is not None else self.hero_selected)
                if not heroes:
                    raise ValueError('请至少勾选一个英雄')
                self.hero_selected = heroes
                self.hero_cursor = 0
            self.hero_enabled = bool(enabled) and not self.closing.is_set()
            self.hero_epoch += 1
            self.hero_due = 0
            self.sync_recovery_gate()

    def sync_recovery_gate(self):
        """Authorize the deduplicated union of normal recovery and the single active collection demand."""
        normal = self.hero_selected if self.hero_enabled else ()
        demand = self.collection.recovery_hero
        selected = checked_heroes(tuple(normal) + ((demand,) if demand else ()))
        if self.connection is not None and selected != self.recovery_authorized:
            self.connection.set_hero_enabled(bool(selected), selected)
            self.recovery_authorized = selected
            self.hero_due = 0
        return selected

    def switch_collection(self, enabled, options=None):
        """Control only collection and its own recovery demand, preserving normal recovery selections."""
        self.collection.switch(enabled, options)

    def switch_hunt(self, enabled, options=None):
        """Authorize hunting independently; a valid manual start also arms this account's refresh schedule."""
        self.hunt.switch(enabled, options)
        if enabled:
            self.allow_scheduled_hunt = True

    def request_collection_attributes(self):
        """Queue a read-only speed/load refresh on the same serial worker as all other game operations."""
        self.collection.attributes_requested.set()

    def request_hero_refresh(self):
        """Queue a read-only roster refresh on the shared worker instead of querying from the UI thread."""
        self.hero_refresh_requested.set()

    def hero_tick(self, connection):
        """Merge recovery sources and confirm one eligible hero item before allowing the next serial action."""
        with self.guard:
            if (not self.hero_enabled and not self.collection.recovery_hero) or self.closing.is_set() or time.monotonic() < self.hero_due:
                return
            epoch = (self.hero_epoch, self.collection.epoch)
            cursor = self.hero_cursor
            self.hero_due = time.monotonic() + 3
        try:
            roster = connection.refresh_heroes()
            self.publish(hero_roster=roster)
            queue_free = True
            if self.collection.recovery_hero:
                queue_free = connection.collection_call('collect_status')['queue_free']
            with self.guard:
                if epoch != (self.hero_epoch, self.collection.epoch) or self.closing.is_set():
                    return
                if self.collection.recovery_hero and not queue_free:
                    self.collection.queue_blocked = True
                self.collection.observe(roster)
                selected = self.sync_recovery_gate()
                generation = connection.hero_generation
                state, next_cursor, message = choose_recovery(roster, selected, cursor)
                self.publish(hero_status=message, recovery_for_collection=self.collection.recovery_hero is not None)
                # Queue submission is protected by the bridge's independent switch gate.
                if state is None:
                    return
                self.hero_cursor = next_cursor
            after = connection.recover_hero(state, generation)
            verify_recovery(state, after)
            self.publish(action='hero_speed', hero=state['hero_id'], hero_state=after,
                         hero_status=f"{state.get('name', state['hero_id'])}恢复进度已确认，继续监控",
                         recovery_for_collection=self.collection.recovery_hero is not None)
            with self.guard:
                self.collection.observe({'heroes': [after]} if self.collection.recovery_hero == after['hero_id'] else roster)
                self.sync_recovery_gate()
                if epoch != (self.hero_epoch, self.collection.epoch) or self.closing.is_set():
                    return False
                if after['remaining_ms'] > 0 or len(selected) > 1 or (self.collection.enabled and self.collection.run and self.collection.run.plan):
                    # A verified success permits the next item without a timer or troop-loop delay.
                    self.hero_due = 0
                    return True
                self.hero_due = time.monotonic() + 3
        except Exception as error:
            with self.guard:
                if epoch != (self.hero_epoch, self.collection.epoch):
                    return
                self.collection.switch(False)
                self.switch_hero(False)
            self.publish(hero_enabled=False, collect_enabled=False, error=str(error), hero_status='自动恢复已停止：' + str(error),
                         collection_status='共用恢复结果异常，采集已停止')

    def run(self):
        """Serialize hunting, troop runs, collection and shared recovery over one owned game connection."""
        connection = Connection()
        run = None
        run_epoch = None
        try:
            state = connection.open(on_status=lambda message: self.publish(ready=False, status=message), cancel=self.closing,
                                    on_account=lambda account: self.publish(account=account))
            self.connection = connection
            for unit in UNIT_NAMES:
                self.publish(state=connection.call('status', unit))
            self.league.tick(connection)
            self.beacon.tick(connection)
            self.publish(ready=True, status='已连接，自动造兵关闭')
            while not self.closing.is_set():
                self.poll_hero_view(connection)
                if self.collection.attributes_requested.is_set():
                    try:
                        self.collection.refresh_attributes(connection)
                    except Exception as error:
                        self.publish(collection_status='采集属性刷新失败：' + str(error))
                if self.hero_refresh_requested.is_set():
                    self.hero_refresh_requested.clear()
                    try:
                        self.publish(hero_roster=connection.refresh_heroes(), hero_list_status='英雄名单已刷新')
                    except Exception as error:
                        self.publish(hero_list_status='名单刷新失败：' + str(error))
                self.beacon.tick(connection)
                self.league.tick(connection)
                self.hunt.tick(connection)
                self.collection.tick(connection)
                if self.hero_tick(connection):
                    continue
                with self.guard:
                    active = self.enabled
                    selected = self.selected
                    epoch = self.epoch
                    use_training_speed = self.use_training_speed
                if not active:
                    run = None
                    self.closing.wait(0.15)
                    continue
                if run is None or run_epoch != epoch:
                    connection.refresh(selected[0])
                    states = {unit: connection.call('status', unit) for unit in selected}
                    run = SelectionRun(states, selected)
                    run_epoch = epoch
                with self.guard:
                    if not self.enabled or self.epoch != run_epoch or self.closing.is_set():
                        continue
                if run.waiting and min(run.waiting.values()) <= time.monotonic():
                    # One due query refreshes all species; do not query each waiting unit separately.
                    connection.refresh(selected[0])
                    run.waiting.clear()
                unit = run.next_unit()
                if unit is None:
                    if len(run.completed) != len(run.selected):
                        self.closing.wait(.15)
                        continue
                    connection.refresh(selected[0])
                    final_states = {unit: connection.call('status', unit) for unit in selected}
                    missing = {unit for unit, snapshot in final_states.items()
                               if owned_soldiers(snapshot) < snapshot['limit']}
                    if missing:
                        run.completed.difference_update(missing)
                        continue
                    for snapshot in final_states.values():
                        self.publish(state=snapshot)
                    self.switch(False)
                    self.publish(enabled=False, status='所选兵种已补满，已自动关闭')
                    continue
                state = connection.call('status', unit)
                if state['soldier_id'] != unit:
                    raise RuntimeError('状态兵种与选择不一致，已停止')
                if state.get('upgrade_known') is not True or state.get('upgrading') is not False:
                    self.switch(False)
                    self.publish(enabled=False, state=state,
                                 status='兵营正在升级或升级状态未确认，自动造兵已关闭；升级完成后请重新开启')
                    continue
                budget = run.budgets[unit]
                action = budget.choose(state, use_training_speed)
                if action == 'complete':
                    run.completed.add(unit)
                    self.publish(unit_done=unit, state=state, status=f'{UNIT_NAMES[unit]}已满，正在检查其他所选兵种')
                    continue
                if action == 'wait':
                    self.wait_for_training(run, unit, state)
                    continue
                if action == 'refresh':
                    if not use_training_speed:
                        # A due server confirmation that is still inconsistent must not start a tight retry loop.
                        raise RuntimeError('训练到期但服务器训练状态尚未更新，已停止；请稍后重新开启')
                    run.empty_refreshes[unit] += 1
                    if run.empty_refreshes[unit] > 10:
                        raise RuntimeError('训练完成状态未更新，已停止')
                    self.closing.wait(0.4)
                    state = connection.refresh(unit)
                    self.publish(state=state)
                else:
                    run.empty_refreshes[unit] = 0
                    budget.consume(action)
                    self.publish(status=f'正在训练{UNIT_NAMES[unit]}' if action == 'train' else f'正在为{UNIT_NAMES[unit]}使用一个五分钟训练加速')
                    before = state
                    try:
                        state = connection.action(action, unit)
                    except BarrackUnavailable as error:
                        self.switch(False)
                        self.publish(enabled=False, status=str(error))
                        continue
                    except TrainingRejected as error:
                        if action != 'train' or error.ret != 6015 or error.unit != unit:
                            raise
                        # Never retry the rejected command. Confirm that this species really reached its cap.
                        state = connection.refresh(unit)
                        if owned_soldiers(state) + state['pending'] < state['limit']:
                            raise RuntimeError('服务器返回训练上限，但兵营数量未能确认，已停止') from error
                        if owned_soldiers(state) >= state['limit']:
                            run.completed.add(unit)
                            self.publish(state=state, status=f'{UNIT_NAMES[unit]}已达上限，继续处理其他兵种')
                        elif state['pending'] > 0 and state['remaining_ms'] > 0:
                            if not use_training_speed:
                                self.wait_for_training(run, unit, state)
                            else:
                                self.publish(state=state, status=f'{UNIT_NAMES[unit]}训练数量已确认，继续处理现有训练')
                        else:
                            raise RuntimeError('训练上限响应后状态不明，已停止') from error
                        continue
                    except Exception:
                        with self.guard:
                            stopped = not self.enabled
                        if stopped:
                            run = None
                            continue
                        raise
                    if action == 'train' and state['pending'] <= before['pending'] and state['count'] <= before['count']:
                        raise RuntimeError('训练响应后未观察到队列或兵力增加，已停止')
                    if action == 'speed' and state['items'] != before['items'] - 1:
                        raise RuntimeError('道具扣量与预期不符，已停止')
                    if (action == 'speed' and state['pending'] >= before['pending'] and
                            state['count'] <= before['count'] and state['remaining_ms'] >= before['remaining_ms']):
                        raise RuntimeError('加速后未观察到训练进度变化，已停止')
                    self.publish(action=action, unit=unit, state=state, status='运行中')
                self.closing.wait(self.step_delay)
        except Exception as error:
            was_enabled = self.enabled
            try:
                self.hunt.switch(False)
                self.league.switch(False)
                self.beacon.switch(False)
                self.collection.switch(False)
                self.switch_hero(False)
                self.switch(False)
            except Exception:
                self.enabled = False
            if not self.closing.is_set():
                self.publish(enabled=False, hero_enabled=False, collect_enabled=False, hunt_enabled=False, league_enabled=False,
                             beacon_enabled=False, ready=False, error=str(error),
                             account_changed='Account session changed' in str(error),
                             hero_status='连接已停止，自动恢复关闭',
                             status=('已停止：' if was_enabled else '连接已停止：') + str(error))
        finally:
            self.connection = None
            connection.close()
            self.publish(closed=True)
