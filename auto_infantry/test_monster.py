"""Verify near-first hunting policy and its state machine without accessing a real account."""
import math
import threading
import unittest
from unittest.mock import Mock, patch

from monster import HuntOptions, default_formation, ordered_targets, ring_for
from monster_service import MonsterService


def target(**changes):
    """Build a visible, idle, fresh ordinary monster for deterministic planning cases."""
    return dict(target_id=1, config_id=20101, x=99, y=184, distance=5, level=1,
                visible=True, idle=True, fresh=True, enemy_power=100, detail_seq=1, available_seq=1, **changes)


def plan(n=2, **changes):
    """Build a positive native default profile, with the actual client's start eligibility attached."""
    return dict(hero_id=303, name='西施', soldier_id=411, followers=n, power=150,
                enemy_power=100, recommendation='我方超强，胜券在握', eligible=True, travel_seconds=6,
                native_default=True,start_enabled=True,**changes)


class MonsterPolicyTests(unittest.TestCase):
    """Require valid native defaults and spend the least qualifying combat strength before travel tie-breaks."""

    def test_native_defaults_choose_ready_hero_and_never_zero_or_manual_profiles(self):
        """Zero-soldier or manually reduced profiles cannot bypass native defaults even if their power is high."""
        a=plan(); zero={**plan(0),'hero_id':305,'travel_seconds':1}
        manual={**plan(1),'hero_id':306,'travel_seconds':1,'native_default':False}
        faster={**plan(),'hero_id':307,'travel_seconds':4}
        self.assertEqual(default_formation({'target':target(),'formations':[a,zero,manual,faster]}),faster)

    def test_lowest_default_total_power_wins_and_equal_power_prefers_faster_travel(self):
        """Preserve higher-power heroes and do not alter default troop counts to manufacture a lower power."""
        low={**plan(4),'power':151,'travel_seconds':50}
        fast_high={**plan(2),'hero_id':304,'power':260,'travel_seconds':1}
        too_weak={**plan(),'hero_id':305,'power':149,'travel_seconds':1,'recommendation':'敌弱我强，优势明显'}
        metrics={'target':target(),'formations':[fast_high,too_weak,low]}
        self.assertIs(default_formation(metrics),low)
        self.assertEqual(low['followers'],4)
        equal_faster={**low,'hero_id':306,'travel_seconds':30}
        metrics['formations'].append(equal_faster)
        self.assertIs(default_formation(metrics),equal_faster)
        equal_stable={**equal_faster,'hero_id':302}
        metrics['formations'].append(equal_stable)
        self.assertIs(default_formation(metrics),equal_stable)

    def test_bad_enemy_weak_side_unknown_or_unavailable_never_qualifies(self):
        """A label cannot authorize hidden targets, zero enemy power, low actual power or stale/busy heroes."""
        for patch_t, patch_p in (({'enemy_power':0},{}), ({'visible':False},{}), ({'idle':False},{}),
                                  ({'fresh':False},{}), ({},{'eligible':False}), ({},{'power':50}),
                                  ({},{'recommendation':'敌弱我强，优势明显'}), ({},{'enemy_power':99}),
                                  ({},{'start_enabled':False}), ({},{'native_default':False})):
            with self.subTest(patch_t=patch_t,patch_p=patch_p):
                self.assertIsNone(default_formation({'target':{**target(),**patch_t},'formations':[{**plan(),**patch_p}]}))

    def test_scope_near_first_completed_and_five_cell_rings(self):
        """Rings describe progressive expansion while distance always remains anchored to home."""
        rows=[{**target(),'distance':12,'target_id':3},target(),{**target(),'visible':False,'target_id':2},
              {**target(),'idle':False,'target_id':4},{**target(),'distance':21,'target_id':5}]
        self.assertEqual([r['target_id'] for r in ordered_targets(rows,20,set())],[1,3])
        self.assertEqual([r['target_id'] for r in ordered_targets(rows,20,{1})],[3])
        self.assertEqual([ring_for(n,18) for n in (1,5,6,12,18)],[5,5,10,15,18])
        self.assertEqual(HuntOptions(200).radius,200)
        self.assertEqual(HuntOptions(101).radius,101)
        self.assertEqual(HuntOptions().radius,20)
        for value in (True,0,201,1000,1.5,'20'):
            with self.assertRaises(ValueError):HuntOptions(value)


