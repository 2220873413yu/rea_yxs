"""Test collection scope, fastest-hero selection and shared recovery without contacting the game."""
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from collection import CollectionOptions, CollectionReplan, candidate_targets, best_collector, quantity_allowed, collection_slot_available, active_resource_targets
from controller import Worker
from test_hero_recovery import hero_state, hero_roster
from game_log import GameResponseLog
from game_log import ResourceMissing
from resource_preferences import save_coordinates, load_coordinates, remove_coordinate
from collection_balance import resource_balance


def metric(hero_id=303, speed=300, **changes):
    """Build a target-specific rate record with all eligibility fields explicit."""
    row = dict(hero_id=hero_id, name=str(hero_id), speed=speed, load=40000, travel_seconds=8,
               hero_state=0, action_state=0, busy=False, fresh=True, found=True, army_known=True)
    row.update(changes)
    return row


def point(target_id=2792, **changes):
    """Create the previously investigated two-star iron point in display coordinates."""
    row = dict(target_id=target_id, kind=3, level=2, x=101, y=191, distance=4, quantity=20000,
               occupants=0, capacity=1, own_present=False)
    row.update(changes)
    return row


class FakeCollectionGame:
    """Simulate shared inventory and independent switches while the real worker chooses its actions."""

    def __init__(self):
        self.hero_generation = 0
        self.collect_generation = 0
        self.allowed = set()
        self.collect_allowed = False
        self.items = 30
        self.states = {303: hero_state(remaining_ms=600000), 305: hero_state(hero_id=305, remaining_ms=0)}
        self.speeds = {303: 300, 305: 200}
        self.recoveries = []
        self.departures = []
        self.gates = []
        self.queue_free = True
        self.query_hook = None
        self.fail_departure = False
        self.query_seq = 0
        self.push_seq = 0
        self.schedule = {'server_now_ms': 1000000, 'stages': []}
        self.stock = dict(food=100000, wood=100000, iron=100000)

    def collection_push_sequence(self):
        """Read a local push marker; no simulated server query is recorded here."""
        return self.push_seq

    def set_hero_enabled(self, enabled, heroes=()):
        """Apply the shared deduplicated authorization rather than one gate per demand source."""
        self.allowed = set(heroes) if enabled else set()
        self.hero_generation += 1
        self.gates.append(tuple(sorted(self.allowed)))

    def set_collection_enabled(self, enabled):
        """Invalidate previously captured departure generations when collection changes."""
        self.collect_allowed = enabled
        self.collect_generation += 1

    def prepare_collection(self):
        """Stand in for log/follower readiness without sending any simulated action."""

    def refresh_heroes(self):
        """Return fresh independent activity plus one shared recovery inventory."""
        return hero_roster(*({**state, 'items': self.items} for state in self.states.values()))

    def collection_call(self, operation):
        """Return current queue occupancy independently of a particular resource query."""
        if operation == 'collect_schedule':
            return self.schedule
        assert operation == 'collect_status'
        return dict(queue_free=self.queue_free, queue_limit=2)

    def collection_candidates(self, kind, level, radius):
        """Expose one known loaded target without expanding the map."""
        return [point()] if kind == 3 and level == 2 else []

    def query_collection(self, target_id):
        """Build fresh rates using current hero activity and optionally simulate user interruption."""
        if self.query_hook:
            hook, self.query_hook = self.query_hook, None
            hook()
        self.query_seq += 1
        rows = [metric(hero_id, self.speeds[hero_id], busy=state['busy'], hero_state=state['hero_state'],
                       action_state=5 if state['remaining_ms'] > 0 else 0)
                for hero_id, state in self.states.items()]
        return dict(target={**point(target_id), 'fresh': True, 'rules_known': True, 'can_collect': True,
                            'queue_free': self.queue_free, 'detail_seq': self.query_seq,
                            'available_seq': self.query_seq}, heroes=rows)

    def recover_hero(self, before, generation):
        """Apply exactly one authorized item and reserve no duplicate charge for another demand source."""
        hero_id = before['hero_id']
        assert hero_id in self.allowed and generation == self.hero_generation
        self.recoveries.append(hero_id)
        self.items -= 1
        state = self.states[hero_id]
        state['remaining_ms'] = max(0, state['remaining_ms'] - 300000)
        state['finish_ms'] -= 300000
        return {**state, 'items': self.items}

    def dispatch_collection(self, metrics, hero_id, generation):
        """Record one permitted departure, or an uncertain attempt that must never be retried."""
        assert self.collect_allowed and generation == self.collect_generation
        self.departures.append(hero_id)
        if self.fail_departure:
            raise TimeoutError('uncertain departure')
        self.states[hero_id].update(busy=True, hero_state=1)
        self.queue_free = False
        return dict(hero_id=hero_id, target_id=metrics['target']['target_id'], army_id=123), self.refresh_heroes()


