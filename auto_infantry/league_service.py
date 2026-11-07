"""One alliance collector, driven by authoritative phase deadlines and passive state changes."""
import threading
import time

from collection_wakeup import CollectionWakeup


def best_collector(metrics):
    """Rank ready native candidates by target speed, load, travel time and a stable hero ID."""
    rows = [r for r in metrics['heroes'] if r['ready'] and r['speed'] > 0]
    return min(rows, key=lambda r: (-r['speed'], -r['load'], r['travel_seconds'], r['hero_id']), default=None)


class LeagueService:
    """Observe existing manual armies and refill only after a fresh response proves none remain."""

    def __init__(self, owner):
        self.owner = owner
        self.enabled = False
        self.epoch = 0
        self.uncertain = False
        self.requested = threading.Event()
        self.requested.set()  # Every process startup gets exactly one read-only reconciliation.
        self.wakeup = CollectionWakeup()
        self.due = float('inf')
        self.watch_due = 0
        self.signature = None
        self.hero_signature = None

    def switch(self, enabled):
        """Cancel queued alliance sends immediately; never persist the enabled state between startups."""
        with self.owner.guard:
            if enabled and self.uncertain:
                raise RuntimeError('上次联盟出征结果未确认，请核对游戏后重启助手')
            self.enabled = bool(enabled) and not self.owner.closing.is_set()
            self.epoch += 1
            self.wakeup = CollectionWakeup()
            self.due = float('inf')
            if self.enabled:
                self.requested.set()
            if self.owner.connection is not None:
                self.owner.connection.set_league_enabled(self.enabled)

    def request_check(self):
        """Queue one manual server reconciliation without changing the default-off spending switch."""
        self.requested.set()

    def observe(self, roster):
        """Wake on received eligibility changes only, never on changing display countdown values."""
        signature = tuple(sorted((r['hero_id'], r.get('busy'), r.get('hero_state'), r.get('finish_ms'))
                                 for r in roster['heroes']))
        with self.owner.guard:
            if self.enabled and self.hero_signature is not None and signature != self.hero_signature:
                self.wakeup.pending = True
            self.hero_signature = signature

    def alive(self, epoch):
        """Prevent a completed read from authorizing sends after off/on or application close."""
        return self.enabled and self.epoch == epoch and not self.owner.closing.is_set()

    def publish_snapshot(self, metrics, schedule):
        """Expose server times and active one-shot plans; cancelled timers never appear scheduled."""
        rows = []
        now = time.monotonic()
        for row in schedule['stages']:
            timer = self.wakeup.timers.get((row['army_id'], row['state'])) if self.enabled else None
            rows.append({**row, 'check_ms': (schedule['server_now_ms'] + max(0, timer[0] - now) * 1000)
                         if timer else None})
        self.owner.publish(league_snapshot={'mine': metrics['mine'], 'rows': rows,
                                            'server_now_ms': schedule['server_now_ms'],
                                            'enabled': self.enabled})

    def tick(self, connection):
        """Reconcile on startup/manual request, stage expiry or passive changes; never perform fixed polling."""
        with self.owner.guard:
            if self.owner.closing.is_set():
                return
            epoch, generation = self.epoch, connection.league_generation
            now = time.monotonic()
            explicit = self.requested.is_set()
            if explicit:
                self.requested.clear()
            if self.enabled and now >= self.watch_due:
                self.watch_due = now + .25
                watch = connection.league_call('league_watch')  # Local Lua reads only.
                if self.signature is not None and self.signature != watch:
                    self.wakeup.pending = True
                self.signature = watch
            if not explicit and (not self.enabled or not self.wakeup.begin(now, self.due)):
                return
            self.due = float('inf')
        try:
            # Check authoritative army state even if the mine disappeared or the feature is off.
            roster = connection.refresh_heroes()
            self.owner.publish(hero_roster=roster)
            schedule = connection.league_call('league_schedule')
            if self.alive(epoch) and not schedule['stages']:
                connection.prepare_collection()
            metrics = connection.query_league()
            # Details may take time; bind the latest own armies immediately before deciding to depart.
            roster = connection.refresh_heroes()
            self.owner.publish(hero_roster=roster)
            self.observe(roster)
            schedule = connection.league_call('league_schedule')
            if metrics['mine'] is not None:
                metrics = connection.league_call('league_metrics')
            with self.owner.guard:
                if self.epoch != epoch:
                    return
                if self.enabled:
                    self.due = self.wakeup.schedule(schedule, time.monotonic())
                self.publish_snapshot(metrics, schedule)
            if not self.alive(epoch):
                self.owner.publish(league_status='已核对服务器状态；联盟采集关闭，不会派出')
                return
            if schedule['stages']:
                self.owner.publish(league_status='已有本方联盟采集队伍，按服务器阶段时间等待；返城确认后继续采集')
                return
            mine = metrics['mine']
            if not mine:
                message = '本联盟暂无资源矿，等待被动变化或手动检查'
            elif mine['stock'] <= 0:
                message = '联盟矿已采空，等待重建后的被动变化或手动检查'
            elif mine['occupied'] >= mine['capacity']:
                message = '联盟矿共享位置已满，等待变化或手动检查'
            elif mine['own_present']:
                message = '矿中仍有本方队伍，等待状态推送或手动确认，不重复派出'
            elif not mine['visible']:
                message = '联盟矿暂无视野，等待变化或手动检查'
            else:
                plan = best_collector(metrics)
                if plan is not None:
                    with self.owner.guard:
                        if not self.alive(epoch):
                            return
                        self.uncertain = True
                    receipt, after = connection.dispatch_league(mine['target_id'], plan['hero_id'], generation)
                    with self.owner.guard:
                        self.uncertain = False
                        if self.alive(epoch):
                            schedule = connection.league_call('league_schedule')
                            self.due = self.wakeup.schedule(schedule, time.monotonic())
                            self.publish_snapshot(metrics, schedule)
                    self.owner.publish(hero_roster=after, action='league_dispatch', receipt=receipt,
                                       league_status=(f"已确认{plan['name']}出征联盟矿；到期或状态变化后再检查" if
                                                      self.alive(epoch) else '联盟出征已确认；自动已关闭，已有队伍继续行动'))
                    return
                cooldowns = [r['remaining_ms'] for r in metrics['heroes'] if r.get('remaining_ms', 0) > 0]
                if cooldowns:
                    self.due = time.monotonic() + min(cooldowns) / 1000 + 1
                message = '暂无可用英雄，等待冷却结束或状态变化；联盟采集不主动使用恢复道具'
            self.owner.publish(league_status=message)
        except Exception as error:
            with self.owner.guard:
                if self.epoch != epoch:
                    return
                self.switch(False)
                self.owner.publish(league_enabled=False, league_status='联盟采集已停止：' + str(error), error=str(error))
        finally:
            # Consume notifications produced by our own explicit reads so they cannot form a query loop.
            if self.enabled and self.epoch == epoch:
                watch = connection.league_call('league_watch')
                if self.signature is not None and watch['seq'] != self.signature['seq']:
                    self.wakeup.pending = True
                self.signature = watch
