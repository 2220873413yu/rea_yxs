"""Scheduled starts use one-shot local deadlines and the latest UI scope, never retry uncertain spending."""
import importlib.util
from importlib.machinery import SourceFileLoader
import threading
import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from monster import HuntOptions
from monster_service import MonsterService
from test_monster_refresh import TIMES, stamp


class ScheduledHuntTests(unittest.TestCase):
    """Exercise closed/open/uncertain sessions without any server or real application window."""

    def setUp(self):
        """Set a server clock just before03:00 while the hunt switch is initially closed."""
        self.owner=Mock();self.owner.guard=threading.RLock();self.owner.closing=threading.Event()
        self.c=Mock();self.owner.connection=self.c
        self.service=MonsterService(self.owner)
        self.server_now=stamp(2,59,50)
        self.c.hunt_call.side_effect=lambda op: {'server_now_ms':self.server_now,'refresh_times':TIMES}

    def tick(self, now):
        """Run the real service while stopped: only a due local clock read is allowed."""
        with patch('monster_service.time.monotonic',return_value=now):self.service.tick(self.c)

    def starts(self):
        """Return requests delivered to the UI, before that UI validates and authorizes its visible scope."""
        return [c.kwargs for c in self.owner.publish.call_args_list if 'hunt_auto_start_epoch' in c.kwargs]

    def test_manual_off_reopens_once_at_slot_using_current_scope_and_logs_the_gate_change(self):
        """Manual cancellation pauses until the next slot; it does not remove the separate scheduled timer."""
        self.tick(100)
        self.service.switch(False)
        self.tick(109);self.c.hunt_call.assert_called_once_with('hunt_refresh_clock')
        self.server_now=stamp(3);self.tick(110)
        self.assertFalse(self.service.enabled)
        request=self.starts()[0]
        self.assertTrue(self.service.start_on_refresh(request['hunt_auto_start_epoch'],HuntOptions(90)))
        self.assertTrue(self.service.enabled)
        self.assertEqual(self.service.options.radius,90)
        self.c.set_hunt_enabled.assert_called_with(True)
        self.assertTrue(any(c.kwargs.get('action')=='hunt_auto_start' and c.kwargs['hunt_enabled']
                            for c in self.owner.publish.call_args_list))
        # A second stop just after the scheduled start waits until06:00 rather than looping immediately.
        self.service.switch(False);self.tick(111);self.tick(112)
        self.assertEqual(len(self.starts()),1)
        self.assertEqual(self.c.hunt_call.call_count,2)

    def test_query_timeout_stop_preserves_next_slot_but_existing_enabled_run_is_not_restarted(self):
        """Stopping does not reset the auto clock; an enabled run retains its generation at the boundary."""
        self.tick(100)
        self.service.switch(True,HuntOptions(70))
        old_epoch=self.service.epoch
        self.server_now=stamp(3)
        with patch('monster_service.time.monotonic',return_value=110):
            self.service.scheduled_start_tick(self.c,110)
        self.assertEqual(self.service.epoch,old_epoch)
        self.assertFalse(self.starts())
        self.service.switch(False)
        self.server_now=stamp(6);self.tick(10910)
        self.assertEqual(len(self.starts()),1)

    def test_uncertain_departure_or_skip_never_requests_or_accepts_auto_enable(self):
        """A local refresh time cannot authorize another departure or replay a skipped battle."""
        for skip in (False,True):
            with self.subTest(skip=skip):
                self.setUp()
                if skip:self.service.active[1]={'skip_attempted':True,'skipped':False}
                else:self.service.uncertain=True
                self.tick(100);self.server_now=stamp(6);self.tick(20000)
                self.c.hunt_call.assert_not_called()
                self.assertFalse(self.starts())
                self.assertFalse(self.service.start_on_refresh(self.service.epoch,HuntOptions(70)))
                self.assertEqual(sum(c.kwargs.get('action')=='hunt_auto_start_blocked'
                                     for c in self.owner.publish.call_args_list),1)

    def test_stale_request_shutdown_or_disconnected_owner_cannot_open_gate(self):
        """An event queued before a newer user action or disconnect is no longer an authorization."""
        self.assertFalse(self.service.start_on_refresh(self.service.epoch,HuntOptions(70)))
        epoch=self.service.epoch;self.service.switch(False)
        self.assertFalse(self.service.start_on_refresh(epoch,HuntOptions(70)))
        self.owner.connection=None
        self.assertFalse(self.service.start_on_refresh(self.service.epoch,HuntOptions(70)))
        self.owner.connection=self.c;self.owner.closing.set();self.tick(100)
        self.assertFalse(self.service.start_on_refresh(self.service.epoch,HuntOptions(70)))
        self.c.hunt_call.assert_not_called()

    def test_clock_failure_suspends_without_repeating_reads(self):
        """A lost map/session or a failed local clock read suspends this schedule, with no polling retry."""
        self.c.hunt_call.side_effect=RuntimeError('World map changed')
        for now in (100,101,1000,20000):self.tick(now)
        self.c.hunt_call.assert_called_once()
        self.assertTrue(self.service.auto_suspended)
        self.assertFalse(self.starts())


