"""Hunting policy independent of transport: near-first rings and unchanged native default formations."""
from dataclasses import dataclass

MAX_HUNT_RADIUS = 200


@dataclass(frozen=True)
class HuntOptions:
    """Bound one run to loaded ordinary monsters within a user-visible distance from home."""
    radius: int = 20

    def __post_init__(self):
        """Validate the helper's configurable radius; the upper bound is not a server-provided game limit."""
        if type(self.radius) is not int or not 1 <= self.radius <= MAX_HUNT_RADIUS:
            raise ValueError(f'打野最大范围须为1～{MAX_HUNT_RADIUS}格')


def ordered_targets(rows, radius, completed, ignored=(), reserved=()):
    """Exclude this run's weak coordinates and reserved/manual targets before issuing any target query."""
    return sorted((r for r in rows if r['visible'] is True and r['idle'] is True and
                   0 <= r['distance'] <= radius and r['target_id'] not in completed and
                   r['target_id'] not in reserved and (r['x'],r['y']) not in ignored),
                  key=lambda r: (r['distance'], r['target_id']))


def default_formation(metrics):
    """Choose the lowest-power overwhelming native default; ties prefer faster travel, then stable hero ID."""
    target = metrics['target']
    if not (target.get('fresh') and target.get('visible') and target.get('idle') and
            type(target.get('enemy_power')) in (int, float) and target['enemy_power'] > 0):
        return None
    choices = [r for r in metrics['formations'] if r.get('eligible') is True and
               r.get('native_default') is True and r.get('start_enabled') is True and
               type(r.get('followers')) is int and r['followers'] > 0 and
               r.get('enemy_power') == target['enemy_power'] and r.get('power', 0) >= target['enemy_power'] and
               r.get('recommendation') == '我方超强，胜券在握']
    return min(choices, key=lambda r: (r['power'], r['travel_seconds'], r['hero_id'])) if choices else None


def ring_for(distance, maximum):
    """Describe the five-cell search ring without ever exceeding the configured maximum."""
    return min(maximum, max(1, ((int(distance) + 4) // 5) * 5))
