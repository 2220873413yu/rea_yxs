"""Export attribution, cancellation, UI click boundaries and real XLSX package regression coverage."""
import queue
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from xml.etree import ElementTree as ET
from controller import Worker
from league_export import LeagueExportService,write_export,export_cells,NS
from league_members_panel import LeagueMembersPanel

SCOPE={'zone_id':1,'map_id':186845}


def member(number,league=42):
    """Keep private identity values distinguishable from allowed workbook output."""
    return dict(identity=[number,'private-openid-'+str(number),0,0],name='玩家'+str(number),league_id=league,
                league_name='测试联盟',x=number,y=19,observed_ms=1000)


def profile():
    """Provide distinct gear/gems for every role, including a duplicated strongest/showcase hero."""
    heroes=[]
    for i,role in enumerate(('最强武将','展示武将1','展示武将2','展示武将3')):
        heroes.append(dict(role=role,name='荆轲'if i<2 else'英雄'+str(i),power=123000+i,level=50-i,star=5,
            gems=[dict(slot=1,name='宝具'+str(i),level=10+i)],equipment=[dict(slot=1,name='装备'+str(i))]))
    return dict(ready=True,display_id=532508878926,nickname='新昵称',heroes=heroes,confirmed_ms=1000)


class ExportServiceTests(unittest.TestCase):
    """Exercise the real worker gate and one-request-per-turn export service with fake transport only."""

    def setUp(self):
        """Create two recorded members and one foreign-league player without opening a connection."""
        self.worker=Worker(queue.Queue());self.connection=Mock();self.worker.connection=self.connection
        self.worker.map_index.scope=SCOPE.copy()
        self.worker.map_index.players={str(i):member(i,42 if i<3 else 88)for i in (1,2,3)}
        self.writer=Mock();self.worker.league_export.writer=self.writer
        self.connection.map_index_call.return_value=SCOPE.copy()
        self.connection.query_map_index_player.side_effect=lambda *args:profile()

    def begin(self):
        """Start exactly as the UI does, through the production worker queue."""
        self.worker.request_league_export(42,'sample.xlsx');self.worker.player_tick(self.connection)

    def test_idle_is_passive_and_export_only_queries_saved_selected_league_serially(self):
        """Nothing requests profiles until a click; each tick consumes one recorded identity only."""
        service=self.worker.league_export;service.tick(self.connection)
        self.connection.query_map_index_player.assert_not_called()
        self.begin();self.assertTrue(self.worker.player_busy)
        self.connection.query_map_index_player.assert_not_called()
        self.worker.map_index.players['1']['name']='changed after click'
        service.tick(self.connection)
        self.assertEqual(self.connection.query_map_index_player.call_count,1)
        self.assertEqual(service.entries[0]['member']['name'],'玩家1')
        self.assertTrue(service.active)
        service.tick(self.connection);service.tick(self.connection)
        self.assertEqual(self.connection.query_map_index_player.call_count,2)
        self.assertEqual([c.args[1]['identity'][0]for c in self.connection.query_map_index_player.call_args_list],[1,2])
        self.connection.query_league_members.assert_not_called()
        self.connection.query_map_index_region.assert_not_called()
        self.writer.assert_called_once();self.assertFalse(self.worker.player_busy)

    def test_manual_conflict_or_timeout_stops_batch_and_marks_remaining_rows(self):
        """Uncertain results never cause another player's request or an automatic retry."""
        for error in (RuntimeError('检测到游戏内手动查询，助手本次查询已取消'),TimeoutError('玩家查询超时')):
            with self.subTest(error=str(error)):
                self.setUp();self.connection.query_map_index_player.side_effect=error;self.begin()
                self.worker.league_export.tick(self.connection)
                self.assertEqual(self.connection.query_map_index_player.call_count,1)
                self.assertFalse(self.worker.league_export.active)
                self.assertIn('未查询',self.writer.call_args.args[2][1]['status'])
                self.assertIsNone(self.writer.call_args.args[2][0]['snapshot'])

    def test_definitive_server_rejection_keeps_row_and_continues_once(self):
        """A decoded server refusal is recorded and allows the next saved member to be queried."""
        self.connection.query_map_index_player.side_effect=[RuntimeError('服务器拒绝玩家详情查询（6808）'),profile()]
        self.begin();service=self.worker.league_export;service.tick(self.connection);service.tick(self.connection)
        self.assertEqual(self.connection.query_map_index_player.call_count,2)
        self.assertIn('6808',self.writer.call_args.args[2][0]['status'])
        self.assertIsNotNone(self.writer.call_args.args[2][1]['snapshot'])

    def test_cancel_before_begin_and_map_change_send_no_profiles(self):
        """Queued cancellation survives initialization; changing maps cannot query previous-map identities."""
        self.worker.request_league_export(42,'sample.xlsx');self.worker.league_export.stop()
        self.worker.player_tick(self.connection);self.worker.league_export.tick(self.connection)
        self.connection.query_map_index_player.assert_not_called();self.writer.assert_called_once()
        self.setUp();self.begin();self.connection.map_index_call.return_value={**SCOPE,'map_id':99}
        self.worker.league_export.tick(self.connection)
        self.connection.query_map_index_player.assert_not_called()
        self.assertIn('地图',self.writer.call_args.args[3])

    def test_shared_gate_and_save_failure_do_not_stop_automatic_features(self):
        """Export is exclusive with searches/manual queries; disk errors release only the query gate."""
        self.worker.enabled=True;self.begin()
        with self.assertRaises(RuntimeError):self.worker.request_player('7')
        with self.assertRaises(RuntimeError):self.worker.request_league_query('map_scan',0)
        self.writer.side_effect=PermissionError('文件已打开')
        self.worker.league_export.tick(self.connection);self.worker.league_export.tick(self.connection)
        self.assertFalse(self.worker.player_busy);self.assertTrue(self.worker.enabled)


