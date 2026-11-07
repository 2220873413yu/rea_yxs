"""Verify the actual Tkinter app layout and coordinate editor without connecting to the game."""
import importlib.machinery
import json
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from resource_list_dialog import ResourceListDialog
from resource_preferences import save_coordinates, load_coordinates


def main():
    """Keep the test window hidden, isolate saves, and disable the app's connection entry point."""
    module = importlib.machinery.SourceFileLoader('resource_ui_preview', str(ROOT / 'auto_infantry/app.pyw')).load_module()
    root = tk.Tk()
    root.withdraw()
    with patch.object(module.App, 'connect', lambda self: None), patch.object(module.tk, 'Tk', return_value=root), \
            patch('collection_panel.load_coordinates', return_value=()):
        app = module.App()
    try:
        root.update_idletasks()
        panel = app.collection_panel
        assert not app.collect_enabled.get()
        assert panel.check_button.instate(['disabled'])
        teams = app.collection_teams_panel
        teams.set_active(True, True)
        view = {'server_now_ms': 1793879346000, 'next_check_ms': 1793879407000,
                'rows': [{'army_id': 1, 'hero_id': 242, 'hero': '霍光', 'state': '采集中',
                          'end_ms': 1793879406000, 'check_ms': 1793879407000},
                         {'army_id': 2, 'hero_id': 305, 'hero': '陈圆圆', 'state': '返城中',
                          'end_ms': 1793879436000, 'check_ms': 1793879437000}]}
        teams.apply_snapshot(view)
        assert len(teams.tree.get_children()) == 2
        assert teams.tree.item('1', 'values')[2:] == ('11-05 19:50:06', '11-05 19:50:07')
        teams.set_active(False, True)
        assert '已取消' in teams.tree.item('1', 'values')[3]
        assert '上次数据' in teams.note.get()
        teams.set_active(True, True)
        assert '等待刷新' in teams.tree.item('1', 'values')[3]
        teams.apply_snapshot({**view, 'rows': view['rows'][:1]})
        assert not teams.tree.exists('2')
        selected_before = app.hero_panel.selected()
        app.hero_panel.apply_roster({'items': 30, 'heroes': [{'hero_id': 303, 'name': '西施',
            'found': True, 'army_known': True, 'fresh': False, 'busy': True, 'hero_state': 1,
            'activity_label': '返城中', 'confirmed_ms': 1793879346000, 'remaining_ms': 0, 'power': 113554}]})
        values = app.hero_panel.tree.item('303', 'values')
        assert values[2:4] == ('返城中', '11-05 19:49:06')
        assert app.hero_panel.selected() == selected_before
        assert not hasattr(panel, 'kind') and not hasattr(panel, 'radius') and not hasattr(panel, 'x_entry')
        try:
            panel.options()
        except ValueError as error:
            assert '清单' in str(error)
        else:
            raise AssertionError('Empty list was accepted')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'resources.json'
            with patch('resource_list_dialog.save_coordinates', side_effect=lambda pairs: save_coordinates(pairs, path)):
                editor = ResourceListDialog(panel, (), panel.list_saved)
                editor.withdraw()
                editor.text.insert('1.0', '97,192\n101,191\n97,192')
                editor.save()
            assert load_coordinates(path) == ((97, 192), (101, 191))
            assert panel.options().coordinates == ((97, 192), (101, 191))
        app.collect_enabled.set(True)
        panel.update_controls(True)
        assert panel.list_button.instate(['disabled'])
        assert panel.check_button.instate(['!disabled'])
        app.collect_enabled.set(False)
        panel.update_controls(True)
        assert panel.list_button.instate(['!disabled'])
        assert panel.check_button.instate(['disabled'])
        panel.apply_queue({'queue_used': 1, 'queue_limit': 4, 'queue_known': True})
        assert '1 / 4' in panel.queue_text.get()
        panel.update_controls(False)
        assert '上次' in panel.queue_text.get()
        panel.update_controls(True)
        root.update_idletasks()
        result = {'requested': [root.winfo_reqwidth(), root.winfo_reqheight()],
                  'collection_panel': [panel.winfo_reqwidth(), panel.winfo_reqheight()],
                  'coordinates': panel.coordinates, 'game_connected': False,
                  'switches_off': not any((app.enabled.get(), app.hero_enabled.get(), app.collect_enabled.get()))}
        assert root.winfo_reqwidth() <= 1050 and root.winfo_reqheight() <= 940, result
        print(json.dumps(result, ensure_ascii=False))
    finally:
        app.close()


if __name__ == '__main__':
    main()
