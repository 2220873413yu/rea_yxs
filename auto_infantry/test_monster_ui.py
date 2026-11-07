"""Validate real Tk controls with background connection startup disabled; no game interaction occurs."""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


class MonsterUITests(unittest.TestCase):
    """Check default-off behavior and the full window's required layout height using the actual widgets."""

    def test_default_off_layout_and_controls(self):
        """Construction must leave all four switches off and must fit the requested desktop window."""
        loader=importlib.machinery.SourceFileLoader('hunt_app_ui_test',str(Path(__file__).with_name('app.pyw')))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        module=importlib.util.module_from_spec(spec);loader.exec_module(module)
        with patch.object(module.threading,'Thread'):
            app=module.App()
        try:
            app.root.withdraw();app.root.update_idletasks()
            self.assertEqual([app.enabled.get(),app.hero_enabled.get(),app.collect_enabled.get(),app.hunt_enabled.get()],
                             [False,False,False,False])
            self.assertFalse(app.league_enabled.get())
            self.assertFalse(app.beacon_enabled.get())
            self.assertEqual(len(app.beacon_panel.choice_boxes),4)
            self.assertIn('disabled',app.beacon_panel.toggle.state())
            app.beacon_panel.apply_snapshot(dict(server_now_ms=1793955800000,refresh_end_ms=1793955884557,
                queue_used=1,queue_limit=5,check_ms=1793955885557,
                events=[dict(kind=1,event_id=10,x=90,y=80,state=3,army_id=0,end_ms=1793955999999)],
                armies=[dict(name='刘备',army_id=77,state=9,target_id=10,end_ms=1793955884557)]))
            self.assertIn('1 / 5',app.beacon_panel.summary.get())
            self.assertIn('已取消',app.beacon_panel.timing.get())
            beacon_rows=[app.beacon_panel.tree.item(i)['values'] for i in app.beacon_panel.tree.get_children()]
            self.assertEqual(beacon_rows[0][4],'—')
            self.assertEqual(beacon_rows[1][2],'返城中')
            self.assertFalse(app.training_speed.get())
            self.assertFalse(app.selections[803].get())
            self.assertEqual(list(app.choice_widgets), [412, 413, 411, 803])
            self.assertEqual(app.choice_widgets[803].cget('text'), '斥候')
            self.assertIn('disabled', app.league_panel.toggle.state())
            app.league_panel.apply_snapshot(dict(mine=dict(name='联盟铁矿', x=125, y=72, stock=7409085,
                                                          occupied=3, capacity=30), server_now_ms=1793955800000,
                rows=[dict(name='陈胜',army_id=155136,state=9,end_ms=1793955884557,check_ms=1793955885557)]))
            self.assertIn('3 / 30', app.league_panel.mine.get())
            league_row = app.league_panel.tree.item(app.league_panel.tree.get_children()[0])['values']
            self.assertEqual(league_row[1], '返城中')
            self.assertEqual(league_row[3], '已取消（自动关闭）')
            self.assertEqual(app.monster_panel.options().radius,20)
            self.assertEqual(float(app.monster_panel.range_box.cget('to')),200)
            app.monster_panel.radius.set(200)
            self.assertEqual(app.monster_panel.options().radius,200)
            app.monster_panel.radius.set(20)
            self.assertIn('disabled',app.monster_panel.toggle.state())
            app.ready=True;app.update_controls()
            self.assertNotIn('disabled',app.beacon_panel.toggle.state())
            app.beacon_enabled.set(True);app.update_controls()
            self.assertTrue(all('disabled' in box.state() for box in app.beacon_panel.choice_boxes))
            self.assertNotIn('disabled',app.beacon_panel.toggle.state())
            app.beacon_enabled.set(False);app.update_controls()
            self.assertNotIn('disabled', app.league_panel.check.state())
            self.assertNotIn('disabled',app.monster_panel.toggle.state())
            app.hunt_enabled.set(True);app.update_controls()
            self.assertIn('disabled',app.monster_panel.range_box.state())
            self.assertNotIn('disabled',app.monster_panel.check.state())
            rows=[dict(name='英雄'+str(i),army_id=i,x=99+i,y=184,followers=i,state=2,
                       end_ms=1793955884557,skipped=False) for i in (1,2,3)]
            app.monster_panel.apply_snapshot(dict(queue_known=True,queue_used=4,queue_limit=5,managed=3,
                                                  ignored=2,rows=rows,server_now_ms=1793955800000))
            self.assertEqual(len(app.monster_panel.tree.get_children()),3)
            self.assertIn('4 / 5',app.monster_panel.capacity.get())
            self.assertIn('本轮忽略 2',app.monster_panel.capacity.get())
            self.assertLessEqual(app.root.winfo_reqheight(),1000)
        finally:
            app.close()


if __name__=='__main__':unittest.main()
