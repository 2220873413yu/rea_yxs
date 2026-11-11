"""Serial multi-team hunting using native capacity and run-scoped weak-coordinate exclusions."""
import time
from contextlib import nullcontext

from collection_wakeup import CollectionWakeup
from monster import HuntOptions, HuntReplan, default_formation, ordered_targets, ring_for
from monster_discovery import MonsterDiscovery
from monster_refresh import MonsterRefresh
from region_conflict import RegionConflict,RegionRestoreConflict
from hunt_reconnect import SessionUnsent, SessionAccepted, connection_lost


class MonsterService:
    """Manage attributed armies independently; uncertain spending never grants an automatic retry."""

    def __init__(self, owner):
        self.owner = owner
        self.enabled = False
        self.epoch = 0
        self.options = HuntOptions()
        self.active = {}
        self.uncertain = False
        self.completed = set()
        self.ignored = set()
        self.waiting = {}
        self.due = float('inf')
        self.poll_due = 0
        self.signature = None
        self.wakeup = CollectionWakeup()
        self.candidates = None
        self.home = None
        self.hero_signature = None
        self.discovery = MonsterDiscovery()
        self.refresh = MonsterRefresh()
        self.refresh_round = 0
        self.auto_refresh = MonsterRefresh()
        self.auto_due = 0
        self.auto_suspended = False
        self.auto_block_notified = False
        self.auto_start_epoch = None
        self.restored_schedule_options = None
        self.search_paused = False

    def switch(self, enabled, options=None):
        """Clear weak exclusions on enable and revoke old commands while retaining accepted armies."""
        with self.owner.guard:
            if enabled:
                if self.uncertain:
                    raise RuntimeError('上次打野请求结果不明，请先核对游戏并重启助手')
                if not isinstance(options, HuntOptions):
                    raise ValueError('打野范围无效')
                self.options = options
                self.ignored.clear()
                self.discovery = MonsterDiscovery()
                if self.auto_suspended:
                    self.auto_refresh = MonsterRefresh()
                    self.auto_due = 0
                    self.auto_suspended = False
            self.enabled = bool(enabled) and not self.owner.closing.is_set()
            self.epoch += 1
            self.auto_start_epoch = None
            self.restored_schedule_options = None
            self.due = 0 if self.enabled else float('inf')
            self.wakeup = CollectionWakeup()
            self.candidates = None
            self.waiting.clear()
            self.search_paused = False
            self.signature = None
            self.poll_due = 0
            self.refresh = MonsterRefresh()
            if not self.active:
                self.home = None
            if self.owner.connection is not None:
                self.owner.connection.set_hunt_enabled(self.enabled)

    def request_check(self):
        """Recheck temporary blockers without clearing confirmed weak coordinates from the current run."""
        with self.owner.guard:
            if self.enabled:
                self.search_paused = False
                self.wakeup.pending = True
                self.candidates = None
                self.waiting.clear()
                self.discovery.rescan()

    def automatic_start_blocked(self):
        """An unconfirmed departure or skip remains stopped; a refresh time never authorizes replaying it."""
        return self.uncertain or any(row.get('skip_attempted') and not row.get('skipped')
                                     for row in self.active.values())

    def scheduled_start_tick(self, connection, now):
        """Check a monotonic one-shot deadline, confirming the local server clock only when that deadline arrives."""
        if not getattr(self.owner, 'allow_scheduled_hunt', True):
            return
        if self.automatic_start_blocked():
            if not self.auto_block_notified:
                self.auto_block_notified = True
                self.owner.publish(hunt_auto_status='定时开启已暂停：上次出征或跳过战斗结果不明，请先核对游戏',
                                   action='hunt_auto_start_blocked')
            return
        self.auto_block_notified = False
        if self.auto_suspended or now < self.auto_due:
            return
        try:
            clock = connection.hunt_call('hunt_refresh_clock')
            crossed = self.auto_refresh.observe(clock['server_now_ms'], clock['refresh_times'])
            next_ms = self.auto_refresh.next_ms
            self.auto_due = (time.monotonic() + (next_ms - clock['server_now_ms']) / 1000
                             if next_ms is not None else float('inf'))
            self.owner.publish(hunt_auto_next_ms=next_ms)
            if crossed:
                self.auto_refresh.consume()
                with self.owner.guard:
                    if not self.enabled and not self.owner.closing.is_set() and not self.automatic_start_blocked():
                        # The UI validates its latest scope before opening the real generation gate.
                        self.auto_start_epoch = self.epoch
                        self.owner.publish(hunt_auto_start_epoch=self.epoch, action='hunt_auto_start_due',
                                           hunt_status='已到地图刷新时刻，等待按当前面板范围自动开启打野')
        except Exception as error:
            if connection_lost(error):
                raise
            self.auto_suspended = True
            self.auto_start_epoch = None
            self.auto_due = float('inf')
            self.owner.publish(hunt_auto_status='定时开启已暂停：' + str(error).splitlines()[0], error=str(error))

    def start_on_refresh(self, epoch, options):
        """Accept one current UI scope only if the scheduled request still belongs to this stopped, safe session."""
        with self.owner.guard:
            if (self.enabled or epoch != self.epoch or epoch != self.auto_start_epoch or
                    self.owner.closing.is_set() or self.auto_suspended or
                    self.owner.connection is None or self.automatic_start_blocked()):
                return False
            self.switch(True, self.restored_schedule_options or options)
            self.refresh.pending = True
            self.owner.publish(hunt_enabled=True, action='hunt_auto_start', radius=self.options.radius,
                               hunt_status='已按地图刷新时刻自动开启打野，正在确认服务器队伍与实际目标')
            return True

    def observe(self, roster):
        """Wake on cached hero eligibility changes, preserving weak exclusions across every response."""
        signature = tuple(sorted((r['hero_id'], r.get('busy'), r.get('hero_state'), r.get('finish_ms'),
                                  r.get('remaining_ms', 0) <= 0, r.get('power')) for r in roster['heroes']))
        if self.enabled and self.hero_signature is not None and self.hero_signature != signature:
            self.search_paused = False
            self.wakeup.pending = True
            self.candidates = None
            self.waiting.clear()
        self.hero_signature = signature

    def alive(self, epoch):
        """Prevent reads from authorizing actions after a stop or off/on transition."""
        return self.enabled and self.epoch == epoch and not self.owner.closing.is_set()

    def publish(self, message, **extra):
        """Publish operator-facing status and credential-free action receipts."""
        self.owner.publish(hunt_status=message, **extra)

    def poll(self, connection, now):
        """Reuse the local watch for clock hints and real changes, deferring timed rescans while capacity is full."""
        if now < self.poll_due:
            return
        self.poll_due = now + 1
        watch = connection.hunt_call('hunt_watch', (self.options.radius,))
        if 'refresh_times' in watch and self.refresh.observe(watch['server_now_ms'], watch['refresh_times']):
            full = (watch.get('queue_known') is True and type(watch.get('queue_used')) is int and
                    type(watch.get('queue_limit')) is int and watch['queue_used'] >= watch['queue_limit'])
            if not full:
                self.search_paused = False
                self.wakeup.pending = True
            else:
                self.publish('已到地图配置刷新时刻，等待出征空位后重新扫描；是否刷新以服务器返回为准')
        self.discovery.merge(watch['candidates'])
        home = (watch['home_x'], watch['home_y'])
        if self.home is not None and home != self.home:
            raise RuntimeError('主城位置发生变化，请核对范围后重新开启打野')
        self.home = home
        signature = (watch['seq'], home, tuple(watch.get('troops', ())), watch.get('queue_used'), watch.get('queue_limit'),
                     tuple(sorted((r['target_id'], r['config_id'], r['visible'], r['idle']) for r in watch['candidates'])),
                     watch.get('queue_known'))
        # A changing camera/candidate cache alone must not restart searches after persistent region conflicts.
        state_changed=(self.signature is not None and
                       (self.signature[:5]!=signature[:5] or self.signature[6]!=signature[6]))
        if self.signature is not None and self.signature != signature and (not self.search_paused or state_changed):
            self.search_paused = False
            self.wakeup.pending = True
            self.candidates = None
            self.waiting.clear()
            if (self.discovery.regions is not None and self.discovery.cursor == len(self.discovery.regions) and
                    (watch['seq'] != self.signature[0] or
                     (type(watch.get('queue_used')) is int and type(self.signature[3]) is int and
                      watch['queue_used'] < self.signature[3]))):
                self.discovery.rescan()
        self.signature = signature

    def publish_snapshot(self, schedule):
        """Display all managed armies against total native occupancy, including manual/returning armies."""
        rows = [{**self.active[r['army_id']], **r} for r in schedule['stages'] if r['army_id'] in self.active]
        self.owner.publish(hunt_snapshot={'queue_known': schedule['queue_known'], 'queue_used': schedule['queue_used'],
                                         'queue_limit': schedule['queue_limit'], 'managed': len(self.active),
                                         'ignored': len(self.ignored), 'rows': rows,
                                         'scanned': self.discovery.cursor, 'regions': len(self.discovery.regions or []),
                                         'discovered': len(self.discovery.records),
                                         'server_now_ms': schedule['server_now_ms']})

    def tick(self, connection):
        """Process arrivals and configured rescan hints, then discover or dispatch only with confirmed free capacity."""
        if self.owner.closing.is_set():
            return
        self.scheduled_start_tick(connection, time.monotonic())
        with self.owner.guard:
            if not self.enabled or self.owner.closing.is_set():
                return
            epoch, generation = self.epoch, connection.hunt_generation
        try:
            now = time.monotonic()
            self.poll(connection, now)
            with self.owner.guard:
                if not self.alive(epoch) or not self.wakeup.begin(now, self.due):
                    return
                self.due = float('inf')
            roster = connection.refresh_heroes()
            self.owner.publish(hero_roster=roster)
            schedule = connection.hunt_call('hunt_schedule')
            with self.owner.guard:
                if not self.alive(epoch):
                    return
                self.due = self.wakeup.schedule(schedule, time.monotonic())
            if self.advance_armies(connection, schedule, epoch, generation) or not self.alive(epoch):
                return
            if self.search_paused:
                self.publish('新增搜索已暂停；已确认队伍继续跟踪，等待部队/英雄状态变化、刷新时刻或立即检查')
                return
            if not schedule['can_skip']:
                raise RuntimeError('当前账号未具备游戏原生跳过战斗权限，未派出')
            if (not schedule['queue_known'] or not schedule['queue_free'] or
                    schedule['queue_used'] >= schedule['queue_limit']):
                self.publish('出征额度已满或未知，地图刷新重扫待空位；等待服务器阶段时间或状态推送' if self.refresh.pending else
                             '出征额度已满或未知，等待空位、服务器阶段时间或状态推送')
                return
            if self.refresh.consume():
                self.refresh_round += 1
                self.discovery.records.clear()
                self.discovery.rescan()
                self.completed.clear()
                self.waiting.clear()
                self.candidates = None
                self.publish('按地图配置刷新提示开始重新扫描，逐个核实服务器实际目标')
            reserved = {r['target_id'] for r in schedule['monsters']} | {r['target_id'] for r in self.active.values()}
            if self.discovery.regions is None:
                self.discovery.plan(connection.hunt_call('hunt_scan_plan', (self.options.radius,))['regions'])
            if self.candidates is None:
                rows = connection.hunt_call('hunt_candidates', (self.options.radius,))
                self.discovery.merge(rows)
                self.candidates = ordered_targets(self.discovery.records.values(), self.options.radius,
                                                   self.completed, self.ignored, reserved)
            self.candidates = [r for r in self.candidates if r['target_id'] not in reserved and
                               r['target_id'] not in self.completed and (r['x'], r['y']) not in self.ignored and
                               (r['x'], r['y']) not in self.waiting]
            region = self.discovery.next_region(self.candidates[0]['distance'] if self.candidates else float('inf'))
            if region is not None:
                if not self.alive(epoch):
                    return
                self.publish(f'正在查询打野区域 {self.discovery.cursor + 1}/{len(self.discovery.regions)}，由近到远发现目标')
                rows = connection.query_hunt_region(region, self.options.radius, generation)
                with self.owner.guard:
                    if not self.alive(epoch):
                        return
                    self.discovery.accept(region, rows)
                    self.candidates = None
                    self.due = 0
                self.publish_snapshot(schedule)
                return
            if not self.candidates:
                self.schedule_waiting()
                self.publish('范围内其余目标已检查，暂缺可用英雄、兵力或完整战力数据，等待状态变化' if self.waiting else
                             f'范围内暂无可打点；区域已查{self.discovery.cursor}/{len(self.discovery.regions)}，'
                             f'独立记录{len(self.discovery.records)}个目标；等待状态变化或手动检查')
                return
            candidate = self.candidates.pop(0)
            ring = ring_for(candidate['distance'], self.options.radius)
            self.publish(f"正在检查主城{ring}格内目标（{candidate['x']},{candidate['y']}），优先近处")
            connection.prepare_collection()
            self.attack_with_region_recheck(connection,candidate,schedule,epoch,generation)
        except HuntReplan:
            with self.owner.guard:
                if not self.alive(epoch):return
                self.search_paused=True
                self.candidates=None
                self.wakeup.pending=False
            self.publish('派出前英雄或资料持续变化，暂停新增搜索；未发送出征，现有队伍继续跟踪，等待状态变化或立即检查')
        except RegionConflict as error:
            if self.automatic_start_blocked():
                self.stop_on_error(epoch,error)
                return
            with self.owner.guard:
                if not self.alive(epoch):return
                self.search_paused=True
                self.candidates=None
                self.wakeup.pending=False
            self.publish('地图响应冲突，暂停新增搜索；已确认出征不重发，现有队伍继续跟踪；等待状态变化或立即检查',
                         action='hunt_region_pause',region_phase='restore' if isinstance(error,RegionRestoreConflict) else 'read',
                         region_error=str(error))
        except Exception as error:
            self.stop_on_error(epoch,error)

    def stop_on_error(self,epoch,error):
        """Stop session/spending failures independently of recoverable read conflicts, preserving unknown-result latches."""
        with self.owner.guard:
            if not self.alive(epoch):return
            if connection_lost(error):
                # Preserve settled intent until the worker captures its default-off replacement checkpoint.
                raise error
            self.switch(False)
        note = ('；请求结果不明，不会定时恢复' if self.automatic_start_blocked() else
                '；定时开启已暂停，请检查连接' if self.auto_suspended else
                '；下个地图刷新时刻将尝试自动开启')
        self.publish('打野已停止：' + str(error).splitlines()[0] + note, hunt_enabled=False, error=str(error))

    def restore_reconnect(self, connection, plan, roster, schedule):
        """Re-adopt only confirmed native armies, preserving exclusions without submitting new departures here."""
        from hunt_reconnect import reconcile
        active, completed = reconcile(plan, roster, schedule)
        with self.owner.guard:
            if self.owner.closing.is_set():
                raise InterruptedError('重连恢复已取消')
            for row in active.values():
                connection.hunt_call('hunt_resume', (row['target_id'], row['hero_id'], row['army_id'], int(row['skipped'])))
            self.options = plan['options']
            self.active, self.completed = active, completed
            self.ignored = set(plan['ignored'])
            self.home = plan['home']
            self.refresh_round = plan['refresh_round']
            self.epoch += 1
            self.enabled = plan['enabled']
            self.uncertain = False
            self.due = 0
            self.poll_due = 0
            self.candidates = None
            self.discovery = MonsterDiscovery()
            self.waiting.clear()
            self.wakeup = CollectionWakeup()
            self.search_paused = plan['search_paused']
            self.refresh = plan['refresh']
            self.auto_refresh = plan['auto_refresh']
            self.restored_schedule_options = self.options if plan['scheduled'] and not self.enabled else None
            if plan['auto_start_pending']:
                # The old UI request was invalidated by disconnect. Reissue its one refresh hint.
                self.auto_refresh.pending = False
                self.auto_refresh.next_ms = 0
            self.auto_due = 0
            connection.set_hunt_enabled(self.enabled)
            self.owner.allow_scheduled_hunt = plan['scheduled']
            self.publish('同账号、同区服、同地图已核对部队，已恢复本轮打野' if self.enabled else
                         '同账号、同区服、同地图已核对部队，已恢复原打野刷新计划',
                         hunt_enabled=self.enabled, action='hunt_reconnect_resumed')
            self.publish_snapshot(schedule)

    def attack_with_region_recheck(self,connection,candidate,schedule,epoch,generation):
        """Repeat only an unsent target read once; restored-map failures and unknown actions never replay a departure."""
        for attempt in range(2):
            if not self.alive(epoch):return
            try:
                scope=connection.hunt_target_region(candidate,self.options.radius,generation) if 'logic_x' in candidate else nullcontext()
                with scope:self.attack_candidate(connection,candidate,schedule,epoch,generation)
                return
            except RegionRestoreConflict:raise
            except HuntReplan:
                if attempt or self.automatic_start_blocked():raise
                connection.refresh_heroes()
                self.publish('派出前英雄或资料已变化，重新核对并选人一次；未发送出征请求')
            except RegionConflict:
                if attempt or self.automatic_start_blocked():raise
                self.publish('目标区域有变化，重新核对一次；不复用旧详情或阵容')

    def attack_candidate(self, connection, candidate, schedule, epoch, generation):
        """Requery a loaded catalog target and preserve native eligibility, reservations and attributed receipts."""
        if not self.alive(epoch):
            return
        metrics = connection.query_monster(candidate['target_id'])
        t = metrics['target']
        with self.owner.guard:
            if not self.alive(epoch):
                return
            if any(t[k] != candidate[k] for k in ('target_id', 'config_id', 'x', 'y')):
                raise RuntimeError('野怪详情与地图候选不符，未派出')
            self.discovery.merge([t])
            if not (t['fresh'] and t['visible'] and t['idle']):
                self.candidates = None
                self.due = 0
                return
            reserved_heroes = {r['hero_id'] for r in self.active.values()}
            eligible = {**metrics, 'formations': [r for r in metrics['formations'] if r['hero_id'] not in reserved_heroes]}
            plan = default_formation(eligible)
            if plan is None:
                self.reject_plan(t, metrics, ring_for(candidate['distance'], self.options.radius), schedule)
                return
            self.uncertain = True
        try:
            receipt, after = connection.dispatch_hunt(t, plan, self.options.radius, generation)
        except (HuntReplan, SessionUnsent):
            # Only a typed native pre-send result can clear the action latch; RPC/receipt failures cannot.
            with self.owner.guard:self.uncertain = False
            raise
        except SessionAccepted as error:
            # A matched server success remains authoritative even if the following roster read disconnects.
            receipt = error.receipt
            with self.owner.guard:
                self.active[receipt['army_id']] = {**receipt, 'name': plan['name'], 'x': t['x'], 'y': t['y'],
                    'followers': plan['followers'], 'skipped': False, 'skip_attempted': False,
                    'refresh_round': self.refresh_round}
                self.uncertain = False
                self.owner.publish(action='hunt_dispatch', receipt=receipt)
            raise
        with self.owner.guard:
            self.active[receipt['army_id']] = {**receipt, 'name': plan['name'], 'x': t['x'], 'y': t['y'],
                                                'followers': plan['followers'], 'skipped': False, 'skip_attempted': False,
                                                'refresh_round': self.refresh_round}
            self.uncertain = False
            self.candidates = None
            if self.alive(epoch):
                self.due = 0
            self.owner.publish(hero_roster=after, action='hunt_dispatch', receipt=receipt)
            self.publish(f"已确认{plan['name']}＋{plan['followers']}名小兵出征（{t['x']},{t['y']}），继续核对剩余额度")

    def reject_plan(self, target, metrics, ring, schedule):
        """Exclude a proven weak coordinate or defer a temporary blocker, then continue other targets and regions."""
        point = (target['x'], target['y'])
        if metrics.get('strength_known') is True and metrics.get('can_win_full') is False:
            self.due = 0
            self.ignored.add(point)
            self.publish(f'本轮忽略（{point[0]},{point[1]}）：所有候选英雄满编仍未胜券在握，不再查询此坐标')
        else:
            self.waiting[point] = {'ring': ring}
            end = metrics.get('cooldown_ms', 0)
            if end > schedule['server_now_ms']:
                self.waiting[point]['due'] = time.monotonic() + (end - schedule['server_now_ms']) / 1000 + 1
            if any((r['x'], r['y']) not in self.waiting for r in self.candidates or []) or self.discovery.next_region() is not None:
                self.due = 0
            else:
                self.schedule_waiting()
            self.publish(f'暂时跳过（{point[0]},{point[1]}）：英雄/兵力不可用或战力数据不完整，不加入忽略名单')
        self.publish_snapshot(schedule)

    def schedule_waiting(self):
        """Consume each hero cooldown deadline once, preserving existing army timers without a poll loop."""
        now = time.monotonic()
        for point, wait in list(self.waiting.items()):
            due = wait.get('due')
            if due is not None and due <= now:
                del self.waiting[point]
                self.candidates = None
                self.due = 0
            elif due is not None:
                self.due = min(self.due, due)

    def advance_armies(self, connection, schedule, epoch, generation):
        """Reconcile every tracked army and skip at most one arrived team before any new departure."""
        stages = {r['army_id']: r for r in schedule['stages']}
        changed = False
        for army_id, active in list(self.active.items()):
            row = stages.get(army_id)
            if row is None:
                connection.hunt_call('hunt_release', (army_id,))
                if active.get('refresh_round', 0) == self.refresh_round:
                    self.completed.add(active['target_id'])
                del self.active[army_id]
                self.candidates = None
                changed = True
                continue
            if row['hero_id'] != active['hero_id'] or row['target_id'] != active['target_id'] or row['aim'] != 3:
                raise RuntimeError('打野队伍归属发生变化，不再自动操作')
        self.publish_snapshot(schedule)
        for army_id, active in list(self.active.items()):
            row = stages[army_id]
            if row['state'] != 3 or active['skipped']:
                continue
            if active['skip_attempted']:
                raise RuntimeError('上次跳过结果不明，不重复提交')
            with self.owner.guard:
                if not self.alive(epoch):
                    return True
                active['skip_attempted'] = True
            try:
                result = connection.skip_hunt(active, generation)
            except SessionUnsent:
                active['skip_attempted'] = False
                raise
            active['skipped'] = True
            self.owner.publish(action='hunt_skip', receipt=result)
            if not result['won']:
                raise RuntimeError('服务器结算为战败，已停止打野，请核对战报')
            self.publish(f"{active['name']}已跳过战斗并确认胜利，其他队伍继续独立处理")
            if self.alive(epoch):
                self.due = 0
            return True
        if changed and self.alive(epoch):
            self.search_paused=False
            self.due = 0
            self.publish('已有队伍返回，按当前服务器额度补队，重新优先近处目标')
        return False
