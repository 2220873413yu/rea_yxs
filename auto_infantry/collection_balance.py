"""Balance ordinary collection using current stock and existing armies, without owning any timers."""
import math

from collection import RESOURCE_NAMES

STOCK_KEYS = {1: 'food', 2: 'wood', 3: 'iron'}


def amount(value):
    """Accept finite nonnegative resource amounts and reject malformed native/account data."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('资源存量或预计收益无效')
    return value


def same_kind_limit(queue_limit):
    """Reserve diversity using the server capacity: two slots allow one of a kind, three/four allow two."""
    if type(queue_limit) is not int or queue_limit < 1:
        raise ValueError('采集队伍上限未确认')
    return max(1, (queue_limit + 1) // 2)


def resource_balance(snapshot, metrics_by_target):
    """Deduplicate manual/automatic armies and replace carried goods with their estimated final haul.

    Returning armies contribute carried goods only. Unknown ordinary destinations block new
    decisions for this check; estimates never determine completion or return deadlines.
    """
    stock = {kind: amount(snapshot[key]) for kind, key in STOCK_KEYS.items()}
    incoming = {kind: 0 for kind in RESOURCE_NAMES}
    counts = {kind: 0 for kind in RESOURCE_NAMES}
    unknown, seen = [], set()
    for army in snapshot['armies']:
        army_id = army['army_id']
        if army_id in seen or army['state'] == 7:
            continue
        seen.add(army_id)
        cargo = {kind: amount(army.get('carried_' + key, 0)) for kind, key in STOCK_KEYS.items()}
        for kind in RESOURCE_NAMES:
            incoming[kind] += cargo[kind]
        if army['aim'] != 1 or army['state'] == 9:
            continue
        metrics = metrics_by_target.get(army['target_id'])
        target = metrics.get('target', {}) if metrics else {}
        kind = target.get('kind') if target.get('target_id') == army['target_id'] else None
        if kind not in RESOURCE_NAMES:
            carried_kinds = [k for k in RESOURCE_NAMES if cargo[k] > 0]
            kind = carried_kinds[0] if len(carried_kinds) == 1 else None
        if kind not in RESOURCE_NAMES:
            unknown.append(army_id)
            continue
        counts[kind] += 1
        if not target or target.get('target_id') != army['target_id']:
            # A vanished field may still have an army returning with the confirmed carried goods.
            continue
        quantity = amount(target['quantity'])
        resident = next((r for r in metrics.get('collectors', ())
                         if r['army_id'] == army_id and r['hero_id'] == army['hero_id']), None)
        if resident is not None:
            collected = max(cargo[kind], amount(resident['count']))
            maximum = amount(resident['maximum'])
            if maximum < amount(resident['count']):
                raise ValueError('服务器采集收益上限小于已采数量')
            forecast = max(collected, min(maximum, collected + quantity))
        else:
            hero = next((h for h in metrics.get('heroes', ()) if h['hero_id'] == army['hero_id']), None)
            if hero is None or army['state'] == 6:
                # A collecting army needs its own resident record, not somebody else's load.
                unknown.append(army_id)
                continue
            forecast = max(cargo[kind], min(amount(hero['load']), cargo[kind] + quantity))
        incoming[kind] += forecast - cargo[kind]
    return dict(stock=stock, incoming=incoming, counts=counts, unknown=unknown,
                effective={k: stock[k] + incoming[k] for k in RESOURCE_NAMES},
                same_kind_limit=same_kind_limit(snapshot['queue_limit']))


def collection_resource_order(balance):
    """Rank dispatchable kinds and hold the richest when its projected stock is twice the next kind."""
    if balance['unknown']:
        return [], None
    ranked = sorted(RESOURCE_NAMES, key=lambda kind: (balance['effective'][kind], balance['counts'][kind]))
    richest, second = ranked[-1], ranked[-2]
    high, middle = balance['effective'][richest], balance['effective'][second]
    held = richest if high > middle and high >= 2 * middle else None
    return [kind for kind in ranked if kind != held and balance['counts'][kind] < balance['same_kind_limit']], held


def balanced_candidates(candidates, balance):
    """Use the resource policy for eligibility and choose nearby points within the same projected stock."""
    eligible, _ = collection_resource_order(balance)
    return sorted((row for row in candidates if row['kind'] in eligible),
                  key=lambda row: (balance['effective'][row['kind']], balance['counts'][row['kind']],
                                   row['distance'], row['x'], row['y'], row['target_id']))
