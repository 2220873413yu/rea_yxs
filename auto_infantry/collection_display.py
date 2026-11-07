"""Present existing server snapshots and actual scheduler timers without querying the game."""
from datetime import datetime, timedelta, timezone

TIMEZONE = timezone(timedelta(hours=8))
STATES = {2: '采集行军中', 3: '采集行军中', 6: '采集中', 9: '返城中'}


def display_time(milliseconds):
    """Format a server epoch timestamp in Beijing time; missing/invalid timestamps stay visibly unknown."""
    if type(milliseconds) not in (int, float) or milliseconds <= 0:
        return '未知'
    try:
        return datetime.fromtimestamp(milliseconds / 1000, TIMEZONE).strftime('%m-%d %H:%M:%S')
    except (ValueError, OverflowError, OSError):
        return '未知'


def team_snapshot(snapshot, roster, wakeup, now):
    """Copy per-army planned triggers and earliest shared check, using the same clock anchor as scheduling."""
    server_now = snapshot['server_now_ms']
    names = {row['hero_id']: row.get('name', str(row['hero_id'])) for row in roster['heroes']}
    rows = []
    checks = []
    for stage in snapshot['stages']:
        hero_id = stage.get('hero_id', 0)
        timer = wakeup.timers.get((stage['army_id'], stage['state']))
        check_ms = None
        if timer:
            check_ms = server_now + max(0, max(timer[0], wakeup.next_check) - now) * 1000
            checks.append(check_ms)
        rows.append({'army_id': stage['army_id'], 'hero_id': hero_id,
                     'hero': names.get(hero_id, f'英雄{hero_id}' if hero_id else '未知英雄'),
                     'state': STATES.get(stage['state'], f"状态{stage['state']}"),
                     'end_ms': stage['end_ms'], 'check_ms': check_ms})
    return {'server_now_ms': server_now, 'rows': rows,
            'next_check_ms': min(checks) if checks else None}
