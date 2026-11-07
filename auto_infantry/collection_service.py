"""Serial collection planning and property refresh; recovery is delegated to the existing worker."""
import threading
import time
from dataclasses import replace

from collection import CollectionOptions, CollectionRun, candidate_targets, best_collector, quantity_allowed, collection_slot_available, active_resource_targets, RESOURCE_NAMES
from collection_wakeup import CollectionWakeup
from collection_display import team_snapshot
from game_log import ResourceMissing
from resource_preferences import remove_coordinate
from collection_balance import balanced_candidates


class CollectionService:
    """Own one optional collection run and expose at most one deduplicated recovery demand."""

    def __init__(self, owner):
        self.owner = owner
        self.enabled = False
        self.epoch = 0
        self.run = None
        self.due = 0
        self.queue_blocked = False
        self.attributes_requested = threading.Event()
        self.wakeup = CollectionWakeup()

    def switch(self, enabled, options=None):
        """Freeze one user scope and revoke departures and recovery demand when its master is closed."""
        with self.owner.guard:
            prior_enabled = self.enabled
            if enabled:
                if not isinstance(options, CollectionOptions):
                    raise ValueError('采集设置无效')
                self.run = CollectionRun(options)
            else:
                self.run = None
            self.enabled = bool(enabled) and not self.owner.closing.is_set()
            self.epoch += 1
            self.due = 0
            self.queue_blocked = False
            self.wakeup = CollectionWakeup()
            if self.owner.connection is not None and (prior_enabled or self.enabled):
                self.owner.connection.set_collection_enabled(self.enabled)
            self.owner.sync_recovery_gate()

    @property
    def recovery_hero(self):
        """Expose a collection-only recovery authorization while that plan still has a free queue."""
        return self.run.recovery_hero if self.enabled and self.run and not self.queue_blocked else None

    def observe(self, roster):
        """Reconcile a shared recovery snapshot and immediately resume collection when the hero is ready."""
        if self.enabled and self.run:
            prior = self.run.recovery_hero
            self.run.observe(roster)
            if self.queue_blocked:
                self.run.needs_recovery = False
            if prior and not self.run.recovery_hero:
                self.due = 0

    def alive(self, run, epoch):
        """Check that an in-flight read still belongs to the user's current enabled collection run."""
        return self.enabled and self.run is run and self.epoch == epoch and not self.owner.closing.is_set()

    def request_check(self):
        """Allow an explicit user recheck without enabling collection or adding a repeating timer."""
        with self.owner.guard:
            if self.enabled:
                self.wakeup.pending = True
                self.run.blocked.clear()

    def remove_missing_target(self, run, epoch, candidate, error):
        """Persist only a matched6001 deletion within this active run; stop if its approved list becomes empty."""
        with self.owner.guard:
            if not self.alive(run, epoch):
                return False
            if run.options.mode != 'list' or error.target_id != candidate['target_id']:
                raise error
            point = (candidate['x'], candidate['y'])
            if point not in run.options.coordinates:
                raise RuntimeError('不存在的资源点不属于当前清单，未删除')
            saved = remove_coordinate(point)
            remaining = tuple(p for p in run.options.coordinates if p != point)
            self.owner.publish(resource_coordinates=saved, action='resource_removed', coordinate=point,
                               target_id=error.target_id, ret=error.ret,
                               collection_status=f'服务器确认资源田不存在，已删除并保存坐标（{point[0]},{point[1]}）')
            run.plan = None
            run.needs_recovery = False
            self.owner.sync_recovery_gate()
            if not remaining:
                self.switch(False)
                self.owner.publish(collect_enabled=False, collection_status='不存在的资源坐标已删除，清单已空，自动采集关闭')
                return False
            run.options = replace(run.options, coordinates=remaining)
            return True

    def schedule_status(self):
        """Explain the next server-deadline check, or explicitly wait for a push/manual recheck."""
        if self.due == float('inf'):
            return '无新的服务器阶段时间，等待状态推送或点击“立即检查”'
        seconds = max(0, int(self.due - time.monotonic()))
        return f'按服务器时间约{seconds // 60}分{seconds % 60}秒后检查'

    def refresh_attributes(self, connection):
        """Query three nearby level-two reference points without enabling recovery or dispatch."""
        self.attributes_requested.clear()
        roster = connection.refresh_heroes()
        self.owner.publish(hero_roster=roster)
        for kind in (3, 2, 1):
            if self.owner.closing.is_set():
                return
            rows = connection.collection_candidates(kind, 2, 100)
            if not rows:
                self.owner.publish(collection_attributes_missing=kind)
                continue
            target = min(rows, key=lambda row: (row['distance'], row['target_id']))
            # Refresh activity before each target so even a slow batch cannot make eligibility look idle.
            connection.refresh_heroes()
            metrics = connection.query_collection(target['target_id'])
            self.owner.publish(collection_metrics=metrics)
        self.owner.publish(collection_status='采集参考属性已刷新（未派出）')

    def tick(self, connection):
        """On existing wakeups, balance projected stock within type caps, then confirm one eligible departure."""
        with self.owner.guard:
            if not self.enabled or self.owner.closing.is_set():
                return
            run, epoch = self.run, self.epoch
            generation = connection.collect_generation
        try:
            self.wakeup.poll(connection, time.monotonic())
            with self.owner.guard:
                if not self.alive(run, epoch) or not self.wakeup.begin(time.monotonic(), self.due):
                    return
                self.due = float('inf')
            roster = connection.refresh_heroes()
            self.owner.publish(hero_roster=roster)
            queue = connection.collection_call('collect_status')
            schedule = connection.collection_call('collect_schedule')
            with self.owner.guard:
                if not self.alive(run, epoch):
                    return
                observed_at = time.monotonic()
                self.due = self.wakeup.schedule(schedule, observed_at)
                self.owner.publish(collection_queue=queue)
                self.owner.publish(collection_teams=team_snapshot(schedule, roster, self.wakeup, observed_at),
                                   collection_teams_epoch=epoch)
                self.queue_blocked = not queue['queue_free']
                self.observe(roster)
                if self.queue_blocked:
                    run.needs_recovery = False
                    self.owner.sync_recovery_gate()
                    self.owner.publish(collection_status=f"采集队列已满或状态不明（上限 {queue['queue_limit']}）；{self.schedule_status()}")
                    return
                if run.recovery_hero:
                    self.owner.sync_recovery_gate()
                    self.owner.hero_due = 0
                    self.owner.publish(collection_status=f"等待共用恢复队列完成{run.plan['name']}的冷却")
                    return
            # A full queue needs only hero/army confirmation, not another barrack/resource batch.
            connection.prepare_collection()
            if run.options.mode == 'list':
                self.owner.publish(collection_status='正在定位清单资源，按区域加载未缓存坐标…')
                located = connection.collection_list_candidates(run.options.coordinates, generation,
                                                                lambda: not self.alive(run, epoch))
                if not self.alive(run, epoch):
                    return
                rows = located['rows']
                if located['regions_loaded']:
                    # Region loads may outlive the old hero snapshot; recheck capacity and destinations once.
                    roster = connection.refresh_heroes()
                    schedule = connection.collection_call('collect_schedule')
                    queue = connection.collection_call('collect_status')
                    with self.owner.guard:
                        if not self.alive(run, epoch):
                            return
                        observed_at = time.monotonic()
                        self.due = self.wakeup.schedule(schedule, observed_at)
                        self.queue_blocked = not queue['queue_free']
                        self.observe(roster)
                        self.owner.publish(hero_roster=roster, collection_queue=queue,
                            collection_teams=team_snapshot(schedule, roster, self.wakeup, observed_at),
                            collection_teams_epoch=epoch)
                        if self.queue_blocked:
                            run.needs_recovery = False
                            self.owner.sync_recovery_gate()
                            self.owner.publish(collection_status='资源已定位，但采集额度已满或未知；' + self.schedule_status())
                            return
            else:
                rows = connection.collection_candidates(run.options.kind, run.options.level, run.options.radius)
            candidates = candidate_targets(rows, run.options, run.blocked, time.monotonic(),
                                           active_resource_targets(schedule))
            balance = None
            if run.options.mode == 'list':
                planned = connection.collection_balance(lambda: not self.alive(run, epoch))
                if not self.alive(run, epoch):
                    return
                balance = planned['balance']
                roster = planned['roster'] or roster
                # Income queries can overlap a return or manual dispatch; reconcile before selecting a new target.
                schedule = connection.collection_call('collect_schedule')
                queue = connection.collection_call('collect_status')
                with self.owner.guard:
                    if not self.alive(run, epoch):
                        return
                    observed_at = time.monotonic()
                    self.due = self.wakeup.schedule(schedule, observed_at)
                    self.queue_blocked = not queue['queue_free']
                    self.owner.publish(collection_balance=balance, hero_roster=roster, collection_queue=queue,
                        collection_teams=team_snapshot(schedule, roster, self.wakeup, observed_at),
                        collection_teams_epoch=epoch)
                    if self.queue_blocked or balance['unknown']:
                        run.plan = None
                        run.needs_recovery = False
                        self.owner.sync_recovery_gate()
                        reason = '采集额度已满或未知' if self.queue_blocked else '已有采集队伍收益或类型未确认'
                        self.owner.publish(collection_status=reason + '；' + self.schedule_status())
                        return
                candidates = candidate_targets(rows, run.options, run.blocked, time.monotonic(),
                                               active_resource_targets(schedule))
                candidates = balanced_candidates(candidates, balance)
            low_stock = 0
            for candidate in candidates:
                with self.owner.guard:
                    if not self.alive(run, epoch):
                        return
                try:
                    metrics = connection.query_collection(candidate['target_id'])
                except ResourceMissing as error:
                    if not self.remove_missing_target(run, epoch, candidate, error):
                        return
                    continue
                target = metrics['target']
                self.owner.publish(collection_metrics=metrics)
                with self.owner.guard:
                    if not self.alive(run, epoch):
                        return
                    if (not target.get('fresh') or not target.get('rules_known') or
                            target['kind'] != candidate['kind'] or target['level'] != candidate['level'] or
                            target['target_id'] != candidate['target_id'] or target['x'] != candidate['x'] or
                            target['y'] != candidate['y']):
                        raise RuntimeError('采集目标数据或范围不符，未派出')
                    if not target['queue_free']:
                        self.queue_blocked = True
                        run.needs_recovery = False
                        self.owner.sync_recovery_gate()
                        self.owner.publish(collection_status='采集队列已满；' + self.schedule_status())
                        return
                    if not collection_slot_available(target) or target['quantity'] <= 0:
                        run.blocked[candidate['target_id']] = time.monotonic() + 30
                        continue
                    if not quantity_allowed(target['level'], target['quantity']):
                        low_stock += 1
                        run.blocked[candidate['target_id']] = time.monotonic() + 30
                        continue
                    hero = best_collector(metrics, roster)
                    if hero is None:
                        self.owner.publish(collection_status='没有可用采集英雄；' + self.schedule_status())
                        return
                    state = next(row for row in roster['heroes'] if row['hero_id'] == hero['hero_id'])
                    run.reserve(target, hero, state)
                    self.owner.sync_recovery_gate()
                    if run.needs_recovery:
                        self.owner.hero_due = 0
                        self.owner.publish(collection_status=f"{hero['name']}采{RESOURCE_NAMES[target['kind']]}最快，交给共用队列恢复")
                        return
                    self.owner.publish(collection_status=f"正在派出{hero['name']}采{RESOURCE_NAMES[target['kind']]}（{target['x']},{target['y']}）")
                    target['scope_radius'] = 0 if run.options.mode == 'list' else run.options.radius
                    target['balance_guard'] = balance is not None
                receipt, after = connection.dispatch_collection(metrics, hero['hero_id'], generation)
                self.owner.publish(action='collection_dispatch', receipt=receipt, hero_roster=after)
                with self.owner.guard:
                    if not self.alive(run, epoch):
                        return
                    run.plan = None
                    run.needs_recovery = False
                    self.owner.sync_recovery_gate()
                    self.due = 0
                self.owner.publish(collection_status=f"已确认{hero['name']}出征采集，继续监控队列")
                return
            with self.owner.guard:
                if self.alive(run, epoch):
                    run.plan = None
                    run.needs_recovery = False
                    self.owner.sync_recovery_gate()
            if run.options.mode == 'list':
                loaded = {(row['x'], row['y']) for row in rows} & set(run.options.coordinates)
                message = f'清单{len(run.options.coordinates)}点，本次已定位{len(loaded)}点；暂无合格可采点'
                if balance:
                    capped = [RESOURCE_NAMES[k] for k, count in balance['counts'].items()
                              if count >= balance['same_kind_limit']]
                    if capped:
                        message += '；' + '、'.join(capped) + f"已达同类{balance['same_kind_limit']}队上限"
                if low_stock:
                    message += f'，本次跳过{low_stock}个高等级余量不足4万的点'
                message += '；' + self.schedule_status()
            else:
                message = '暂无符合条件的可采点；' + self.schedule_status()
            self.owner.publish(collection_status=message)
        except Exception as error:
            with self.owner.guard:
                if not self.alive(run, epoch):
                    return
                self.switch(False)
            self.owner.publish(collect_enabled=False, error=str(error), collection_status='采集已停止：' + str(error))
