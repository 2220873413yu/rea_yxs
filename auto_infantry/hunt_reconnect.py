"""Memory-only, acknowledged hunting checkpoints; no credential or automatic action replay."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import time

import frida

RECONNECT_DELAY = 600


def connection_lost(error):
    """Recognize a session fence or a lost Frida transport, not ordinary game query errors."""
    if isinstance(error, (SessionUnsent, SessionAccepted)) and error.__cause__ is not None:
        return connection_lost(error.__cause__)
    return ('Account session changed' in str(error) or
            'Game Lua update did not run within five seconds' in str(error) or
            isinstance(error, (frida.TransportError, frida.ServerNotRunningError, frida.ProcessNotFoundError)) or
            isinstance(error, frida.InvalidOperationError) and
            any(word in str(error).lower() for word in ('destroyed', 'detached', 'closed')))


def recovery_plan(worker, connection, error):
    """Keep the original task intent and unknown-result flags without retaining a live connection."""
    if not connection_lost(error) or not connection.process_identity or not connection.reconnect_key:
        return None
    hunt = worker.hunt
    blocked = hunt.automatic_start_blocked()
    scheduled = worker.allow_scheduled_hunt and not hunt.auto_suspended
    collection = worker.collection
    collection_blocked = collection.uncertain or worker.hero_uncertain
    return {
        'process': connection.process_identity, 'key': connection.reconnect_key,
        'deadline': time.monotonic() + RECONNECT_DELAY,
        'reason': str(error).splitlines()[0],
        'collection': collection.run.options if collection.enabled and not collection_blocked else None,
        'collection_blocked': collection_blocked,
        'recovery_mode': worker.recovery_mode,
        'hunt_blocked': blocked,
        'hunt': {
            'options': hunt.options, 'active': deepcopy(hunt.active),
            'ignored': set(hunt.ignored), 'completed': set(hunt.completed), 'home': hunt.home,
            'refresh_round': hunt.refresh_round, 'enabled': hunt.enabled, 'search_paused': hunt.search_paused,
            'scheduled': scheduled, 'auto_refresh': deepcopy(hunt.auto_refresh),
            'auto_start_pending': hunt.auto_start_epoch is not None, 'refresh': deepcopy(hunt.refresh),
        } if not blocked and (hunt.enabled or scheduled) else None,
    }


def log_reconnect(action, reason, **fields):
    """Append a UI-owned reconnect event without serializing its private recovery plan."""
    try:
        with Path(__file__).with_name('actions.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'time': datetime.now().isoformat(), 'action': action,
                                  'reason': reason, **fields}, ensure_ascii=False) + '\n')
    except OSError:
        pass


class SessionUnsent(RuntimeError):
    """The bridge's exact line-one fence ran before the native action body, so nothing was sent."""


class SessionAccepted(RuntimeError):
    """Carry one attributed successful departure when a later state read lost its connection."""

    def __init__(self, error, receipt):
        super().__init__(str(error))
        self.receipt = dict(receipt)


def fence_rejected(error):
    """Only the bridge's unambiguous pre-body assertion can prove an action was not submitted."""
    return 'rea-auto-infantry:1: Account session changed; reconnect the helper' in str(error)


def reconcile(plan, roster, schedule):
    """Match acknowledged army identities against one fresh server snapshot; never infer a new departure."""
    if not roster.get('fresh') or not schedule.get('queue_known'):
        raise RuntimeError('重连后英雄或部队状态未确认，不恢复打野')
    heroes = {row['hero_id']: row for row in roster['heroes']}
    stages = {row['army_id']: row for row in schedule['stages']}
    active, completed = {}, set(plan['completed'])
    for army_id, before in plan['active'].items():
        if before.get('skip_attempted') and not before.get('skipped'):
            raise RuntimeError('上次跳过结果不明，不恢复打野')
        hero = heroes.get(before['hero_id'])
        if not hero or not hero.get('army_known') or not hero.get('fresh'):
            raise RuntimeError('重连后原打野英雄状态未确认，不恢复打野')
        row = stages.get(army_id)
        if row is None:
            if any(r['hero_id'] == before['hero_id'] for r in stages.values()) or hero.get('busy'):
                raise RuntimeError('重连后原英雄的部队归属变化，不恢复打野')
            if before.get('refresh_round', 0) == plan['refresh_round']:
                completed.add(before['target_id'])
            continue
        if (row['hero_id'] != before['hero_id'] or row['target_id'] != before['target_id'] or
                row['aim'] != 3):
            raise RuntimeError('重连后打野队伍身份或目标变化，不恢复打野')
        active[army_id] = deepcopy(before)
    return active, completed