class CollectionStrategyTests(unittest.TestCase):
    """Exercise user scope and rate ordering without treating cooldown as a reason to select second place."""

    def test_active_destinations_exclude_marching_collecting_but_not_returning_or_hunting(self):
        """An already-fetched own action list excludes inbound targets before field occupancy catches up."""
        stages=[dict(aim=1,state=state,target_id=index) for index,state in enumerate((2,3,6,9,7),1)]
        stages.append(dict(aim=3,state=2,target_id=6))
        active=active_resource_targets({'stages':stages})
        self.assertEqual(active,{1,2,3})
        rows=[point(i) for i in range(1,7)]
        self.assertEqual([r['target_id'] for r in candidate_targets(rows,CollectionOptions(),{},9999,active)], [4,5,6])
        with self.assertRaisesRegex(RuntimeError,'目标不明'):
            active_resource_targets({'stages':[dict(aim=1,state=2)]})

    def test_scope_and_candidates_cannot_silently_change_fixed_target(self):
        """Scope stays fixed while occupied cache entries still receive live eligibility queries."""
        options = CollectionOptions()
        rows = [point(), point(1, kind=2), point(2, level=3), point(3, distance=21),
                point(4, occupants=1), point(5, x=100), point(6, quantity=0)]
        self.assertEqual([row['target_id'] for row in candidate_targets(rows, options, {}, 0)], [4, 2792])
        self.assertEqual([row['target_id'] for row in candidate_targets(rows, options, {2792: 30}, 0)], [4])
        for value in ({'kind': True}, {'radius': 101}, {'level': 0}, {'mode': 'any'}, {'x': -1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CollectionOptions(**value)

    def test_cooling_first_place_is_retained_and_busy_first_place_is_skipped(self):
        """Recover the fastest idle hero, but never recover one who is marching or otherwise busy."""
        roster = hero_roster(hero_state(remaining_ms=600000), hero_state(hero_id=305, remaining_ms=0))
        metrics = dict(heroes=[metric(303, 300, action_state=5), metric(305, 200)])
        self.assertEqual(best_collector(metrics, roster)['hero_id'], 303)
        roster['heroes'][0]['busy'] = True
        self.assertEqual(best_collector(metrics, roster)['hero_id'], 305)
        roster['heroes'][1]['fresh'] = False
        self.assertIsNone(best_collector(metrics, roster))

    def test_list_scope_accepts_mixed_levels_and_requires_live_stock_checks(self):
        """Only listed positions within range qualify; stale cached stock/occupation never bypass a live query."""
        options = CollectionOptions(mode='list', coordinates=((97, 192), (101, 191)))
        rows = [point(1, level=4, x=97, y=192, distance=2, quantity=0, occupants=1),
                point(2, level=1, distance=4), point(3, x=99), point(4, distance=21), point(5, kind=2, distance=6)]
        self.assertEqual([row['target_id'] for row in candidate_targets(rows, options, {}, 0)], [1, 2, 5, 4])
        with self.assertRaises(ValueError):
            CollectionOptions(mode='list')
        coordinates = [[97, 192]]
        frozen = CollectionOptions(mode='list', coordinates=coordinates)
        coordinates[0][0] = 1
        self.assertEqual(frozen.coordinates, ((97, 192),))

    def test_quantity_threshold_has_exact_level_and_amount_boundaries(self):
        """Three-star scraps qualify, four-star39999 does not, and exactly40000 qualifies."""
        for level, quantity, expected in ((3, 1, True), (3, 0, False), (4, 39999, False),
                                          (4, 40000, True), (7, 39999, False), (7, 40001, True)):
            with self.subTest(level=level, quantity=quantity):
                self.assertEqual(quantity_allowed(level, quantity), expected)

    def test_shared_slots_require_capacity_native_permission_and_no_own_army(self):
        """Allow an allied occupant below capacity, while rejecting full, own, enemy and unknown states."""
        base = dict(point(level=4, occupants=1, capacity=2), rules_known=True, can_collect=True)
        for changes, expected in (({}, True), ({'occupants': 2}, False), ({'own_present': True}, False),
                                  ({'can_collect': False}, False), ({'rules_known': False}, False),
                                  ({'capacity': None}, False), ({'capacity': True}, False),
                                  ({'occupants': -1}, False), ({'own_present': None}, False)):
            with self.subTest(changes=changes):
                self.assertEqual(collection_slot_available({**base, **changes}), expected)


class SharedRecoveryTests(unittest.TestCase):
    """Drive the actual collection service and shared recovery method with both demand sources active."""

    def setUp(self):
        """Give each test its own log and clock so no sleep or game resources are involved."""
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.worker = Worker(queue.Queue())
        self.worker.log_path = Path(self.folder.name) / 'actions.jsonl'
        self.game = FakeCollectionGame()
        self.worker.connection = self.game
        clock = patch('time.monotonic', return_value=100)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    def start(self, normal=True):
        """Start the known iron target and optionally the same hero's ordinary recovery switch."""
        if normal:
            self.worker.switch_hero(True, (303,))
        self.worker.switch_collection(True, CollectionOptions())
        self.worker.collection.tick(self.game)

    def test_unsent_busy_hero_replans_to_next_hero_without_closing(self):
        """A hero occupied after selection causes one bounded recheck and a new eligible selection."""
        self.game.states[303]['remaining_ms']=0
        original=self.game.dispatch_collection
        attempts=[]
        def dispatch(metrics,hero_id,generation):
            """Simulate a pre-send race once, then use the real fake sender to verify selection."""
            attempts.append(hero_id)
            if len(attempts)==1:
                self.game.states[303].update(busy=True,hero_state=1)
                raise CollectionReplan('definitely unsent')
            return original(metrics,hero_id,generation)
        self.game.dispatch_collection=dispatch
        self.start(normal=False)
        self.assertTrue(self.worker.collection.enabled);self.assertEqual(self.game.departures,[])
        self.clock.return_value=101;self.worker.collection.tick(self.game)
        self.assertEqual(attempts,[303,305]);self.assertEqual(self.game.departures,[305])
        self.assertTrue(self.worker.collection.enabled)

    def test_repeated_unsent_changes_wait_for_event_not_fixed_retries(self):
        """Persistent preflight changes retain the master but stop automatic rechecks after one retry."""
        self.game.states[303]['remaining_ms']=0
        self.game.dispatch_collection=Mock(side_effect=CollectionReplan('definitely unsent'))
        self.start(normal=False)
        self.clock.return_value=101;self.worker.collection.tick(self.game)
        for now in (102,103,9999):
            self.clock.return_value=now;self.worker.collection.tick(self.game)
        self.assertTrue(self.worker.collection.enabled)
        self.assertEqual(self.game.dispatch_collection.call_count,2)
        self.assertEqual(self.game.departures,[])

    def test_expired_target_queue_status_rechecks_without_reporting_full(self):
        """A3/4 stale preflight goes through bounded refresh instead of waiting as though all slots are used."""
        self.game.states[303]['remaining_ms']=0
        original=self.game.query_collection
        reads=[]
        def query(target):
            """Expire only the first target's hero/army evidence after the earlier capacity snapshot."""
            result=original(target);reads.append(target)
            if len(reads)==1:
                result['target'].update(queue_free=False,queue_reason='stale',queue_used=3,queue_limit=4)
            return result
        self.game.query_collection=query
        self.start(normal=False)
        self.assertTrue(self.worker.collection.enabled);self.assertEqual(self.game.departures,[])
        self.assertEqual(self.worker.collection.due,0)
        self.clock.return_value=101;self.worker.collection.tick(self.game)
        self.assertEqual(self.game.departures,[303]);self.assertEqual(len(reads),2)

    def test_overlapping_sources_charge_only_once_per_confirmed_item(self):
        """Two sources for303 produce two needed items, not two parallel two-item sequences."""
        self.start()
        self.assertEqual(self.worker.recovery_authorized, (303,))
        self.assertEqual(self.game.gates, [(303,)])
        self.assertTrue(self.worker.hero_tick(self.game))
        self.assertTrue(self.worker.hero_tick(self.game))
        self.clock.return_value = 101
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.recoveries, [303, 303])
        self.assertEqual(self.game.items, 28)
        self.assertEqual(self.game.departures, [303])
        self.worker.hero_tick(self.game)
        self.assertEqual(self.game.recoveries, [303, 303])

    def test_stopping_collection_preserves_normal_authorization(self):
        """Removing collection's demand does not remove a still-enabled explicit recovery choice."""
        self.start()
        self.worker.switch_collection(False)
        self.assertEqual(self.worker.recovery_authorized, (303,))
        self.worker.hero_tick(self.game)
        self.assertEqual(self.game.recoveries, [303])
        self.assertEqual(self.game.departures, [])

    def test_stopping_normal_recovery_preserves_collection_demand(self):
        """The normal switch may be off while collection's explicitly approved recovery finishes."""
        self.start()
        self.worker.switch_hero(False)
        self.assertEqual(self.worker.recovery_authorized, (303,))
        self.worker.hero_tick(self.game)
        self.worker.hero_tick(self.game)
        self.clock.return_value = 101
        self.worker.collection.tick(self.game)
        self.assertFalse(self.worker.hero_enabled)
        self.assertEqual(self.game.departures, [303])
        self.assertEqual(self.worker.recovery_authorized, ())

    def test_stopping_both_or_a_full_queue_cancels_collection_only_recovery(self):
        """No remaining demand or queue capacity means no more collection-funded recovery items."""
        self.start(normal=False)
        self.worker.switch_collection(False)
        self.worker.hero_tick(self.game)
        self.assertEqual(self.game.recoveries, [])
        self.assertEqual(self.worker.recovery_authorized, ())
        self.start(normal=False)
        self.game.queue_free = False
        self.worker.hero_tick(self.game)
        self.assertEqual(self.game.recoveries, [])
        self.assertEqual(self.worker.recovery_authorized, ())

    def test_busy_top_hero_uses_next_without_any_recovery(self):
        """Being busy is not fixed by recovery items, so second place is used directly."""
        self.game.states[303].update(busy=True, hero_state=4)
        self.start(normal=False)
        self.assertEqual(self.game.departures, [305])
        self.assertEqual(self.game.recoveries, [])

    def test_service_dispatches_to_occupied_allied_point_with_free_slot(self):
        """Exercise the real service so its old occupied-point filter cannot silently survive."""
        query = self.game.query_collection
        def allied_query(target_id):
            """Return a fresh target with one of its two configured slots occupied."""
            result = query(target_id)
            result['target'].update(occupants=1, capacity=2, own_present=False)
            return result
        self.game.query_collection = allied_query
        self.game.states[303]['remaining_ms'] = 0
        self.start(normal=False)
        self.assertEqual(self.game.departures, [303])

    def test_own_presence_prevents_collection_recovery_demand(self):
        """An own army at a shared resource must be rejected before spending cooldown items."""
        query = self.game.query_collection
        def own_query(target_id):
            """Return an own occupied target that still has spare physical capacity."""
            result = query(target_id)
            result['target'].update(occupants=1, capacity=2, own_present=True)
            return result
        self.game.query_collection = own_query
        self.start(normal=False)
        self.worker.hero_tick(self.game)
        self.assertEqual(self.game.departures, [])
        self.assertEqual(self.game.recoveries, [])
        self.assertEqual(self.worker.recovery_authorized, ())

    def test_user_off_during_query_never_authorizes_or_dispatches(self):
        """A late response from a disabled run cannot open either spending gate."""
        self.game.query_hook = lambda: self.worker.switch_collection(False)
        self.start(normal=False)
        self.assertEqual(self.game.departures, [])
        self.assertEqual(self.game.recoveries, [])
        self.assertEqual(self.game.allowed, set())

    def test_uncertain_departure_stops_instead_of_retrying(self):
        """An unknown server outcome closes collection even if the hero still appears idle locally."""
        self.game.states[303]['remaining_ms'] = 0
        self.game.fail_departure = True
        self.start(normal=False)
        self.worker.collection.tick(self.game)
        self.assertFalse(self.worker.collection.enabled)
        self.assertEqual(self.game.departures, [303])


class ListCollectionGame(FakeCollectionGame):
    """Separate stale map candidates from live resource quantities to exercise the real scheduler."""

    def __init__(self):
        super().__init__()
        self.points = [point(1, level=4, x=97, y=192, distance=2, quantity=50000),
                       point(2, level=5, x=101, y=191, distance=4, quantity=50000)]
        self.live = {1: {'quantity': 39999}, 2: {'quantity': 40000}}
        self.queries = []
        self.target_departures = []

    def collection_candidates(self, kind, level, radius):
        """A level-zero request enumerates all loaded levels for the selected resource."""
        assert (kind, level, radius) == (0, 0, 0)
        return self.points

    def collection_list_candidates(self, coordinates, generation, cancelled=None):
        """Existing scenarios have all points cached; region-loading regressions override this transport seam."""
        return {'rows': self.collection_candidates(0,0,0), 'regions_loaded': 0}

    def collection_balance(self, cancelled):
        """Exercise the real balancing policy with isolated authoritative manual/automatic army records."""
        armies = [dict(row) for row in self.schedule['stages']]
        metrics = {}
        for army in armies:
            target = next((row for row in self.points if row['target_id'] == army.get('target_id')), None)
            if target:
                metrics[army['target_id']] = dict(target=target, heroes=[dict(hero_id=army['hero_id'],load=40000)],
                    collectors=[dict(army_id=army['army_id'],hero_id=army['hero_id'],count=0,maximum=40000)])
        snapshot = dict(self.stock, armies=armies, queue_limit=self.collection_call('collect_status')['queue_limit'])
        return dict(balance=resource_balance(snapshot, metrics), roster=None)

    def query_collection(self, target_id):
        """Deliver current quantity independent of cached quantity and preserve the queried identity."""
        self.queries.append(target_id)
        result = super().query_collection(target_id)
        result['target'].update(next(row for row in self.points if row['target_id'] == target_id))
        result['target'].update(self.live.get(target_id, {}))
        return result

    def dispatch_collection(self, metrics, hero_id, generation):
        """Record the resource identity accepted by the scheduler without spending in the real game."""
        self.target_departures.append(metrics['target']['target_id'])
        return super().dispatch_collection(metrics, hero_id, generation)


class ResourceListServiceTests(unittest.TestCase):
    """Run list decisions through the existing serialized service and shared recovery gate."""

    setUp = SharedRecoveryTests.setUp

    def test_balance_prefers_scarce_wood_over_nearer_iron(self):
        """The serial service chooses the scarce type, then retains nearest-point ordering within it."""
        self.game=ListCollectionGame();self.worker.connection=self.game
        self.game.points[0]['kind']=3
        self.game.points[1]['kind']=2
        self.game.live={1:dict(quantity=50000),2:dict(quantity=50000)}
        self.game.stock=dict(food=300000,wood=10000,iron=200000)
        self.game.states[303]['remaining_ms']=0
        self.start_list()
        self.assertEqual(self.game.target_departures,[2])
        self.assertEqual(self.game.queries,[2])

    def test_manual_same_type_limit_waits_without_fixed_forecast_or_target_queries(self):
        """Manual inbound/collecting trips count even outside the saved list; elapsed time adds no retries."""
        self.game=ListCollectionGame();self.worker.connection=self.game
        self.game.points=[point(i,x=96+i,y=191) for i in (1,2,3)]
        self.game.live={i:dict(quantity=50000) for i in (1,2,3)}
        self.game.schedule['stages']=[dict(army_id=100+i,hero_id=300+i,aim=1,state=state,
                                         target_id=i,end_ms=2000000) for i,state in ((1,2),(2,6))]
        self.game.collection_balance=Mock(wraps=self.game.collection_balance)
        self.worker.switch_collection(True,CollectionOptions(mode='list',coordinates=((99,191),)))
        self.worker.collection.tick(self.game)
        for now in (101,110,200):
            self.clock.return_value=now;self.worker.collection.tick(self.game)
        self.game.collection_balance.assert_called_once()
        self.assertEqual(self.game.queries,[])
        self.assertEqual(self.game.target_departures,[])
        self.assertTrue(self.worker.collection.enabled)

    def test_confirmed_first_haul_changes_second_resource_choice(self):
        """The next free team considers the first confirmed trip instead of reusing the old inventory ranking."""
        self.game=ListCollectionGame();self.worker.connection=self.game
        self.game.points=[point(1,kind=3,x=97,y=192),point(2,kind=2,x=101,y=191),point(3,kind=3,x=102,y=191)]
        self.game.live={i:dict(quantity=100000) for i in (1,2,3)}
        self.game.stock=dict(food=100000,wood=30000,iron=10000)
        self.game.states[303]['remaining_ms']=0
        original=self.game.dispatch_collection
        def dispatch(metrics,hero_id,generation):
            """Model a successful matching receipt before exposing the new marching trip."""
            receipt,roster=original(metrics,hero_id,generation)
            self.game.schedule['stages'].append(dict(army_id=123,hero_id=hero_id,aim=1,state=2,
                target_id=metrics['target']['target_id'],end_ms=2000000))
            self.game.queue_free=len(self.game.departures)<2
            return receipt,roster
        self.game.dispatch_collection=dispatch
        self.worker.switch_collection(True,CollectionOptions(mode='list',coordinates=tuple(
            (p['x'],p['y']) for p in self.game.points)))
        self.worker.collection.tick(self.game)
        self.clock.return_value=101;self.worker.collection.tick(self.game)
        self.assertEqual(self.game.target_departures,[1,2])

    def test_confirmed_missing_point_is_removed_saved_and_next_point_continues(self):
        """A matched6001 deletes only its coordinate and does not prevent another valid resource dispatch."""
        self.game=ListCollectionGame()
        self.worker.connection=self.game
        self.game.states[303]['remaining_ms']=0
        path=Path(self.folder.name)/'resources.json'
        save_coordinates(((97,192),(101,191),(5,5)),path)
        original=self.game.query_collection
        def query(target_id):
            """Only the first mapped resource is explicitly missing; the second still returns normal data."""
            if target_id==1:
                raise ResourceMissing(1)
            return original(target_id)
        self.game.query_collection=query
        with patch('collection_service.remove_coordinate',side_effect=lambda p:remove_coordinate(p,path)):
            self.start_list()
        self.assertEqual(load_coordinates(path),((101,191),(5,5)))
        self.assertEqual(self.game.target_departures,[2])
        self.assertEqual(self.worker.collection.run.options.coordinates,((101,191),))

    def test_all_missing_points_empty_saved_list_and_disable_collection(self):
        """The final confirmed deletion stops collection without recovery, dispatch or re-enabling it."""
        self.game=ListCollectionGame()
        self.worker.connection=self.game
        path=Path(self.folder.name)/'resources.json'
        save_coordinates(((97,192),(101,191)),path)
        self.game.query_collection=Mock(side_effect=lambda target: (_ for _ in ()).throw(ResourceMissing(target)))
        with patch('collection_service.remove_coordinate',side_effect=lambda p:remove_coordinate(p,path)):
            self.start_list()
        self.assertEqual(load_coordinates(path),())
        self.assertFalse(self.worker.collection.enabled)
        self.assertEqual(self.game.departures,[])
        self.assertEqual(self.game.recoveries,[])

    def test_cache_miss_timeout_and_occupied_or_low_stock_never_delete_points(self):
        """Unavailable discovery and ordinary ineligibility never authorize persistent list changes."""
        self.game=ListCollectionGame()
        self.worker.connection=self.game
        with patch('collection_service.remove_coordinate') as remove:
            self.game.points=[]
            self.start_list()
            self.worker.switch_collection(False)
            self.game.points=[point(1,level=4,x=97,y=192)]
            self.game.query_collection=Mock(side_effect=TimeoutError('read timeout'))
            self.start_list()
            remove.assert_not_called()

    def start_list(self):
        """Start two known positions without granting ordinary automatic recovery."""
        self.worker.switch_collection(True, CollectionOptions(mode='list', coordinates=((97, 192), (101, 191))))
        self.worker.collection.tick(self.game)

    def test_nearest_insufficient_point_is_skipped_for_the_next_live_qualified_point(self):
        """A stale50000 cache cannot cause dispatch to a four-star point whose live stock is39999."""
        self.game = ListCollectionGame()
        self.worker.connection = self.game
        self.game.states[303]['remaining_ms'] = 0
        self.start_list()
        self.assertEqual(self.game.queries, [1, 2])
        self.assertEqual(self.game.target_departures, [2])
        self.assertEqual(self.game.recoveries, [])

    def test_all_insufficient_points_authorize_no_recovery_and_no_departure(self):
        """Do not spend cooldown items for a hero when every selected target fails the stock rule."""
        self.game = ListCollectionGame()
        self.worker.connection = self.game
        self.game.live[2] = {'quantity': 39999}
        self.start_list()
        self.worker.hero_tick(self.game)
        self.assertEqual(self.game.queries, [1, 2])
        self.assertEqual(self.worker.recovery_authorized, ())
        self.assertEqual(self.game.recoveries, [])
        self.assertEqual(self.game.departures, [])

    def test_lower_level_small_live_stock_is_selected_first(self):
        """A low-level point with one remaining resource is still preferred when it is nearer."""
        self.game = ListCollectionGame()
        self.worker.connection = self.game
        self.game.points[0]['level'] = 3
        self.game.points[0].update(quantity=0, occupants=1)
        self.game.live[1] = {'quantity': 1, 'occupants': 0}
        self.game.states[303]['remaining_ms'] = 0
        self.start_list()
        self.assertEqual(self.game.queries, [1])
        self.assertEqual(self.game.target_departures, [1])

    def test_two_free_queues_dispatch_different_heroes_to_mixed_resources(self):
        """A confirmed first trip must not leave a free second queue idle behind old kind/radius filters."""
        self.game = ListCollectionGame()
        self.worker.connection = self.game
        self.game.points[0]['kind'] = 2
        self.game.points[1].update(kind=1, distance=35)
        self.game.live[1]['quantity'] = 40000
        self.game.states[303]['remaining_ms'] = 0
        original_dispatch = self.game.dispatch_collection

        def dispatch(metrics, hero_id, generation):
            """Confirm a trip, mark its point occupied, and keep the second queue available."""
            self.assertEqual(metrics['target']['scope_radius'], 0)
            receipt, roster = original_dispatch(metrics, hero_id, generation)
            self.game.live[metrics['target']['target_id']]['occupants'] = 1
            self.game.queue_free = len(self.game.departures) < 2
            return receipt, roster

        self.game.dispatch_collection = dispatch
        self.start_list()
        self.clock.return_value = 101
        self.worker.collection.tick(self.game)
        self.worker.collection.due = 0
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.target_departures, [1, 2])
        self.assertEqual(self.game.departures, [303, 305])
        self.assertEqual(self.game.recoveries, [])

    def test_three_empty_queues_choose_different_targets_even_with_slow_steps_and_empty_field_lists(self):
        """Sixty-second scheduling gaps cannot send three heroes to the nearest already-inbound destination."""
        self.game=ListCollectionGame();self.worker.connection=self.game
        self.game.points=[point(i,kind=i,x=96+i,y=191,distance=i) for i in (1,2,3)]
        self.game.live={i:dict(quantity=50000,occupants=0,own_present=False) for i in (1,2,3)}
        self.game.states={i:hero_state(hero_id=i,remaining_ms=0) for i in (303,305,306)}
        self.game.speeds={303:300,305:200,306:100}
        original=self.game.dispatch_collection
        def dispatch(metrics,hero_id,generation):
            """Only authoritative action destinations change; resource-field resident lists remain empty."""
            receipt,roster=original(metrics,hero_id,generation)
            receipt['army_id']=120+len(self.game.departures)
            self.game.schedule['stages'].append(dict(army_id=receipt['army_id'],hero_id=hero_id,
                aim=1,state=2,target_id=metrics['target']['target_id'],end_ms=2000000))
            self.game.queue_free=len(self.game.departures)<3
            return receipt,roster
        self.game.dispatch_collection=dispatch
        self.worker.switch_collection(True,CollectionOptions(mode='list',coordinates=tuple(
            (r['x'],r['y']) for r in self.game.points)))
        for now in (100,160,220):
            self.clock.return_value=now;self.worker.collection.tick(self.game)
        self.assertEqual(self.game.target_departures,[1,2,3])
        self.assertEqual(self.game.queries,[1,2,3])
        self.assertEqual(self.game.recoveries,[])

    def setup_region_loading(self):
        """Model two active targets in the screen cache and a third saved point outside that cache."""
        self.game=ListCollectionGame();self.worker.connection=self.game
        self.game.points=[point(i,kind=i,x=96+i,y=191,distance=i) for i in (1,2,3)]
        self.game.live={i:dict(quantity=50000) for i in (1,2,3)}
        self.game.states={i:hero_state(hero_id=i,remaining_ms=0,busy=i!=306,hero_state=0 if i==306 else 1)
                          for i in (303,305,306)}
        self.game.speeds={303:300,305:200,306:100}
        self.game.schedule['stages']=[dict(army_id=120+i,hero_id=h,aim=1,state=6,target_id=i,end_ms=2000000)
                                      for i,h in ((1,303),(2,305))]
        self.game.collection_candidates=lambda *args:self.game.points[:2]
        self.game.collection_list_candidates=Mock(return_value={'rows':self.game.points,'regions_loaded':1})
        self.worker.switch_collection(True,CollectionOptions(mode='list',coordinates=tuple(
            (r['x'],r['y']) for r in self.game.points)))

    def test_missing_saved_point_loads_and_fills_third_slot_after_rechecking_own_targets(self):
        """The real scheduler fills the free third queue without reusing either cached active resource."""
        self.setup_region_loading()
        self.worker.collection.tick(self.game)
        self.game.collection_list_candidates.assert_called_once()
        self.assertEqual(self.game.queries,[3])
        self.assertEqual(self.game.target_departures,[3])
        self.assertEqual(self.game.departures,[306])

    def test_capacity_change_during_region_loading_and_full_initial_queue_do_not_depart(self):
        """A free slot observed before a slow load cannot authorize departure after manual dispatch fills it."""
        self.setup_region_loading()
        def load(*args):
            """Simulate a manual team consuming the last quota during the region response."""
            self.game.queue_free=False
            return {'rows':self.game.points,'regions_loaded':1}
        self.game.collection_list_candidates.side_effect=load
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.queries,[]);self.assertEqual(self.game.departures,[])
        self.setup_region_loading();self.game.queue_free=False
        self.worker.collection.tick(self.game)
        self.game.collection_list_candidates.assert_not_called()

    def test_stop_during_missing_point_loading_never_queries_or_departs_afterward(self):
        """Cancelling a saved-list lookup invalidates its result before any target or hero is selected."""
        self.setup_region_loading()
        def load(*args):
            """Return late data only after the user has closed the collection switch."""
            self.worker.switch_collection(False)
            return {'rows':self.game.points,'regions_loaded':1}
        self.game.collection_list_candidates.side_effect=load
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.queries,[]);self.assertEqual(self.game.departures,[])

    def test_empty_loaded_regions_preserve_saved_points_and_wait_without_fixed_reload(self):
        """An area with no matching resource is not an attributed6001 and cannot delete a saved coordinate."""
        self.setup_region_loading()
        self.game.collection_list_candidates.return_value={'rows':[],'regions_loaded':1}
        with patch('collection_service.remove_coordinate') as remove:
            self.worker.collection.tick(self.game)
            for now in (101,110,130,160):
                self.clock.return_value=now;self.worker.collection.tick(self.game)
            remove.assert_not_called()
        self.game.collection_list_candidates.assert_called_once()
        self.assertEqual(len(self.worker.collection.run.options.coordinates),3)
        self.assertEqual(self.game.departures,[])

    def test_dynamic_server_capacity_fills_two_then_four_without_duplicate_heroes(self):
        """Changing the confirmed limit from2 to4 permits two more trips, never a hardcoded team count."""
        self.game = ListCollectionGame()
        self.worker.connection = self.game
        self.game.points = [point(i + 1, x=100 + i, y=190, distance=i + 1) for i in range(4)]
        self.game.live = {i + 1: {'quantity': 50000} for i in range(4)}
        self.game.states = {i: hero_state(hero_id=i, remaining_ms=0) for i in (303, 305, 114, 242)}
        self.game.speeds = {303: 400, 305: 300, 114: 200, 242: 100}
        limit = [2]

        def queue(operation):
            """Model server-supplied capacity and current usage rather than a fixed two-team boolean."""
            if operation == 'collect_schedule':
                return self.game.schedule
            used = len(self.game.departures)
            return dict(queue_used=used, queue_limit=limit[0], queue_known=True, queue_free=used < limit[0])

        original_dispatch = self.game.dispatch_collection

        def dispatch(metrics, hero_id, generation):
            """Occupy the selected target and update capacity only after a simulated confirmed departure."""
            self.assertLess(len(self.game.departures), limit[0])
            result = original_dispatch(metrics, hero_id, generation)
            self.game.live[metrics['target']['target_id']]['occupants'] = 1
            self.game.queue_free = len(self.game.departures) < limit[0]
            return result

        self.game.collection_call = queue
        self.game.dispatch_collection = dispatch
        self.worker.switch_collection(True, CollectionOptions(mode='list', coordinates=tuple(
            (row['x'], row['y']) for row in self.game.points)))
        for now in range(100, 104):
            self.clock.return_value = now
            self.worker.collection.tick(self.game)
        self.assertEqual(len(self.game.departures), 2)
        limit[0] = 4
        self.game.queue_free = True
        self.worker.collection.request_check()
        for now in range(104, 109):
            self.clock.return_value = now
            self.worker.collection.tick(self.game)
        self.assertEqual(len(self.game.departures), 4)
        self.assertEqual(len(set(self.game.departures)), 4)


