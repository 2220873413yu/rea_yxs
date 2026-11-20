"""Serialize selected beacon event policies using server deadlines and passive changes."""
import threading
import time

from collection_wakeup import CollectionWakeup
from beacon_preferences import checked_types
from game_log import BeaconRejected, BeaconCapacityUnavailable, BeaconScoutUnconfirmed


def choose_rescue_hero(metrics, kind=1):
    """Use native combat power for monsters/rescue and target-specific speed then load for resources."""
    return min((h for h in metrics['heroes'] if h['ready']),
               key=lambda h: ((-h['speed'],-h['load'],h['travel_seconds'],h['hero_id']) if kind==3 else
                              (h['power'],h['travel_seconds'],h['hero_id'])), default=None)


def beacon_schedule(snapshot, roster, kinds=(1,)):
    """Use real army ends, rescue ends and anchored refresh time; completed events discard their old timer."""
    stages = [dict(army_id=a['army_id'], state=a['state'], end_ms=a['end_ms']) for a in snapshot['armies']]
    for event in snapshot['events']:
        if event['kind'] in kinds and event['kind'] in (1,3) and event['state'] == 2 and event['end_ms'] > 0:
            stages.append(dict(army_id=-event['event_id']-100, state=6, end_ms=event['end_ms']))
    if snapshot['refresh_end_ms'] > 0:
        stages.append(dict(army_id=-1, state=2, end_ms=snapshot['refresh_end_ms']))
    # Scout cache lifetime can exceed treasure completion; it is not an event/arrival deadline.
    # Treasure completion is reconciled by existing event pushes, manual checks and beacon refresh.
    finishes = [h['finish_ms'] for h in roster['heroes'] if h.get('found') and not h.get('busy') and
                h.get('hero_state') == 0 and h.get('finish_ms', 0) > snapshot['server_now_ms']]
    if finishes and any(e['kind'] in kinds and e['kind']!=2 and e['state'] == 0 for e in snapshot['events']):
        stages.append(dict(army_id=-2, state=6, end_ms=min(finishes)))
    return dict(server_now_ms=snapshot['server_now_ms'], stages=stages)