class ExportWorkbookTests(unittest.TestCase):
    """Validate the actual ZIP/XML spreadsheet, public-data projection and atomic failure behavior."""

    def test_one_member_one_row_all_four_hero_groups_and_no_private_identity(self):
        """Every hero retains its own gem/equipment group, and no UID/OpenID enters workbook parts."""
        entry=dict(member=member(1),snapshot=profile(),status='成功')
        entry['snapshot']['nickname']='=HYPERLINK("https://example.test")'
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'成员.xlsx';write_export(path,SCOPE,[entry],'导出完成')
            with zipfile.ZipFile(path)as archive:
                docs={name:ET.fromstring(archive.read(name))for name in archive.namelist()}
                sheet=docs['xl/worksheets/sheet1.xml'];ns={'s':NS}
                rows=sheet.findall('s:sheetData/s:row',ns);self.assertEqual(len(rows),5)
                values=[''.join(c.itertext())for c in rows[-1]];self.assertEqual(len(values),19)
                self.assertEqual(values[2],'532508878926')
                self.assertEqual(sheet.find('.//s:c[@r="C5"]',ns).get('t'),'inlineStr')
                self.assertIn('荆轲',values[5]);self.assertIn('荆轲',values[8])
                power_cell=sheet.find('.//s:c[@r="E5"]',ns)
                self.assertEqual(power_cell.get('t'),'n')
                self.assertEqual(int(power_cell.find('s:v',ns).text),123000)
                for i in range(4):
                    self.assertIn('宝具'+str(i),values[6+i*3]);self.assertIn('装备'+str(i),values[7+i*3])
                self.assertTrue(values[1].startswith('=HYPERLINK'))
                self.assertFalse(sheet.findall('.//s:f',ns))
                self.assertEqual(sheet.find('s:sheetViews/s:sheetView/s:pane',ns).get('xSplit'),'4')
                self.assertEqual(sheet.find('s:autoFilter',ns).get('ref'),'A4:S5')
                self.assertNotIn('private-openid',b''.join(archive.read(n)for n in archive.namelist()).decode('utf-8'))

    def test_missing_showcase_is_marked_not_inferred_and_failed_row_remains(self):
        """Missing return fields are explicit and cannot be confused with an absent hero or zero power."""
        snap=profile();snap['heroes']=snap['heroes'][:1]
        cells=export_cells(member(1),snap,'成功')
        self.assertEqual(cells[8:17],['未返回']*9)
        cells=export_cells(member(1),None,'查询失败：6808')
        self.assertIsNone(cells[4])
        self.assertEqual(cells[5:17],['未查询']*12);self.assertIn('6808',cells[-2])

    def test_missing_power_stays_blank_and_zero_remains_a_real_number(self):
        """Unknown power must not rank as zero; use the strongest role rather than a showcase maximum."""
        for power,expected in ((None,None),(0,0),('123000',None),(float('nan'),None)):
            snap=profile();snap['heroes'][0]['power']=power
            self.assertEqual(export_cells(member(1),snap,'成功')[4],expected)
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'blank.xlsx';write_export(path,SCOPE,[dict(member=member(1),snapshot=None,status='未查询')],'验证')
            with zipfile.ZipFile(path)as archive:
                sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                self.assertIsNone(sheet.find('.//{'+NS+'}c[@r="E5"]/{'+NS+'}v'))

    def test_failed_replace_preserves_existing_file_and_cleans_temporary_file(self):
        """An open destination cannot be truncated by an unsuccessful export."""
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'existing.xlsx';path.write_bytes(b'existing')
            with patch('league_export.os.replace',side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):write_export(path,SCOPE,[],'导出完成')
            self.assertEqual(path.read_bytes(),b'existing');self.assertEqual(list(Path(folder).iterdir()),[path])


class ExportPanelTests(unittest.TestCase):
    """Keep export behind a deliberate context-menu command, using saved rows rather than server roster rows."""

    def test_menu_selects_clicked_league_and_only_command_queues_export(self):
        """Right-click sends nothing; busy/empty leagues cannot start an export."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock();stop=Mock()
        try:
            panel=LeagueMembersPanel(root,callback,on_export_stop=stop);panel.update_controls(True)
            panel.apply_index(dict(scope=SCOPE,players=[dict(record_key='one',**{k:v for k,v in member(1).items()if k!='identity'})]))
            with patch.object(panel.comparison,'identify_row',return_value='42'),patch.object(panel.league_menu,'tk_popup'),patch.object(panel.league_menu,'grab_release'):
                panel.open_league_menu(SimpleNamespace(y=10,x_root=10,y_root=10))
            callback.assert_not_called();panel.league_menu.invoke(0);callback.assert_called_once_with('export',42)
            panel.clear_cache.invoke();callback.assert_called_with('clear_profile_cache',0)
            count=callback.call_count
            panel.set_busy(True);panel.export_league();panel.clear_cache.invoke();self.assertEqual(callback.call_count,count)
            panel.apply_export_progress(dict(active=True,done=1,total=2,path='file.xlsx'))
            panel.stop_export.invoke();stop.assert_called_once()
            panel.clear();self.assertFalse(panel.export_running)
        finally:root.destroy()


if __name__=='__main__':unittest.main()
