"""Trial transitions using production policy with fake game responses; no live challenges are performed."""
import copy
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from trial_service import TrialService
from trial_receipts import TrialRejected, request_matches, wait_trial_receipt


def snapshot(**updates):
    """Create a role-scoped local trial view with no current battle by default."""
    data=dict(profile_seq=1,profile_ret=0,available_seq=0,available_ret=0,result_seq=0,result=None,
              max_floor=19,today_floor=0,remaining=3,next_quest=10010010,total=80,heroes=[],
              world_ready=True,in_game=False,battle_ready=False,can_skip=False,
              server_now_ms=100000,skip_at_ms=110000,round=0,army_id=0,room=0,table_id=0)
    data.update(updates)
    return data


def heroes():
    """Return three confirmed identifiers, deliberately distinct from their level50."""
    return [dict(id=i,name=str(i),state=0,power=p)for i,p in ((219,424972),(213,423244),(208,417672))]


class TrialServiceTests(unittest.TestCase):
    """Assert that only matched wins advance and every loss/cancellation leaves manual control intact."""

    def setUp(self):
        self.events=[]
        self.c=Mock(trial_generation=1)
        self.owner=SimpleNamespace(guard=threading.RLock(),closing=threading.Event(),connection=self.c,
                                   publish=lambda **e:self.events.append(e))
        self.s=TrialService(self.owner)
        self.view=snapshot()
        self.c.trial_call.side_effect=lambda op,**kw:copy.deepcopy(self.view)if op=='status'else {'started':True}
        self.c.trial_action.side_effect=lambda op,g,cancel:dict(code=1,target=self.view['next_quest'],heroes=[219,213,208],ret=0)

    def tick(self, **updates):
        """Deliver one already-received local response without sleeping or querying a real server."""
        self.view.update(updates);self.s.local_due=0;return self.s.tick(self.c)

    def start(self):
        """Explicitly enable the master and consume its initial profile read."""
        self.s.switch(True);self.tick()

    def actions(self):
        """Expose only outgoing policy operations for comparisons."""
        return [c.args[0]for c in self.c.trial_action.call_args_list]

    def battle(self):
        """Reach an accepted first-layer challenge through the real selection policy."""
        self.start();self.tick(profile_seq=2);self.tick(available_seq=1)
        self.tick(profile_seq=3,heroes=heroes());self.tick()
        self.tick(battle_ready=True,world_ready=False,in_game=True)

    def test_default_off_does_not_query_or_select(self):
        self.assertFalse(self.tick())
        self.c.trial_call.assert_not_called();self.assertEqual(self.actions(),[])

    def test_win_advances_once_and_does_not_treat_skip_ack_as_win(self):
        self.battle();self.tick(can_skip=True)
        self.assertEqual(self.s.phase,'result')
        self.assertEqual(self.actions(),['query_profile','query_available','select','challenge','skip'])
        for _ in range(6):self.tick(result=None)
        self.assertNotIn('return_after_win',self.actions())
        self.tick(result=dict(ret=0,win=True),in_game=False)
        self.tick();self.assertEqual(self.actions()[-1],'return_after_win')
        self.tick(world_ready=True,profile_seq=4,next_quest=10010011,today_floor=1)
        self.tick()
        self.assertEqual(self.actions().count('challenge'),2)
        self.assertEqual(self.actions().count('select'),1)

    def test_loss_closes_immediately_without_return_retry_or_revive(self):
        self.battle();self.tick(can_skip=True)
        before=self.actions()
        self.tick(result=dict(ret=0,win=False),in_game=False)
        self.assertFalse(self.s.enabled);self.assertFalse(self.s.uncertain)
        self.assertTrue(any('战败' in e.get('trial_status','')for e in self.events))
        for _ in range(5):self.tick()
        self.assertEqual(self.actions(),before)
        self.tick(world_ready=True)
        self.assertEqual(sum(bool(e.get('trial_reconnect'))for e in self.events),1)
        self.tick();self.assertEqual(self.actions(),before)

    def test_waiting_uses_local_status_without_periodic_server_queries(self):
        self.battle();before=self.actions()
        for _ in range(60):self.tick(can_skip=False,server_now_ms=101000)
        self.assertEqual(self.actions(),before)

    def test_user_off_does_not_skip_or_return_even_when_conditions_become_ready(self):
        self.battle();self.s.switch(False);before=self.actions()
        self.tick(can_skip=True,result=dict(ret=0,win=True),in_game=False)
        self.assertEqual(self.actions(),before)

    def test_switch_off_cancels_queued_begin_without_breaking_read_only_handoff(self):
        self.s.switch(True)

        def cancel_begin(operation, **kwargs):
            """Simulate a UI stop between the local status read and queued native begin."""
            if operation == 'status':
                return copy.deepcopy(self.view)
            self.s.switch(False)
            raise RuntimeError('Trial switch changed')

        self.c.trial_call.side_effect = cancel_begin
        self.tick()
        self.assertFalse(self.s.enabled)
        self.assertFalse(self.s.reconnect_requested)
        self.assertFalse(any(e.get('ready') is False for e in self.events))

    def test_uncertain_mutation_is_never_automatically_retried(self):
        self.start();self.tick(profile_seq=2)
        self.c.trial_action.side_effect=TimeoutError('No definitive acknowledgement')
        self.tick(available_seq=1)
        self.assertFalse(self.s.enabled);self.assertTrue(self.s.uncertain)
        with self.assertRaises(RuntimeError):self.s.switch(True)
        before=self.actions();self.tick();self.assertEqual(self.actions(),before)

    def test_existing_trial_roster_is_not_reset_or_selected_again(self):
        self.start();self.tick(profile_seq=2,heroes=heroes());self.tick()
        self.assertEqual(self.actions(),['query_profile','challenge'])

    def test_fresh_profile_after_win_must_not_restart_same_quest(self):
        self.battle();self.tick(result=dict(ret=0,win=True),in_game=False)
        self.tick();self.tick(world_ready=True)
        self.assertEqual(self.actions()[-1],'query_profile')
        self.tick(profile_seq=4,next_quest=10010010)
        self.assertFalse(self.s.enabled);self.assertEqual(self.actions().count('challenge'),1)

    def test_server_refusal_stops_without_replay(self):
        self.start();self.tick(profile_seq=2)
        self.c.trial_action.side_effect=TrialRejected('select',6012)
        self.tick(available_seq=1)
        self.assertFalse(self.s.enabled);self.assertFalse(self.s.uncertain)

    def test_worker_trial_start_disarms_every_world_master_and_refresh_schedule(self):
        from controller import Worker
        w=Worker(Mock());w.connection=Mock()
        w.enabled=w.hero_enabled=w.collection.enabled=w.hunt.enabled=w.league.enabled=w.beacon.enabled=True
        w.switch_trial(True)
        self.assertTrue(w.trial.enabled)
        self.assertFalse(any((w.enabled,w.hero_enabled,w.collection.enabled,w.hunt.enabled,w.league.enabled,w.beacon.enabled,w.allow_scheduled_hunt)))


class TrialWireTests(unittest.TestCase):
    """Keep a request acknowledgement separate from the battle's eventual result."""

    def test_matches_hero_roster_quest_and_army(self):
        sent=dict(heroes=[219,213,208],target=10010010,hero_id=219,army_id=77)
        row=lambda x:dict(value=[dict(tag=0,value=x)])
        self.assertTrue(request_matches('select',{0:[row(208),row(219),row(213)]},sent))
        self.assertFalse(request_matches('select',{0:[row(208),row(219),row(50)]},sent))
        self.assertTrue(request_matches('challenge',{0:10010010,2:16,3:[dict(tag=0,value=219)],4:0},sent))
        self.assertFalse(request_matches('challenge',{0:10010010,2:3,3:[dict(tag=0,value=219)]},sent))
        self.assertFalse(request_matches('skip',{0:78},sent))

    def test_cancel_never_reads_or_replays_wire(self):
        log=Mock()
        with self.assertRaises(InterruptedError):wait_trial_receipt(log,'skip',dict(code=11015,army_id=77),lambda:True)
        log.drain.assert_not_called()


if __name__=='__main__':unittest.main()