class MonsterServiceTests(unittest.TestCase):
    """Exercise departure/arrival/return, waiting and cancellation using only fixed transport seams."""

    def setUp(self):
        """Build a serial-owner fake and stable native snapshot, without opening a spending gate in a game."""
        self.owner=Mock();self.owner.guard=threading.RLock();self.owner.closing=threading.Event()
        self.c=Mock();self.c.hunt_generation=9;self.owner.connection=self.c
        self.service=MonsterService(self.owner)
        self.schedule=dict(server_now_ms=1000000,stages=[],monsters=[],queue_free=True,can_skip=True,
                           queue_known=True,queue_used=0,queue_limit=1)
        self.c.refresh_heroes.return_value={'heroes':[]}
        self.c.hunt_call.side_effect=self.call
        self.metrics={'target':target(),'formations':[plan()],'potential':False,'cooldown_ms':0}
        self.c.query_monster.return_value=self.metrics
        self.c.dispatch_hunt.return_value=({'ret':0,'hero_id':303,'target_id':1,'army_id':10},{'heroes':[]})
        self.c.skip_hunt.return_value={'ret':0,'won':True,'target_id':1,'army_id':10}
        self.service.switch(True,HuntOptions())

    def call(self, op, arguments=()):
        """Return local watch and fresh server schedules; all mutation seams are separately mocked."""
        if op=='hunt_watch':return {'seq':0,'home_x':100,'home_y':60,'candidates':[target()]}
        if op=='hunt_schedule':return self.schedule
        if op=='hunt_candidates':return [target()]
        if op=='hunt_scan_plan':return {'regions':[]}
        if op=='hunt_refresh_clock':return {'server_now_ms':1000000,'refresh_times':''}
        return 'ok'

    def tick(self, at):
        """Advance the production state machine with a deterministic monotonic clock."""
        with patch('monster_service.time.monotonic',return_value=at):self.service.tick(self.c)

    def test_one_departure_arrival_skip_once_and_return(self):
        """An in-flight army prevents another send; successful skip waits for confirmed return."""
        self.tick(100);self.c.dispatch_hunt.assert_called_once()
        army=dict(army_id=10,hero_id=303,target_id=1,aim=3,state=2,end_ms=1006000)
        self.schedule['stages']=[army];self.schedule['monsters']=[army]
        self.schedule['queue_used']=1;self.schedule['queue_free']=False
        self.tick(101);self.c.skip_hunt.assert_not_called()
        self.assertEqual(self.service.due,108)
        self.tick(102);self.c.dispatch_hunt.assert_called_once()
        army['state']=3;self.service.request_check();self.tick(103)
        self.c.skip_hunt.assert_called_once();self.assertTrue(self.service.active[10]['skipped'])
        self.tick(104);self.c.skip_hunt.assert_called_once()
        self.schedule['stages']=[];self.schedule['monsters']=[];self.service.request_check();self.tick(105)
        self.assertFalse(self.service.active);self.assertIn(1,self.service.completed)
        self.c.dispatch_hunt.assert_called_once()

    def test_no_targets_enters_push_wait_without_fixed_server_polling(self):
        """Idle loops sample local cache but never repeat authoritative server reads without a change."""
        self.c.hunt_call.side_effect=lambda op,args=(): ([] if op=='hunt_candidates' else
            {**self.call(op,args),'candidates':[]} if op=='hunt_watch' else self.call(op,args))
        self.tick(100)
        self.assertTrue(math.isinf(self.service.due))
        for at in range(101,130):self.tick(at)
        self.c.refresh_heroes.assert_called_once();self.c.dispatch_hunt.assert_not_called()

    def test_busy_potential_waits_without_expanding_and_cooldown_schedules_once(self):
        """A nearby target needing a recovering hero does not cause attacks farther from home."""
        self.c.query_monster.return_value={**self.metrics,'formations':[],'potential':True,'cooldown_ms':1060000}
        self.tick(100)
        self.assertEqual(self.service.due,161)
        for at in (101,120,160):self.tick(at)
        self.c.query_monster.assert_called_once();self.c.dispatch_hunt.assert_not_called()

    def test_full_queue_unknown_capacity_or_missing_entitlement_never_dispatches(self):
        """Manual occupancy counts toward capacity; unknown capacity or missing entitlement prevents spending."""
        for change in ({'queue_used':1},{'queue_free':False},{'queue_known':False},{'can_skip':False}):
            self.setUp();self.schedule.update(change);self.tick(100)
            self.c.dispatch_hunt.assert_not_called();self.c.query_monster.assert_not_called()
            self.c.query_hunt_region.assert_not_called()

    def test_uncertain_send_and_skip_cannot_be_repeated(self):
        """An ambiguous departure disables this run and refuses rearming; an ambiguous skip is marked first."""
        self.c.dispatch_hunt.side_effect=TimeoutError('uncertain')
        self.tick(100);self.assertFalse(self.service.enabled)
        with self.assertRaises(RuntimeError):self.service.switch(True,HuntOptions())
        self.c.dispatch_hunt.assert_called_once()
        self.setUp();self.tick(100)
        army=dict(army_id=10,hero_id=303,target_id=1,aim=3,state=3,end_ms=0)
        self.schedule.update(stages=[army],monsters=[army])
        self.c.skip_hunt.side_effect=TimeoutError('uncertain skip')
        self.tick(101);self.assertFalse(self.service.enabled)
        self.service.switch(True,HuntOptions());self.tick(103)
        self.c.skip_hunt.assert_called_once()

    def test_stop_during_target_read_prevents_departure(self):
        """Closing the switch while a query completes cannot promote its old result into a new action."""
        def query(_):
            self.service.switch(False)
            return self.metrics
        self.c.query_monster.side_effect=query
        self.tick(100);self.c.dispatch_hunt.assert_not_called()

    def test_hero_snapshot_generations_alone_do_not_cause_a_poll_loop(self):
        """Only eligibility changes from cached hero responses wake a waiting search."""
        r={'heroes':[{'hero_id':303,'busy':False,'hero_state':0,'finish_ms':0,'remaining_ms':0,'power':100}]}
        self.service.observe(r);self.service.wakeup.pending=False
        self.service.observe({**r,'hero_seq':999})
        self.assertFalse(self.service.wakeup.pending)
        self.service.observe({'heroes':[{**r['heroes'][0],'busy':True}]})
        self.assertTrue(self.service.wakeup.pending)

    def enable_multi(self, limit=3):
        """Provide independent targets/heroes and receipts, as if the server confirms each departure."""
        self.schedule.update(queue_limit=limit)
        self.targets=[{**target(),'target_id':i,'x':98+i,'distance':4+i} for i in range(1,6)]
        self.current_target=None
        self.c.hunt_call.side_effect=lambda op,args=(): self.targets if op=='hunt_candidates' else self.call(op,args)

        def query(target_id):
            """Expose one target-specific available formation using a different hero per monster."""
            t=next(r for r in self.targets if r['target_id']==target_id)
            self.current_target=t
            return {'target':t,'formations':[{**plan(),'hero_id':300+target_id}],
                    'strength_known':True,'can_win_full':True,'potential':False,'cooldown_ms':0}

        def dispatch(t,p,radius,generation):
            """Update the fake authoritative army list before returning one attributed success."""
            row=dict(army_id=100+t['target_id'],hero_id=p['hero_id'],target_id=t['target_id'],aim=3,state=2,end_ms=2000000)
            self.schedule['stages'].append(row);self.schedule['monsters'].append(row)
            self.schedule['queue_used']+=1
            self.schedule['queue_free']=self.schedule['queue_used']<self.schedule['queue_limit']
            return {'ret':0,'hero_id':p['hero_id'],'target_id':t['target_id'],'army_id':row['army_id']},{'heroes':[]}

        self.c.query_monster.side_effect=query
        self.c.dispatch_hunt.side_effect=dispatch

    def test_dynamic_capacity_fills_three_then_four_and_respects_a_reduction(self):
        """Every increase/decrease is server-driven; a reduced limit does not cancel accepted armies."""
        self.enable_multi()
        for at in (100,101,102,103):self.tick(at)
        self.assertEqual(self.c.dispatch_hunt.call_count,3)
        self.assertEqual(len(self.service.active),3)
        self.schedule.update(queue_limit=4,queue_free=True);self.service.request_check();self.tick(104)
        self.assertEqual(self.c.dispatch_hunt.call_count,4)
        self.schedule.update(queue_limit=2,queue_free=False);self.service.request_check();self.tick(105)
        self.assertEqual(len(self.service.active),4)
        self.assertTrue(self.service.enabled)
        self.assertEqual(self.c.dispatch_hunt.call_count,4)

    def test_one_return_refills_without_waiting_for_the_other_teams(self):
        """The freed server slot is filled while the other two accepted teams remain in flight."""
        self.enable_multi()
        for at in (100,101,102):self.tick(at)
        self.schedule['stages']=[r for r in self.schedule['stages'] if r['army_id']!=101]
        self.schedule['monsters']=[r for r in self.schedule['monsters'] if r['army_id']!=101]
        self.schedule.update(queue_used=2,queue_free=True);self.service.request_check();self.tick(103)
        self.assertEqual(set(self.service.active),{102,103,104})
        self.assertEqual(self.c.dispatch_hunt.call_count,4)

    def test_arrivals_are_skipped_independently_before_new_departures(self):
        """Two simultaneous arrivals each skip once, ahead of using any newly available fourth slot."""
        self.enable_multi()
        for at in (100,101,102):self.tick(at)
        for row in self.schedule['stages'][:2]:row['state']=3
        self.schedule.update(queue_limit=4,queue_free=True);self.service.request_check()
        self.tick(103);self.tick(104)
        self.assertEqual(self.c.skip_hunt.call_count,2)
        self.assertEqual(self.c.dispatch_hunt.call_count,3)
        self.assertEqual([c.args[0]['army_id'] for c in self.c.skip_hunt.call_args_list],[101,102])
        self.tick(105)
        self.assertEqual(self.c.dispatch_hunt.call_count,4)

    def test_manual_army_uses_one_slot_but_is_never_skipped_or_reselected(self):
        """Manual monsters count toward capacity and their reserved targets are excluded from queries."""
        self.enable_multi()
        manual=dict(army_id=90,hero_id=999,target_id=1,aim=3,state=3,end_ms=0)
        self.schedule.update(stages=[manual],monsters=[manual],queue_used=1)
        for at in (100,101,102):self.tick(at)
        self.assertEqual(self.c.dispatch_hunt.call_count,2)
        self.assertEqual(set(self.service.active),{102,103})
        self.c.skip_hunt.assert_not_called()
        self.assertNotIn(1,[c.args[0] for c in self.c.query_monster.call_args_list])

    def test_weak_coordinate_not_requeried_on_manual_check_push_or_new_monster_id(self):
        """Only a new enable clears full-strength failure memory; ID changes do not bypass coordinate exclusion."""
        self.c.query_monster.return_value={**self.metrics,'formations':[],'strength_known':True,'can_win_full':False}
        self.tick(100)
        self.assertEqual(self.service.ignored,{(99,184)})
        self.tick(101)
        self.service.request_check();self.tick(102)
        self.service.observe({'heroes':[{'hero_id':303,'power':1}]})
        self.service.observe({'heroes':[{'hero_id':303,'power':2}]});self.tick(103)
        original=self.c.hunt_call.side_effect
        self.c.hunt_call.side_effect=lambda op,args=(): [{**target(),'target_id':999}] if op=='hunt_candidates' else original(op,args)
        self.service.request_check();self.tick(104)
        self.c.query_monster.assert_called_once()
        self.service.switch(False);self.service.switch(True,HuntOptions())
        self.assertFalse(self.service.ignored)
        self.c.hunt_call.side_effect=original;self.tick(106)
        self.assertEqual(self.c.query_monster.call_count,2)

    def test_cooldown_stock_unknown_or_busy_strength_never_enters_ignore_set(self):
        """Temporary unavailability and incomplete strength evidence cannot permanently exclude a coordinate."""
        cases=({'potential':True,'can_win_full':True,'strength_known':True},
               {'needs_soldiers':True,'can_win_full':True,'strength_known':True},
               {'can_win_full':False,'strength_known':False})
        for change in cases:
            with self.subTest(change=change):
                self.setUp()
                self.c.query_monster.return_value={**self.metrics,'formations':[],**change}
                self.tick(100)
                self.assertFalse(self.service.ignored)
                self.assertIn((99,184),self.service.waiting)

    def test_reserved_hero_is_filtered_even_if_a_stale_candidate_says_idle(self):
        """An accepted hero cannot be reused while another independent target is considered."""
        self.enable_multi();self.tick(100)
        self.c.query_monster.side_effect=lambda identifier: {'target':next(r for r in self.targets if r['target_id']==identifier),
                  'formations':[{**plan(),'hero_id':301}],'potential':True,'can_win_full':True,'strength_known':True,'cooldown_ms':0}
        self.tick(101)
        self.assertEqual(self.c.dispatch_hunt.call_count,1)
        self.assertFalse(self.service.ignored)

    def test_regions_find_uncached_near_target_before_far_sighting_and_pause_when_full(self):
        """Finite region responses survive cache replacement, and discovery pauses immediately at native capacity."""
        regions=[dict(x=20,y=15,min_distance=0,distance=0),dict(x=60,y=15,min_distance=1,distance=1),
                 dict(x=100,y=15,min_distance=10,distance=20)]
        far={**target(),'target_id':2,'x':110,'distance':15}
        near={**target(),'distance':5}
        def call(op,args=()):
            """The screen cache remains empty even after the independent scan has found monsters."""
            if op=='hunt_scan_plan':return {'regions':regions}
            if op=='hunt_candidates':return []
            if op=='hunt_watch':return {**self.call(op,args),'candidates':[],
                                       'queue_used':self.schedule['queue_used'],'queue_limit':1}
            return self.call(op,args)
        self.c.hunt_call.side_effect=call
        self.c.query_hunt_region.side_effect=[[far],[near],[]]
        self.tick(100);self.tick(101)
        self.c.dispatch_hunt.assert_not_called()
        self.assertEqual(set(self.service.discovery.records),{1,2})
        self.tick(102)
        self.assertEqual(self.c.query_monster.call_args.args,(1,))
        self.c.dispatch_hunt.assert_called_once()
        self.schedule.update(queue_used=1,queue_free=False)
        self.tick(103);self.tick(104)
        self.assertEqual(self.c.query_hunt_region.call_count,2)
        self.assertEqual(self.service.discovery.cursor,2)
        self.schedule.update(queue_used=0,queue_free=True)
        self.tick(105)
        self.assertEqual(self.c.query_hunt_region.call_args.args[0],regions[2])
        self.assertEqual(self.c.query_hunt_region.call_count,3)

    def test_exhausted_empty_regions_wait_without_network_polling_and_manual_check_rescans(self):
        """An empty finite sweep sleeps until a real event or explicit check, rather than restarting itself."""
        regions=[dict(x=20,y=15,min_distance=0,distance=0)]
        def call(op,args=()):
            """Provide one valid empty region and no preloaded monsters."""
            if op=='hunt_scan_plan':return {'regions':regions}
            if op=='hunt_candidates':return []
            if op=='hunt_watch':return {**self.call(op,args),'candidates':[]}
            return self.call(op,args)
        self.c.hunt_call.side_effect=call;self.c.query_hunt_region.return_value=[]
        self.tick(100);self.tick(101)
        for at in range(102,130):self.tick(at)
        self.c.query_hunt_region.assert_called_once()
        self.assertTrue(math.isinf(self.service.due))
        refreshes=self.c.refresh_heroes.call_count
        self.tick(140);self.assertEqual(self.c.refresh_heroes.call_count,refreshes)
        self.service.request_check();self.tick(141)
        self.assertEqual(self.c.query_hunt_region.call_count,2)

    def test_stop_while_region_loads_prevents_acceptance_and_departure(self):
        """A completed read belonging to an old enabled generation cannot seed or dispatch a new run."""
        self.service.discovery.plan([dict(x=20,y=15,min_distance=0,distance=0)])
        def query(region,radius,generation):
            """Simulate the user closing the switch while an already-sent read finishes."""
            self.service.switch(False)
            return [target()]
        self.c.query_hunt_region.side_effect=query
        self.tick(100)
        self.assertEqual(self.service.discovery.cursor,0)
        self.c.dispatch_hunt.assert_not_called()

    def configure_refresh_watch(self, full=False):
        """Expose only changing server clock/capacity metadata while map, troops and push marker stay unchanged."""
        from test_monster_refresh import TIMES,stamp
        self.server_now=stamp(2,59,50)
        self.schedule.update(queue_used=int(full),queue_free=not full)
        def call(op,args=()):
            """Reuse the normal watch with no targets so only the configured clock can trigger a rescan."""
            if op=='hunt_watch':
                return dict(seq=0,home_x=100,home_y=60,candidates=[],server_now_ms=self.server_now,
                    refresh_times=TIMES,queue_known=True,queue_used=self.schedule['queue_used'],queue_limit=1)
            if op=='hunt_candidates':return []
            if op=='hunt_scan_plan':return {'regions':[dict(x=20,y=15,min_distance=0,distance=0)]}
            return self.call(op,args)
        self.c.hunt_call.side_effect=call
        self.c.query_hunt_region.return_value=[]

    def test_refresh_slot_restarts_exhausted_scan_once_without_clearing_weak_exclusions(self):
        """A real configured boundary wakes idle discovery once; ordinary elapsed seconds do not query servers."""
        from test_monster_refresh import stamp
        self.configure_refresh_watch();self.tick(100);self.tick(101)
        self.c.query_hunt_region.assert_called_once()
        self.service.ignored.add((99,184));self.service.completed.add(77)
        self.service.discovery.merge([dict(target_id=88,x=90,y=19,visible=False,idle=False,distance=19)])
        self.server_now=stamp(3);self.tick(110)
        self.assertEqual(self.c.query_hunt_region.call_count,2)
        self.assertEqual(self.service.ignored,{(99,184)})
        self.assertFalse(self.service.completed);self.assertFalse(self.service.discovery.records)
        self.assertFalse(self.service.refresh.pending)
        self.tick(111)
        reads=self.c.refresh_heroes.call_count
        for at in range(112,140):self.tick(at)
        self.assertEqual(self.c.refresh_heroes.call_count,reads)
        self.assertEqual(self.c.query_hunt_region.call_count,2)

    def test_full_queue_defers_refresh_without_queries_until_a_real_free_slot(self):
        """A boundary only leaves a pending flag while full; multiple slots do not repeatedly refresh capacity."""
        from test_monster_refresh import stamp
        self.configure_refresh_watch(full=True);self.tick(100)
        self.server_now=stamp(3);self.tick(110);self.tick(111)
        self.server_now=stamp(6);self.tick(120)
        self.assertTrue(self.service.refresh.pending)
        self.c.query_hunt_region.assert_not_called()
        self.c.refresh_heroes.assert_called_once()
        self.schedule.update(queue_used=0,queue_free=True);self.tick(121)
        self.c.query_hunt_region.assert_called_once()
        self.assertFalse(self.service.refresh.pending)

    def test_switch_off_discards_refresh_hint_and_old_return_cannot_hide_new_cycle_target(self):
        """Stopped automation cannot run a queued scan, and a pre-refresh army release cannot poison new discoveries."""
        from test_monster_refresh import stamp
        self.configure_refresh_watch(full=True);self.tick(100)
        self.server_now=stamp(3);self.tick(110)
        self.service.switch(False);self.tick(120)
        self.assertFalse(self.service.refresh.pending)
        self.c.query_hunt_region.assert_not_called()
        self.service.refresh_round=1
        self.service.active[10]=dict(hero_id=303,target_id=1,refresh_round=0)
        self.service.advance_armies(self.c,self.schedule,self.service.epoch,self.c.hunt_generation)
        self.assertNotIn(1,self.service.completed)

    def test_actual_read_query_timeout_can_resume_on_next_refresh_slot_without_retrying_now(self):
        """The production timeout catch closes hunting, yet a later configured slot can safely start a new check."""
        from test_monster_refresh import TIMES,stamp
        server=[stamp(2,59,50)]
        original=self.c.hunt_call.side_effect
        self.c.hunt_call.side_effect=lambda op,args=(): (
            {'server_now_ms':server[0],'refresh_times':TIMES} if op=='hunt_refresh_clock' else original(op,args))
        self.c.query_monster.side_effect=TimeoutError('野怪详情或可用英雄查询超时，未派出')
        self.tick(100)
        self.assertFalse(self.service.enabled)
        self.assertFalse(self.service.automatic_start_blocked())
        self.c.dispatch_hunt.assert_not_called()
        self.tick(109);self.c.query_monster.assert_called_once()
        server[0]=stamp(3);self.tick(110)
        events=[c.kwargs for c in self.owner.publish.call_args_list if 'hunt_auto_start_epoch' in c.kwargs]
        self.assertEqual(len(events),1)
        self.assertTrue(self.service.start_on_refresh(events[0]['hunt_auto_start_epoch'],HuntOptions(70)))
        self.c.query_monster.side_effect=None
        self.tick(111)
        self.c.dispatch_hunt.assert_called_once()


if __name__=='__main__':unittest.main()
