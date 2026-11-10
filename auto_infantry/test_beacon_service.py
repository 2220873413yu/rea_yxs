"""Exercise rescue orchestration without an emulator, network traffic or item consumption."""
import copy
import threading
import unittest
from unittest.mock import Mock, patch

from beacon_service import BeaconService, beacon_schedule, choose_rescue_hero
from game_log import BeaconRejected,BeaconCapacityUnavailable


def event(identifier=10, kind=1, state=0, army_id=0):
    """Build a visible event with a server end time for state-transition tests."""
    return dict(event_id=identifier, kind=kind, state=state, army_id=army_id,
                end_ms=200000, distance=2, visible=True, x=90, y=80)


class BeaconServiceTests(unittest.TestCase):
    """Cover startup reconciliation, serial actions, native capacity and cancellation."""

    def setUp(self):
        """Replace only connection I/O and keep the real scheduler and decision logic."""
        self.owner=Mock(guard=threading.RLock(), closing=threading.Event())
        self.c=Mock(beacon_generation=7)
        self.owner.connection=self.c
        self.s=BeaconService(self.owner)
        self.snapshot=dict(server_now_ms=100000, refresh_end_ms=400000, queue_limit=4,
                           queue_used=0, queue_full=False, events=[event()], armies=[])
        self.roster=dict(heroes=[])
        self.c.query_beacon.side_effect=lambda *a: copy.deepcopy(self.snapshot)
        self.c.refresh_heroes.side_effect=lambda: copy.deepcopy(self.roster)
        self.c.beacon_call.side_effect=lambda op,*args: ({'signature':'stable'} if op=='beacon_watch'
                                                 else copy.deepcopy(self.snapshot))
        self.c.query_beacon_candidates.return_value=dict(heroes=[
            dict(hero_id=303, ready=True, power=100, travel_seconds=5)])
        self.c.beacon_action.side_effect=self.accept

    def accept(self, operation, identifier, generation, **kwargs):
        """Advance fake authoritative states after exactly one accepted request."""
        e=next(e for e in self.snapshot['events'] if e['event_id']==identifier)
        if operation=='dispatch':
            e.update(state=1,army_id=77)
            self.snapshot['queue_used']+=1
            self.snapshot['armies'].append(dict(army_id=77, hero_id=303, state=2,
                                               target_id=identifier, end_ms=150000))
        elif operation=='recall':
            e.update(state=3,army_id=0)
            self.snapshot['armies'][0]['state']=9
        elif operation=='scout':
            e['state']=1
            self.snapshot['scouts']=[dict(x=e['x'],y=e['y'],end_ms=150000)]
        elif operation=='skip':
            e['state']=3
            self.snapshot['armies'][0]['state']=9
        else:
            self.snapshot['events'].remove(e)
        return dict(ret=0),copy.deepcopy(self.snapshot),copy.deepcopy(self.roster)

    def test_startup_is_readonly_and_no_fixed_server_polling(self):
        """Startup checks once with the switch off; repeated worker ticks generate no GETs."""
        for _ in range(20):self.s.tick(self.c)
        self.c.query_beacon.assert_called_once()
        self.c.beacon_action.assert_not_called()
        self.assertFalse(self.s.enabled)

    def test_dispatch_arrival_recall_claim_and_return_are_separate(self):
        """Do not recall a marching hero or regard a completed event as a returned army."""
        self.s.switch(True);self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[:3],('dispatch',10,7))
        self.snapshot['events'][0]['state']=2
        self.snapshot['armies'][0]['state']=6
        self.s.request_check();self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[0],'recall')
        self.s.request_check();self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[0],'claim')
        self.assertEqual(self.snapshot['armies'][0]['state'],9)
        self.assertEqual(self.c.beacon_action.call_count,3)

    def test_capacity_is_server_driven_and_full_queue_waits(self):
        """A server limit of five permits a fourth departure; a full server queue sends nothing."""
        self.snapshot.update(queue_used=3,queue_limit=5)
        self.s.switch(True);self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_count,1)
        self.snapshot.update(queue_used=5,events=[event(11)])
        self.s.request_check();self.s.tick(self.c)
        for _ in range(20):self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_count,1)
        self.assertEqual(self.c.query_beacon.call_count,2)

    def test_other_types_never_execute_even_if_complete(self):
        """Monster/resource/treasure events are visible but never acted on in this release."""
        self.snapshot['events']=[event(i,kind=i,state=state) for i,state in ((2,3),(3,2),(4,0))]
        self.s.switch(True);self.s.tick(self.c)
        self.c.beacon_action.assert_not_called()
        self.c.query_beacon_candidates.assert_not_called()

    def test_disabled_during_candidate_read_cannot_depart(self):
        """The final epoch guard cancels a departure planned before the checkbox changed."""
        def disable(*args):
            """Simulate the GUI turning the feature off while a read completes."""
            self.s.switch(False)
            return dict(heroes=[dict(hero_id=303,ready=True,power=1,travel_seconds=1)])
        self.c.query_beacon_candidates.side_effect=disable
        self.s.switch(True);self.s.tick(self.c)
        self.c.beacon_action.assert_not_called()
        self.c.set_beacon_enabled.assert_called_with(False)

    def test_ambiguous_action_blocks_reenable_and_never_retries(self):
        """A response timeout cannot cause another departure or be cleared by toggling on."""
        self.c.beacon_action.side_effect=TimeoutError('result unknown')
        self.s.switch(True);self.s.tick(self.c)
        for _ in range(10):self.s.tick(self.c)
        self.assertFalse(self.s.enabled)
        self.assertTrue(self.s.uncertain)
        self.c.beacon_action.assert_called_once()
        with self.assertRaises(RuntimeError):self.s.switch(True)

    def test_passive_change_triggers_one_check_without_periodic_get(self):
        """Repeated local signatures are free; a changed signature authorizes one server check."""
        self.snapshot['events']=[]
        self.s.switch(True)
        with patch('beacon_service.time.monotonic',return_value=100):self.s.tick(self.c)
        with patch('beacon_service.time.monotonic',return_value=102):
            for _ in range(10):self.s.tick(self.c)
        self.assertEqual(self.c.query_beacon.call_count,1)
        original=self.c.beacon_call.side_effect
        self.c.beacon_call.side_effect=lambda op: {'signature':'push'} if op=='beacon_watch' else original(op)
        with patch('beacon_service.time.monotonic',return_value=104):self.s.tick(self.c)
        self.assertEqual(self.c.query_beacon.call_count,2)

    def test_completed_old_timer_is_removed_but_return_timer_retained(self):
        """Do not wait the original rescue duration after early recall has completed the event."""
        self.snapshot['events']=[event(state=3)]
        self.snapshot['armies']=[dict(army_id=77,state=9,end_ms=120000)]
        stages=beacon_schedule(self.snapshot,self.roster)['stages']
        self.assertEqual({a['army_id'] for a in stages},{77,-1})

    def test_server_deadline_checks_once_and_expired_cache_cannot_loop(self):
        """An unchanged expired server deadline is consumed once rather than polled repeatedly."""
        self.snapshot.update(events=[],refresh_end_ms=100500)
        self.s.switch(True)
        with patch('beacon_service.time.monotonic',return_value=100):self.s.tick(self.c)
        with patch('beacon_service.time.monotonic',return_value=102):self.s.tick(self.c)
        with patch('beacon_service.time.monotonic',return_value=120):
            for _ in range(20):self.s.tick(self.c)
        self.assertEqual(self.c.query_beacon.call_count,2)
        self.assertEqual(self.s.due,float('inf'))

    def test_ready_low_power_then_fast_hero_and_no_recovery_items(self):
        """Busy/cooling heroes cannot win selection, regardless of strength or travel speed."""
        heroes=[dict(hero_id=i,ready=ready,power=power,travel_seconds=seconds)
                for i,ready,power,seconds in ((1,False,1,1),(2,True,50,8),(3,True,50,4),(4,True,90,1))]
        self.assertEqual(choose_rescue_hero(dict(heroes=heroes))['hero_id'],3)
        self.c.query_beacon_candidates.return_value=dict(heroes=[])
        self.s.switch(True);self.s.tick(self.c)
        self.c.beacon_action.assert_not_called()
        self.assertFalse(any('recover' in str(call) for call in self.c.mock_calls))

    def test_treasure_can_scout_while_army_queue_is_full(self):
        """Treasure is outside the native hero-army counter, while unselected types stay inactive."""
        self.snapshot.update(events=[event(kind=2)],queue_used=4,queue_full=True)
        self.c.query_beacon_scout.return_value=dict(eligible=True,fresh=True,stock=3,cost=1)
        self.s.switch(True,(2,));self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[0],'scout')
        self.assertEqual(self.snapshot['scouts'][0]['end_ms'],150000)
        self.s.request_check();self.s.tick(self.c)
        self.c.query_beacon_scout.assert_called_once()

    def test_shortage_waits_without_scout_or_fixed_stock_queries(self):
        """A shortage produces a displayed cost and then waits for a real change or deadline."""
        self.snapshot.update(events=[event(kind=2)])
        self.c.query_beacon_scout.return_value=dict(eligible=False,fresh=True,stock=0,cost=3)
        self.s.switch(True,(2,));self.s.tick(self.c)
        for _ in range(20):self.s.tick(self.c)
        self.c.query_beacon_scout.assert_called_once()
        self.c.beacon_action.assert_not_called()

    def test_resource_prefers_speed_then_load_and_never_recalls_on_arrival(self):
        """The resource strategy cannot accidentally inherit rescue's arrival shortcut."""
        candidates=[dict(hero_id=i,ready=True,speed=speed,load=load,travel_seconds=seconds)
                    for i,speed,load,seconds in ((1,300,20000,2),(2,300,40000,4),(3,250,90000,1))]
        self.assertEqual(choose_rescue_hero(dict(heroes=candidates),3)['hero_id'],2)
        self.snapshot['events']=[event(kind=3,state=2,army_id=77)]
        self.snapshot['armies']=[dict(army_id=77,hero_id=303,state=6,target_id=10,end_ms=200000)]
        self.s.switch(True,(3,));self.s.tick(self.c)
        self.c.beacon_action.assert_not_called()

    def test_weak_monster_ignored_but_other_type_still_runs(self):
        """Rejecting a weak monster does not starve an eligible resource event."""
        self.snapshot['events']=[event(kind=4),event(11,kind=3)]
        self.c.query_beacon_candidates.side_effect=[dict(heroes=[dict(ready=False,overwhelming=False)]),
            dict(heroes=[dict(hero_id=303,ready=True,speed=300,load=40000,travel_seconds=1)])]
        self.s.switch(True,(3,4));self.s.last_kind=3;self.s.tick(self.c)
        self.assertIn(10,self.s.ignored)
        self.assertEqual(self.c.beacon_action.call_args.args[:2],('dispatch',11))
        self.s.switch(False);self.s.switch(True,(3,4));self.assertFalse(self.s.ignored)

    def test_monster_skip_is_not_repeated_and_only_selected_rewards_claimed(self):
        """Matched combat completion is reserved separately from claiming its reward."""
        self.snapshot['events']=[event(kind=4,state=2,army_id=77)]
        self.snapshot['armies']=[dict(army_id=77,hero_id=303,state=3,target_id=10,end_ms=200000)]
        self.s.switch(True,(4,));self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[0],'skip')
        self.assertIn(77,self.s.skipped)
        self.s.request_check();self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[0],'claim')

    def test_type_rotation_does_not_treat_scout_cache_expiry_as_completion(self):
        """Selected types rotate, while scout cache lifetime never schedules a false event-completion check."""
        self.snapshot['events']=[event(kind=1),event(11,kind=3)]
        self.c.query_beacon_candidates.return_value=dict(heroes=[dict(hero_id=303,ready=True,power=100,
                                                                    speed=300,load=40000,travel_seconds=5)])
        self.s.switch(True,(1,3));self.s.last_kind=1;self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_args.args[1],11)
        self.snapshot['scouts']=[dict(x=86,y=69,end_ms=120000)]
        stages=beacon_schedule(self.snapshot,self.roster,(2,))['stages']
        self.assertFalse(any(s['army_id']<-1000000000 for s in stages))

    def test_passive_watch_failure_stops_only_beacon_before_planning(self):
        """A local Lua getter error must not escape to Worker and disconnect unrelated automation."""
        original=self.c.beacon_call.side_effect
        self.c.beacon_call.side_effect=lambda op: (_ for _ in ()).throw(RuntimeError('getter missing')) if op=='beacon_watch' else original(op)
        self.s.switch(True);self.s.tick(self.c)
        self.assertFalse(self.s.enabled)
        self.assertFalse(self.owner.closing.is_set())
        self.c.beacon_action.assert_not_called()
        self.c.query_beacon.assert_not_called()
        self.c.set_beacon_enabled.assert_called_with(False)

    def test_final_watch_failure_cannot_escape_module_error_boundary(self):
        """The post-reconciliation passive read has the same isolated failure handling as the initial read."""
        self.snapshot['events']=[];original=self.c.beacon_call.side_effect;calls=[]
        def read(op):
            """Fail the second cached watch only, after a successful read-only reconciliation."""
            if op=='beacon_watch':
                calls.append(op)
                if len(calls)==2:raise RuntimeError('getter missing')
            return original(op)
        self.c.beacon_call.side_effect=read
        self.s.switch(True);self.s.tick(self.c)
        self.assertFalse(self.s.enabled)
        self.assertFalse(self.owner.closing.is_set())
        self.c.beacon_action.assert_not_called()

    def test_6395_keeps_switch_on_waits_and_resumes_only_after_return(self):
        """An exact server rejection releases only its unsent reservation and waits without polling or repeat sends."""
        self.snapshot.update(queue_used=1,armies=[dict(army_id=88,hero_id=304,state=9,target_id=99,end_ms=150000)])
        self.c.beacon_action.side_effect=BeaconRejected('dispatch',10,6395)
        self.s.switch(True);self.s.tick(self.c)
        self.assertTrue(self.s.enabled);self.assertFalse(self.s.uncertain)
        self.assertIsNotNone(self.s.capacity_wait)
        self.c.beacon_call.assert_any_call('beacon_rejected',(10,6395))
        query_count=self.c.query_beacon.call_count
        for _ in range(20):self.s.tick(self.c)
        self.assertEqual(self.c.query_beacon.call_count,query_count)
        self.assertEqual(self.c.beacon_action.call_count,1)
        # An explicit check with unchanged armies still cannot resubmit the rejected action.
        self.s.request_check();self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_count,1)
        self.snapshot.update(queue_used=0,armies=[])
        self.c.beacon_action.side_effect=self.accept
        self.s.request_check();self.s.tick(self.c)
        self.assertEqual(self.c.beacon_action.call_count,2)
        self.assertIsNone(self.s.capacity_wait)

    def test_full_returning_queue_stays_enabled_and_uses_return_deadline(self):
        """A4/4 queue containing returns waits on the earliest server return, with the switch still checked."""
        self.snapshot.update(queue_used=4,queue_full=True,returning_count=2,
            armies=[dict(army_id=88,hero_id=304,state=9,target_id=99,end_ms=120000)])
        self.s.switch(True)
        with patch('beacon_service.time.monotonic',return_value=100):self.s.tick(self.c)
        self.assertTrue(self.s.enabled)
        self.assertEqual(self.s.due,121)
        self.c.beacon_action.assert_not_called()

    def test_unattributed_6395_text_and_other_rejections_still_stop(self):
        """Only the typed exact dispatch rejection can recover; error text and claim errors cannot relax safety."""
        for error in (TimeoutError('6395 result unknown'),RuntimeError('server6395'),
                      BeaconRejected('dispatch',11,6395),BeaconRejected('dispatch',10,6012),
                      BeaconRejected('claim',10,6395)):
            with self.subTest(error=str(error)):
                self.setUp();self.c.beacon_action.side_effect=error
                self.s.switch(True);self.s.tick(self.c)
                self.assertFalse(self.s.enabled);self.assertTrue(self.s.uncertain)
                self.assertFalse(any(call.args[0]=='beacon_rejected' for call in self.c.beacon_call.call_args_list))

    def test_final_native_full_without_send_uses_same_wait_but_releases_no_reservation(self):
        """A slot taken after planning is an explicit no-send result, not an unknown action or a server6395."""
        self.snapshot.update(queue_used=1,armies=[dict(army_id=88,hero_id=304,state=9,target_id=99,end_ms=150000)])
        self.c.beacon_action.side_effect=BeaconCapacityUnavailable('not sent')
        self.s.switch(True);self.s.tick(self.c)
        self.assertTrue(self.s.enabled);self.assertFalse(self.s.uncertain)
        self.assertIsNotNone(self.s.capacity_wait)
        self.assertFalse(any(call.args[0]=='beacon_rejected' for call in self.c.beacon_call.call_args_list))


if __name__=='__main__':unittest.main()
