"""Verify independent sightings and bounded exact-generation region reads without any game connection."""
import unittest
from unittest.mock import Mock,patch

from connection import Connection
from monster_discovery import MonsterDiscovery
from region_conflict import RegionConflict,RegionRestoreConflict


class DiscoveryTests(unittest.TestCase):
    """Cache replacement cannot erase sightings, while respawns cannot accumulate duplicate coordinates."""

    def test_dedup_and_respawn_replace_only_the_same_coordinate(self):
        """Keep other areas and refresh one ID's attributes/time across overlapping regional replies."""
        d=MonsterDiscovery()
        a=dict(target_id=1,x=92,y=19,logic_x=92,logic_y=231,visible=True,idle=True)
        b=dict(target_id=2,x=93,y=19,logic_x=93,logic_y=231,visible=True,idle=True)
        d.merge([a,b]);d.merge([{**a,'visible':False}]);d.merge([])
        self.assertEqual(len(d.records),2)
        self.assertFalse(d.records[1]['visible'])
        d.merge([{**a,'target_id':3}])
        self.assertEqual(set(d.records),{2,3})
        self.assertIn('seen_at',d.records[3])

    def test_frontier_and_confirmed_absence_inside_covered_core(self):
        """A nearby unfinished area precedes farther sightings; missing covered records are retired."""
        d=MonsterDiscovery()
        region=dict(x=20,y=15,min_distance=0,distance=0,left=0,right=39,bottom=0,top=29)
        d.plan([dict(x=60,y=15,min_distance=30,distance=40),region])
        d.merge([dict(target_id=1,x=10,y=240,logic_x=10,logic_y=10)])
        self.assertIs(d.next_region(5),region)
        d.accept(region,[])
        self.assertFalse(d.records)
        self.assertIsNone(d.next_region(5))
        self.assertIsNone(d.next_region(waiting_distance=5))
        self.assertEqual(d.next_region()['x'],60)


