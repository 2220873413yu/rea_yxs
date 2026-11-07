"""Check timer display and default-off controls with a hidden Tk window, without game requests."""
import tkinter as tk
import unittest
from report_panel import ReportPanel


class ReportPanelTests(unittest.TestCase):
    """Displaying a deadline or snapshot must never authorize reward collection."""

    def test_default_off_disconnected_and_role_reset_clear_deadline(self):
        root=tk.Tk();root.withdraw()
        try:
            enabled=tk.BooleanVar(root,value=False);calls=[]
            panel=ReportPanel(root,enabled,lambda:calls.append(True))
            self.assertTrue(panel.toggle.instate(['disabled']))
            panel.update_controls(True);self.assertTrue(panel.toggle.instate(['!disabled']))
            panel.apply_next(1794070000000)
            panel.apply_snapshot(dict(total=300,claimable=27,military=100,military_pending=24,
                internal=100,internal_pending=3,event=100,event_pending=0,confirmed_ms=1794060000000))
            self.assertIn('27',panel.summary.get());self.assertFalse(enabled.get());self.assertEqual(calls,[])
            panel.clear();self.assertIn('未安排',panel.next_time.get());self.assertIn('尚未查询',panel.summary.get())
        finally:
            root.destroy()