class BeaconService:
    """Reconcile once at startup and perform at most one selected event action per decision."""

    def __init__(self, owner):
        """Queue one startup reconciliation while leaving every rescue action disabled."""
        self.owner = owner
        self.enabled = False
        self.epoch = 0
        self.uncertain = False
        self.requested = threading.Event()
        self.requested.set()
        self.wakeup = CollectionWakeup()
        self.due = float('inf')
        self.watch_due = 0
        self.signature = None
        self.hero_signature = None
        self.kinds=(1,)
        self.ignored=set()
        self.last_kind=0
        self.skipped=set()
        self.capacity_wait=None
        self.last_snapshot=None
        self.scout_review = set()

    def switch(self, enabled, kinds=None):
        """Keep the checkbox default-off and immediately revoke every queued action on an off/on transition."""
        with self.owner.guard:
            if enabled and self.uncertain:
                raise RuntimeError('上次烽火台动作结果未确认，请核对游戏并重新连接助手')
            if enabled:
                self.kinds=checked_types(self.kinds if kinds is None else kinds)
                if not self.kinds:
                    raise ValueError('请至少勾选一种烽火台事件')
                self.ignored.clear();self.last_kind=0
                self.capacity_wait=None
                if self.owner.connection is not None:
                    self.owner.connection.configure_beacon(self.kinds)
            self.enabled = bool(enabled) and not self.owner.closing.is_set()
            self.epoch += 1
            self.wakeup = CollectionWakeup()
            self.due = float('inf')
            if self.enabled:
                self.requested.set()
            if self.owner.connection is not None:
                self.owner.connection.set_beacon_enabled(self.enabled)

    def request_check(self):
        """Queue reconciliation; actions remain conditional on the existing master switch and type selection."""
        self.requested.set()

    def alive(self, epoch):
        """Reject stale planning after closing, disabling or restarting this feature."""
        return self.enabled and self.epoch == epoch and not self.owner.closing.is_set()

    def observe(self, roster):
        """Wake on already-received hero eligibility changes; changing countdown display values are ignored."""
        signature = tuple(sorted((h['hero_id'], h.get('busy'), h.get('hero_state'), h.get('finish_ms'))
                                 for h in roster['heroes']))
        with self.owner.guard:
            if self.enabled and self.hero_signature is not None and signature != self.hero_signature:
                self.wakeup.pending = True
            self.hero_signature = signature

    def publish_snapshot(self, snapshot, roster):
        """Display confirmed server stages, deadlines and treasure receipts requiring review."""
        self.last_snapshot=snapshot
        if self.enabled:
            self.due = self.wakeup.schedule(beacon_schedule(snapshot, roster,self.kinds), time.monotonic())
        check_ms = (snapshot['server_now_ms'] + max(0, self.due-time.monotonic())*1000
                    if self.enabled and self.due != float('inf') else None)
        self.owner.publish(beacon_snapshot={**snapshot, 'enabled': self.enabled, 'check_ms': check_ms,
                                             'scout_review': sorted(self.scout_review)},
                           hero_roster=roster)

    def act(self, connection, operation, event, epoch, generation, army=None, hero=None):
        """Reserve one action and isolate scout results that do not require stopping other events."""
        with self.owner.guard:
            if not self.alive(epoch):
                return
            self.uncertain = True
        try:
            receipt, snapshot, roster = connection.beacon_action(operation, event['event_id'], generation,
                hero_id=(army['hero_id'] if army else hero['hero_id'] if hero else 1),
                army_id=army['army_id'] if army else None)
        except BeaconRejected as error:
            if operation!='dispatch' or error.operation!='dispatch' or error.event_id!=event['event_id'] or error.ret!=6395:
                raise
            self.wait_for_capacity(connection,event,epoch,error)
            return
        except BeaconCapacityUnavailable:
            if operation!='dispatch':raise
            self.wait_for_capacity(connection,event,epoch,None)
            return
        except BeaconScoutUnconfirmed as error:
            if operation != 'scout':
                raise
            with self.owner.guard:
                self.uncertain = False
                self.scout_review.add(event['event_id'])
            self.owner.publish(action='beacon_scout_unconfirmed', event_id=event['event_id'],
                               reason=str(error), beacon_status='该宝藏侦察结果待核对，暂停该事件')
            return 'review'
        with self.owner.guard:
            self.uncertain = False
            if operation=='skip':self.skipped.add(army['army_id'])
            if self.epoch == epoch:
                self.publish_snapshot(snapshot, roster)
                if self.alive(epoch):
                    self.due = 0  # A matched action response permits another decision, not an autonomous loop.
        names = {'dispatch':'出征', 'recall':'到达撤回', 'claim':'领奖','scout':'侦察','skip':'跳过战斗'}
        labels={1:'救援',2:'宝藏',3:'资源',4:'怪物'}
        self.owner.publish(action='beacon_' + operation, receipt=receipt,
                           beacon_status=f"{labels[event['kind']]}（{event['x']},{event['y']}）{names[operation]}已确认")

    def wait_for_capacity(self, connection, event, epoch, rejection):
        """Reconcile once after an attributed6395 or explicit unsent full result, then await confirmed capacity release."""
        with self.owner.guard:
            self.uncertain=False
            before=self.last_snapshot
        if rejection is not None:
            connection.beacon_call('beacon_rejected',(event['event_id'],6395))
        snapshot=connection.query_beacon(lambda:self.owner.closing.is_set() or self.epoch!=epoch)
        roster=connection.refresh_heroes()
        snapshot=connection.beacon_call('beacon_snapshot')
        with self.owner.guard:
            if not self.alive(epoch):return
            previous=before or snapshot
            ids=frozenset(a['army_id'] for a in previous['armies']+snapshot['armies'] if a['state']!=7)
            self.capacity_wait=dict(army_ids=ids,limit=previous['queue_limit'])
            self.publish_snapshot(snapshot,roster)
            current={a['army_id'] for a in snapshot['armies'] if a['state']!=7}
            if ids-current and not snapshot['queue_full'] and snapshot['queue_used']<snapshot['queue_limit']:
                self.due=0  # Reconciliation already confirmed a return; the next decision still refreshes before sending.
        self.owner.publish(action='beacon_capacity_wait',receipt=dict(ret=rejection.ret if rejection else None,event_id=event['event_id']),
                           beacon_status='烽火台额度已满，保持开启；等待返城时间或推送确认空位，不立即重发')

    def capacity_blocked(self, snapshot, explicit=False):
        """Clear a6395 wait only after refreshed own armies confirm a release or the server raises its limit."""
        if self.capacity_wait is None:return False
        ids={a['army_id'] for a in snapshot['armies'] if a['state']!=7}
        before=self.capacity_wait['army_ids']
        released=bool(before-ids) or snapshot['queue_limit']>self.capacity_wait['limit'] or (explicit and not before)
        if released and not snapshot['queue_full'] and snapshot['queue_used']<snapshot['queue_limit']:
            self.capacity_wait=None
            return False
        return True

    def stop_on_error(self, epoch, error):
        """Contain beacon failures, revoke its gate and preserve uncertain-action state without disconnecting other features."""
        with self.owner.guard:
            if self.epoch != epoch:
                return
            self.switch(False)
        self.owner.publish(beacon_enabled=False,error=str(error),beacon_status='烽火台已停止：'+str(error))

    def tick(self, connection):
        """Reconcile on manual requests, server deadlines or cached changes and keep independent events moving."""
        with self.owner.guard:
            if self.owner.closing.is_set():
                return
            epoch, generation = self.epoch, connection.beacon_generation
            now = time.monotonic()
            explicit = self.requested.is_set()
            if explicit:
                self.requested.clear()
            if self.enabled and now >= self.watch_due:
                self.watch_due = now + .25
                try:
                    signature = connection.beacon_call('beacon_watch')['signature']
                except Exception as error:
                    self.stop_on_error(epoch,error)
                    return
                if self.signature is not None and self.signature != signature:
                    self.wakeup.pending = True
                self.signature = signature
            if not explicit and (not self.enabled or not self.wakeup.begin(now, self.due)):
                return
            self.due = float('inf')
        try:
            # Initialize the log and event view before taking time-sensitive hero snapshots.
            snapshot = connection.query_beacon(lambda: self.owner.closing.is_set() or self.epoch != epoch)
            roster = connection.refresh_heroes()
            snapshot = connection.beacon_call('beacon_snapshot')
            with self.owner.guard:
                if self.epoch != epoch:
                    return
                self.publish_snapshot(snapshot, roster)
                self.observe(roster)
            if not self.alive(epoch):
                self.owner.publish(beacon_status='已核对服务器状态；自动烽火台关闭')
                return
            selected = sorted((e for e in snapshot['events'] if e['kind'] in self.kinds),
                             key=lambda e: (e['distance'], e['event_id']))
            # Arrival and ownership must both agree; manual rescues are reconciled the same way.
            for event in selected:
                if event['kind']==1 and event['state'] == 2:
                    army = next((a for a in snapshot['armies'] if a['army_id'] == event['army_id'] and
                                 a['target_id'] == event['event_id'] and a['state'] not in (2,7,9)), None)
                    if army:
                        self.act(connection, 'recall', event, epoch, generation, army=army)
                        return
                if event['kind']==4:
                    army=next((a for a in snapshot['armies'] if a['target_id']==event['event_id'] and a['state']==3 and a['army_id'] not in self.skipped),None)
                    if army:
                        self.act(connection,'skip',event,epoch,generation,army=army)
                        return
            for event in selected:
                if event['state'] == 3:
                    self.act(connection, 'claim', event, epoch, generation)
                    return
            blocked=self.capacity_blocked(snapshot,explicit)
            # Rotate types for new work; treasure is allowed even when hero-army capacity is full.
            kinds=list(self.kinds)
            rotation=kinds[kinds.index(self.last_kind)+1:]+kinds[:kinds.index(self.last_kind)+1] if self.last_kind in kinds else kinds
            selected.sort(key=lambda e:(rotation.index(e['kind']),e['distance'],e['event_id']))
            for event in selected:
                # The native treasure dialog can scout in fog; other tasks still require vision.
                if event['state'] != 0 or (event['kind'] != 2 and not event['visible']):
                    continue
                if event['event_id'] in self.ignored:
                    continue
                if event['kind']!=2 and (blocked or snapshot['queue_full'] or snapshot['queue_used']>=snapshot['queue_limit']):
                    continue
                if any(a['target_id'] == event['event_id'] for a in snapshot['armies']):
                    continue
                if not self.alive(epoch):
                    return
                if event['kind']==2:
                    if event['event_id'] in self.scout_review:
                        continue
                    if any(s['x']==event['x'] and s['y']==event['y'] and s['end_ms']>snapshot['server_now_ms'] for s in snapshot.get('scouts',[])):
                        continue
                    metrics=connection.query_beacon_scout(event['event_id'],generation,lambda:not self.alive(epoch))
                    self.owner.publish(beacon_scout=metrics)
                    if not self.alive(epoch):return
                    if metrics['eligible'] and metrics['fresh']:
                        outcome = self.act(connection,'scout',event,epoch,generation)
                        if outcome is None:
                            self.last_kind = 2
                            return
                    continue
                # All features use this same worker; refresh eligibility before the final native send.
                roster = connection.refresh_heroes()
                metrics = connection.query_beacon_candidates(event['event_id'], generation,
                                                              lambda: not self.alive(epoch))
                if not self.alive(epoch):
                    return
                hero = choose_rescue_hero(metrics,event['kind'])
                if hero:
                    self.last_kind=event['kind']
                    self.act(connection, 'dispatch', event, epoch, generation, hero=hero)
                    return
                if event['kind']==4 and metrics['heroes'] and all(h.get('strength_known',True) for h in metrics['heroes']) and not any(h.get('overwhelming') for h in metrics['heroes']):
                    self.ignored.add(event['event_id'])
            with self.owner.guard:
                if not self.alive(epoch):
                    return
                self.publish_snapshot(snapshot,roster)
            if blocked or snapshot['queue_full'] or snapshot['queue_used']>=snapshot['queue_limit']:
                self.owner.publish(beacon_status=f"烽火台额度已满或待服务器确认（{snapshot['queue_used']}/{snapshot['queue_limit']}，含返城），保持开启；等待阶段时间或推送")
            else:
                self.owner.publish(beacon_status=f"暂无符合条件的空位、事件、英雄或斥候；等待服务器时间/推送。本轮排除怪物 {len(self.ignored)} 个")
        except Exception as error:
            self.stop_on_error(epoch,error)
        finally:
            if self.epoch == epoch and self.enabled:
                try:
                    signature = connection.beacon_call('beacon_watch')['signature']
                except Exception as error:
                    self.stop_on_error(epoch,error)
                    return
                # A confirmed action already schedules its own immediate follow-up.
                if self.signature is not None and self.signature != signature and self.due != 0:
                    self.wakeup.pending = True
                self.signature = signature
