"""Collection choices and pending recovery demand, independent of game transport and UI."""
from dataclasses import dataclass
from resource_preferences import checked_coordinates

RESOURCE_NAMES = {1: '粮', 2: '木', 3: '铁'}


class CollectionReplan(RuntimeError):
    """A confirmed pre-send eligibility change permits bounded replanning, never replay of a sent request."""

    def __init__(self,message,reason='preflight_changed'):
        """Keep a credential-free reason so repeated unsent checks can be diagnosed without another action."""
        super().__init__(message)
        self.reason=reason


def collection_queue_reason(state):
    """Separate unavailable capacity from expired evidence; only fresh counts may be described as full."""
    reason=state.get('queue_reason')
    if reason=='stale':
        raise CollectionReplan('英雄或部队资料已过期，尚未发送出征请求',reason='queue_stale')
    if reason=='native_blocked':return '原生采集规则暂不允许派出，队伍数量尚未满'
    if reason=='unknown':return '采集队伍资料未确认'
    if reason=='full':return '采集队列已满'
    return '采集队列已满或状态不明'


@dataclass(frozen=True)
class CollectionOptions:
    """Freeze the resource scope and item authorization for one run."""
    kind: int = 3
    level: int = 2
    radius: int = 20
    mode: str = 'coordinate'
    x: int = 101
    y: int = 191
    coordinates: tuple = ()
    use_hero_recovery: bool = False

    def __post_init__(self):
        """Reject malformed options before any query, recovery authorization or departure."""
        if (type(self.kind) is not int or self.kind not in RESOURCE_NAMES or
                type(self.level) is not int or not 1 <= self.level <= 10 or
                type(self.radius) is not int or not 1 <= self.radius <= 100 or
                self.mode not in {'coordinate', 'nearby', 'list'} or type(self.x) is not int or
                type(self.y) is not int or not 0 <= self.x <= 10000 or not 0 <= self.y <= 10000):
            raise ValueError('采集类型、等级、范围或坐标无效')
        if type(self.use_hero_recovery) is not bool:
            raise ValueError('采集恢复道具选项无效')
        object.__setattr__(self, 'coordinates', checked_coordinates(self.coordinates))
        if self.mode == 'list' and not self.coordinates:
            raise ValueError('请先录入并保存资源清单')


def quantity_allowed(level, quantity):
    """Require40000 for levels4+, and any positive remaining quantity for lower levels."""
    return (type(level) is int and 1 <= level <= 10 and
            type(quantity) in (int, float) and quantity > 0 and (level < 4 or quantity >= 40000))


def collection_slot_available(target):
    """Require native relationship permission, a configured free slot and no own army at the point."""
    capacity, occupied = target.get('capacity'), target.get('occupants')
    return (target.get('rules_known') is True and target.get('can_collect') is True and
            target.get('own_present') is False and type(capacity) is int and capacity > 0 and
            type(occupied) is int and 0 <= occupied < capacity)


def active_resource_targets(schedule):
    """Read own marching/collecting destinations from an already-refreshed schedule, excluding returned armies."""
    targets = set()
    for row in schedule['stages']:
        if row.get('aim') == 1 and row['state'] not in (7, 9):
            target = row.get('target_id')
            if type(target) is not int or target <= 0:
                raise RuntimeError('采集队伍目标不明，未继续派出')
            targets.add(target)
    return targets


def candidate_targets(rows, options, blocked, now, active_targets=()):
    """Order scoped points while excluding own inbound/collecting destinations before any resource query."""
    return sorted((row for row in rows if row['kind'] in RESOURCE_NAMES and
                   (options.mode == 'list' or row['kind'] == options.kind) and
                   (options.mode == 'list' or row['level'] == options.level) and
                   (options.mode == 'list' or row['distance'] <= options.radius) and
                   (options.mode == 'list' or row['quantity'] > 0) and
                   row['target_id'] not in active_targets and blocked.get(row['target_id'], 0) <= now and (options.mode == 'nearby' or
                   (options.mode == 'list' and (row['x'], row['y']) in options.coordinates) or
                   (options.mode == 'coordinate' and row['x'] == options.x and row['y'] == options.y))),
                  key=lambda row: (row['distance'], row['x'], row['y'], row['target_id']))


def best_collector(metrics, roster, *, use_hero_recovery=False):
    """Rank available heroes by target speed, including cooling heroes only with item authorization."""
    states = {state['hero_id']: state for state in roster['heroes']}
    eligible_actions = (0, 5) if use_hero_recovery else (0,)
    eligible = []
    for row in metrics['heroes']:
        state = states.get(row['hero_id'])
        if (state and state.get('found') and state.get('fresh') and state.get('army_known') and
                not state.get('busy') and state.get('hero_state') == 0 and row.get('fresh') and
                row.get('army_known') and not row.get('busy') and row.get('hero_state') == 0 and
                row.get('action_state') in eligible_actions and row.get('speed', 0) > 0 and
                (use_hero_recovery or state.get('remaining_ms') == 0)):
            eligible.append(row)
    if not eligible:
        return None
    return min(eligible, key=lambda row: (-row['speed'], -row['load'], row['travel_seconds'], row['hero_id']))


class CollectionRun:
    """Keep a single resource/hero plan whose recovery demand merges with normal automatic recovery."""

    def __init__(self, options):
        self.options = options
        self.plan = None
        self.needs_recovery = False
        self.blocked = {}
        self.located = {}
        self.scanned_regions = set()
        self.continuing_discovery = False

    @property
    def recovery_hero(self):
        """Expose one hero to the shared recovery queue only when the run opted in."""
        return self.plan['hero_id'] if self.options.use_hero_recovery and self.plan and self.needs_recovery else None

    def observe(self, roster):
        """Drop a plan that became busy/unknown, or release its recovery demand when cooldown reaches zero."""
        if not self.plan:
            return
        state = next((row for row in roster['heroes'] if row['hero_id'] == self.plan['hero_id']), None)
        if (state is None or not state.get('found') or not state.get('fresh') or not state.get('army_known') or
                state.get('busy') or state.get('hero_state') != 0):
            self.plan = None
            self.needs_recovery = False
        else:
            self.needs_recovery = self.options.use_hero_recovery and state['remaining_ms'] > 0

    def reserve(self, target, hero, state):
        """Reserve the selected hero and request shared recovery only for opted-in runs."""
        self.plan = {'target_id': target['target_id'], 'hero_id': hero['hero_id'], 'name': hero['name']}
        self.needs_recovery = self.options.use_hero_recovery and state['remaining_ms'] > 0