class CollectionPushServiceTests(unittest.TestCase):
    """Bound discovery under notification storms while always confirming server state before dispatch."""

    setUp = SharedRecoveryTests.setUp

    def test_pushes_coalesce_and_full_queue_checks_do_not_query_barracks(self):
        """Push hints merge at1 check/s; elapsed wall time alone never causes fallback queries."""
        self.game.queue_free = False
        self.game.refresh_heroes = Mock(wraps=self.game.refresh_heroes)
        self.game.prepare_collection = Mock()
        self.worker.switch_collection(True, CollectionOptions())
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 1)
        self.game.push_seq = 200
        self.clock.return_value = 100.25
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 1)
        self.clock.return_value = 101
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 2)
        self.clock.return_value = 103.99
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 2)
        self.clock.return_value = 104
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 2)
        self.game.prepare_collection.assert_not_called()
        self.worker.switch_collection(False)
        self.game.push_seq += 1
        self.clock.return_value = 110
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 2)

    def test_retreat_hint_does_not_dispatch_until_server_confirms_queue_free(self):
        """Manual retreat does not pause; a returning army still occupies capacity until confirmed free."""
        self.game.queue_free = False
        self.game.states[303]['remaining_ms'] = 0
        self.worker.switch_collection(True, CollectionOptions())
        self.worker.collection.tick(self.game)
        self.game.push_seq = 1
        self.clock.return_value = 101
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.departures, [])
        self.assertTrue(self.worker.collection.enabled)
        self.game.queue_free = True
        self.game.push_seq = 2
        self.clock.return_value = 102
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.departures, [303])

    def test_server_phase_deadline_checks_once_without_periodic_queries(self):
        """A full queue stays quiet until its server deadline; an unchanged expired stage does not loop."""
        self.game.queue_free = False
        self.game.schedule = {'server_now_ms': 1000000,
                              'stages': [{'army_id': 123, 'state': 6, 'end_ms': 1060000}]}
        self.game.refresh_heroes = Mock(wraps=self.game.refresh_heroes)
        self.worker.switch_collection(True, CollectionOptions())
        self.worker.collection.tick(self.game)
        for now in (103, 110, 130, 160.9):
            self.clock.return_value = now
            self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 1)
        self.clock.return_value = 161
        self.game.schedule['server_now_ms'] = 1061000
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 2)
        self.clock.return_value = 1000
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 2)
        self.worker.collection.request_check()
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.refresh_heroes.call_count, 3)

    def test_future_server_phase_updates_then_return_allows_collection(self):
        """Arrival transitions rearm using the new server deadline, never a speed-derived duration."""
        self.game.queue_free = False
        self.game.states[303]['remaining_ms'] = 0
        self.game.schedule = {'server_now_ms': 1000000,
                              'stages': [{'army_id': 123, 'state': 6, 'end_ms': 1060000}]}
        self.worker.switch_collection(True, CollectionOptions())
        self.worker.collection.tick(self.game)
        self.clock.return_value = 161
        self.game.schedule = {'server_now_ms': 1061000,
                              'stages': [{'army_id': 123, 'state': 9, 'end_ms': 1091000}]}
        self.worker.collection.tick(self.game)
        self.assertEqual(self.worker.collection.due, 192)
        self.assertEqual(self.game.departures, [])
        self.clock.return_value = 192
        self.game.queue_free = True
        self.game.schedule = {'server_now_ms': 1092000, 'stages': []}
        self.worker.collection.tick(self.game)
        self.assertEqual(self.game.departures, [303])


if __name__ == '__main__':
    unittest.main()