class RegionConnectionTests(unittest.TestCase):
    """A temporary area stays scoped through target use and is restored even when validation rejects it."""

    def connection(self):
        """Model delayed response generations and the native single-slot cache explicitly."""
        c=Connection();state=dict(seq=0,last_x=-1,last_y=-1,view_x=88,view_y=162)
        sends=[]
        def call(op,args=()):
            """Only an actual region query advances the response counter, including same-center reads."""
            if op=='hunt_region_state':return dict(state)
            if op=='hunt_region_query':
                x,y=args;sends.append((x,y));state.update(seq=state['seq']+1,last_x=x,last_y=y,view_x=x,view_y=y)
                return 'sent'
            if op=='hunt_region_read':return [dict(target_id=1,x=92,y=19,logic_x=92,logic_y=231)]
            if op=='hunt_candidates':return []
            raise AssertionError(op)
        c.hunt_call=Mock(side_effect=call)
        return c,state,sends

    def test_query_restores_origin_and_requires_a_new_same_center_generation(self):
        """A fresh exact response is returned as records before the game's cache is restored."""
        c,state,sends=self.connection()
        rows=c.query_hunt_region(dict(x=92,y=231),90)
        self.assertEqual(rows[0]['target_id'],1)
        self.assertEqual(sends,[(92,231),(88,162)])
        self.assertEqual((state['view_x'],state['view_y']),(88,162))
        c.query_hunt_region(dict(x=88,y=162),90)
        self.assertEqual(sends[-1],(88,162));self.assertEqual(len(sends),3)

    def test_uncached_target_stays_loaded_until_the_final_guard_then_restores(self):
        """Neither a failed eligibility check nor an uncertain dispatch leaks the remote cache permanently."""
        c,state,sends=self.connection()
        with self.assertRaisesRegex(RuntimeError,'eligibility'):
            with c.hunt_target_region(dict(target_id=1,config_id=20204,x=92,y=19,logic_x=92,logic_y=231),90):
                self.assertEqual((state['view_x'],state['view_y']),(92,231))
                raise RuntimeError('eligibility rejected')
        self.assertEqual(sends,[(92,231),(88,162)])

    def test_same_center_old_cache_and_foreign_responses_are_not_accepted(self):
        """A timeout or another region response never becomes an empty successful search result."""
        c=Connection();c.hunt_call=Mock(return_value=dict(seq=3,last_x=92,last_y=231,view_x=92,view_y=231))
        with self.assertRaises(TimeoutError):c._load_hunt_region(92,231,timeout=0)
        foreign=dict(seq=4,last_x=100,last_y=231,view_x=100,view_y=231)
        c.hunt_call=Mock(side_effect=lambda op,args=(),**kw: 'sent' if op=='hunt_region_query' else foreign)
        clock=iter([0,0,.1,.2,.3,.4])
        # The old generation cannot satisfy a same-center read, even after another region arrives.
        c.hunt_call.side_effect=[dict(seq=3),'sent',foreign,foreign,foreign]
        with patch('connection.time.monotonic',side_effect=lambda:next(clock)),patch('connection.time.sleep'):
            with self.assertRaises(RegionConflict):c._load_hunt_region(92,231,timeout=.3)

    def test_foreign_reply_before_expected_reply_is_waited_without_resend(self):
        """Replay two interleaved map replies; only a new matching center can satisfy the current read."""
        c=Connection()
        foreign=dict(seq=4,last_x=184,last_y=126,view_x=184,view_y=126)
        expected=dict(seq=5,last_x=216,last_y=103,view_x=216,view_y=103)
        c.hunt_call=Mock(side_effect=[dict(seq=3),'sent',foreign,expected])
        with patch('connection.time.sleep'):
            self.assertEqual(c._load_hunt_region(216,103),expected)
        self.assertEqual(sum(call.args[0]=='hunt_region_query' for call in c.hunt_call.call_args_list),1)

    def test_restore_conflict_preserves_primary_uncertain_error(self):
        """A cleanup collision must never turn an unknown departure into a retryable read-only failure."""
        c,state,sends=self.connection()
        original=c._load_hunt_region
        def load(x,y,**kwargs):
            if (x,y)==(88,162):raise RegionConflict('restore collision')
            return original(x,y,**kwargs)
        c._load_hunt_region=load
        with self.assertRaisesRegex(TimeoutError,'uncertain departure'):
            with c._hunt_region_scope(92,231):raise TimeoutError('uncertain departure')

    def test_native_camera_response_already_restored_view_is_not_overwritten(self):
        """After a camera move loads another area, cleanup must not issue a competing restoration request."""
        c,state,sends=self.connection()
        state.update(camera_x=86,camera_y=156)
        with c._hunt_region_scope(92,231):
            state.update(seq=2,last_x=184,last_y=126,view_x=184,view_y=126,camera_x=184,camera_y=125)
        self.assertEqual(sends,[(92,231)])

    def test_conflicted_region_read_retries_once_and_never_marks_foreign_data_empty(self):
        """A generation conflict redoes discovery at most once; both attempts retain exact-center guards."""
        c,state,sends=self.connection()
        original=c.hunt_call.side_effect
        failures=[0]
        def call(op,args=(),**kwargs):
            if op=='hunt_region_read':
                failures[0]+=1
                if failures[0]==1:raise RegionConflict('cache changed between state and read')
            return original(op,args)
        c.hunt_call.side_effect=call
        self.assertEqual(len(c.query_hunt_region(dict(x=92,y=231),90)),1)
        self.assertEqual(sends,[(92,231),(88,162),(92,231),(88,162)])

    def test_post_read_restore_failure_is_typed_without_replaying_read(self):
        """A successful body followed by a cleanup conflict has a distinct phase and no immediate replay."""
        c,state,sends=self.connection()
        original=c._load_hunt_region
        def load(x,y,**kwargs):
            if (x,y)==(88,162):raise RegionConflict('restore replaced')
            return original(x,y,**kwargs)
        c._load_hunt_region=load
        with self.assertRaises(RegionRestoreConflict):c.query_hunt_region(dict(x=92,y=231),90)
        self.assertEqual(sends,[(92,231)])

    def test_only_read_guard_can_be_classified_as_retryable_conflict(self):
        """An identical error string at a spending boundary is not permission to replay that command."""
        c=Connection();c.script=Mock()
        c.script.exports_sync.query.side_effect=RuntimeError('HUNT_REGION_CONFLICT: Regional response changed')
        with self.assertRaises(RegionConflict):c.hunt_call('hunt_region_read',(90,1,92,231))
        with self.assertRaises(RuntimeError) as raised:c.hunt_call('hunt_dispatch',(1,))
        self.assertNotIsInstance(raised.exception,RegionConflict)
        self.assertEqual(c.script.exports_sync.query.call_count,2)

    def test_scan_queries_share_the_revocable_gate_but_cleanup_is_read_only(self):
        """Stop/off-on cancels queued new-area work; the original-cache restoration may still complete."""
        c=Connection();c.script=Mock();c.script.exports_sync.query.return_value='sent'
        c.hunt_call('hunt_region_query',(92,231),generation=7)
        self.assertEqual(c.script.exports_sync.query.call_args.args[1:],('hunt',1,7))
        c.hunt_call('hunt_region_query',(88,162))
        self.assertEqual(c.script.exports_sync.query.call_args.args[1:],(False,1,None))

    def test_user_camera_move_during_target_check_restores_the_new_view(self):
        """A background regional read must not put an old area back after the user moves the camera."""
        c,state,sends=self.connection()
        state.update(camera_x=86,camera_y=156)
        with c.hunt_target_region(dict(target_id=1,config_id=20204,x=92,y=19,logic_x=92,logic_y=231),90):
            state.update(camera_x=120,camera_y=100)
        self.assertEqual(sends,[(92,231),(120,100)])


if __name__=='__main__':unittest.main()
