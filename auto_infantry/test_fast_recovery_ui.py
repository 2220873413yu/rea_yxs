"""Check the real Tk mode selector without a game connection or saved-preference changes."""
import tkinter as tk
import unittest
from unittest.mock import patch
from hero_panel import HeroPanel


class FastRecoveryUITests(unittest.TestCase):
    """Mode choices are explicit, default normal and unavailable during shared recovery consumers."""

    def test_selector_default_and_active_consumer_lock(self):
        """Changing a visible choice never starts automation; both masters freeze the same selector."""
        root=tk.Tk();root.withdraw()
        try:
            enabled=tk.BooleanVar(root,value=False)
            with patch('hero_panel.load_heroes',return_value=(303,)):
                panel=HeroPanel(root,enabled,lambda:None,lambda:None)
            self.assertEqual(panel.recovery_mode(),'normal')
            panel.update_controls(True,False)
            self.assertEqual(str(panel.mode_box.cget('state')),'readonly')
            panel.mode.set('快速');self.assertEqual(panel.recovery_mode(),'fast')
            enabled.set(True);panel.update_controls(True,False)
            self.assertEqual(str(panel.mode_box.cget('state')),'disabled')
            enabled.set(False);panel.update_controls(True,True)
            self.assertEqual(str(panel.mode_box.cget('state')),'disabled')
            panel.mode.set('invalid')
            with self.assertRaises(ValueError):panel.recovery_mode()
            panel.destroy();del panel,enabled
        finally:root.destroy()
