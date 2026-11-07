"""Exercise the real Tk trial panel with a withdrawn window and no game connection."""
import tkinter as tk
import unittest
from trial_panel import TrialPanel
from test_trial_service import snapshot, heroes


class TrialPanelTests(unittest.TestCase):
    """Verify that viewing progress cannot enable automation and stopping stays available."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.enabled = tk.BooleanVar(self.root, value=False)
        self.calls = []
        self.panel = TrialPanel(self.root, self.enabled, lambda: self.calls.append(True))

    def tearDown(self):
        self.root.destroy()

    def test_default_off_and_snapshot_rendering_does_not_authorize_actions(self):
        self.assertFalse(self.enabled.get())
        self.assertTrue(self.panel.toggle.instate(['disabled']))
        self.panel.apply_snapshot(snapshot(heroes=heroes(), phase='skip'))
        self.assertEqual(len(self.panel.tree.get_children()), 3)
        self.assertFalse(self.enabled.get())
        self.assertEqual(self.calls, [])
        self.panel.clear()
        self.assertEqual(self.panel.tree.get_children(), ())

    def test_ready_enables_start_and_active_run_always_allows_stop(self):
        self.panel.update_controls(True)
        self.assertTrue(self.panel.toggle.instate(['!disabled']))
        self.enabled.set(True)
        self.panel.update_controls(False)
        self.assertTrue(self.panel.toggle.instate(['!disabled']))
        self.enabled.set(False)
        self.panel.update_controls(False)
        self.assertTrue(self.panel.toggle.instate(['disabled']))