class ScheduledHuntUiTests(unittest.TestCase):
    """The GUI validates its current controls rather than replaying an obsolete worker-side radius."""

    @classmethod
    def setUpClass(cls):
        """Import the pyw entrypoint without instantiating Tk or starting worker threads."""
        path=Path(__file__).with_name('app.pyw')
        loader=SourceFileLoader('scheduled_hunt_app_tests',str(path))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        module=importlib.util.module_from_spec(spec);loader.exec_module(module)
        cls.App=module.App

    def make_app(self):
        """Use plain mocks for controls so no real checkboxes or game switches can change."""
        app=self.App.__new__(self.App)
        app.ready=True;app.closing=False;app.trial_exclusive=False;app.worker=Mock();app.hunt_enabled=Mock()
        app.sessions=Mock(epoch=1,worker=app.worker)
        app.battle_chat=Mock(generation=0)
        app.hall_profile=Mock(generation=0)
        app.hunt_enabled.get.return_value=False
        app.monster_panel=Mock();app.monster_panel.options.return_value=HuntOptions(90)
        app.worker.hunt.start_on_refresh.return_value=True
        app.update_controls=Mock()
        return app

    def test_latest_visible_radius_is_validated_before_checking_the_switch(self):
        """The worker must accept the current90-cell scope before the GUI shows hunting as enabled."""
        app=self.make_app();app.start_hunt_on_refresh(7)
        app.worker.hunt.start_on_refresh.assert_called_once_with(7,HuntOptions(90))
        app.hunt_enabled.set.assert_called_once_with(True)

    def test_invalid_radius_not_ready_or_rejected_epoch_never_checks_the_switch(self):
        """Invalid controls and stale worker requests remain stopped instead of displaying a phantom enabled state."""
        app=self.make_app();app.monster_panel.options.side_effect=ValueError('invalid radius')
        app.start_hunt_on_refresh(7)
        app.worker.hunt.start_on_refresh.assert_not_called()
        app.hunt_enabled.set.assert_called_once_with(False)
        app.worker.switch_hunt.assert_called_once_with(False)
        app=self.make_app();app.ready=False;app.start_hunt_on_refresh(7)
        app.worker.hunt.start_on_refresh.assert_not_called();app.hunt_enabled.set.assert_not_called()
        app=self.make_app();app.worker.hunt.start_on_refresh.return_value=False;app.start_hunt_on_refresh(7)
        app.hunt_enabled.set.assert_not_called()

    def test_event_loop_accepts_scheduled_request_and_renders_confirmed_enabled_state(self):
        """The authorized timer request passes current options through the UI and keeps the checkbox in sync."""
        app=self.make_app();app.events=queue.Queue();app.root=Mock()
        app.events.put({'hunt_auto_start_epoch':7})
        app.events.put({'hunt_enabled':True,'hunt_status':'confirmed enabled'})
        app.poll()
        app.worker.hunt.start_on_refresh.assert_called_once_with(7,HuntOptions(90))
        self.assertTrue(all(c.args==(True,) for c in app.hunt_enabled.set.call_args_list))
        self.assertEqual(app.hunt_enabled.set.call_count,2)
        app.monster_panel.status.set.assert_called_with('confirmed enabled')


if __name__=='__main__':unittest.main()
