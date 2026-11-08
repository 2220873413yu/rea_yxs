"""Map discovery coverage, persistent scope isolation, cancellation and manual-only UI/runtime contracts."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from lupa.luajit21 import LuaRuntime
from map_index_store import MapIndexStore,player_key,public_players
from map_index_service import MapIndexService
from league_members_panel import LeagueMembersPanel
from test_player_query import FIXTURE

SCOPE=dict(zone_id=1,map_id=186845,width=81,height=61)


def row(uin=123,**changes):
    """Build one native-shaped observation with a stable identity and changeable league/position."""
    value=dict(identity=[uin,'private-'+str(uin),0,1],name='玩家'+str(uin),league_id=42,league_name='联盟',x=10,y=20,observed_ms=1000)
    return {**value,**changes}


def cipher(data,decrypt=False):
    """Keep tests deterministic while verifying that the store actually invokes its encryption boundary."""
    return data[7:]if decrypt else b'SEALED:'+data


class MapIndexStoreTests(unittest.TestCase):
    """Persist only a valid scoped index and preserve the last good file across failed writes."""

    def test_round_trip_separates_maps_and_zones_and_ui_has_no_identity(self):
        """The same nicknames/UIDs in different maps cannot leak into one another's result view."""
        with tempfile.TemporaryDirectory()as folder:
            store=MapIndexStore(folder,cipher);r=row();key=player_key(r['identity'])
            store.save(SCOPE,{key:r})
            self.assertTrue(store.path(SCOPE).read_bytes().startswith(b'SEALED:'))
            self.assertEqual(store.load(SCOPE)[key],r)
            for scope in ({**SCOPE,'zone_id':2},{**SCOPE,'map_id':10}):self.assertEqual(store.load(scope),{})
            self.assertNotIn('private-',json.dumps(public_players(store.load(SCOPE))))

    def test_malformed_or_cross_world_payload_is_rejected_without_overwriting(self):
        """Loading a corrupt file must not quietly replace it with an empty index."""
        with tempfile.TemporaryDirectory()as folder:
            store=MapIndexStore(folder,cipher);r=row();store.save(SCOPE,{player_key(r['identity']):r})
            original=store.path(SCOPE).read_bytes();other={**SCOPE,'map_id':10}
            store.path(other).write_bytes(original)
            with self.assertRaises(RuntimeError):store.load(other)
            self.assertEqual(store.path(other).read_bytes(),original)
            with self.assertRaises(ValueError):store.path(dict(zone_id='../',map_id=1))

    def test_failed_encryption_keeps_previous_file(self):
        """A failed update cannot truncate or replace the earlier successful encrypted save."""
        with tempfile.TemporaryDirectory()as folder:
            store=MapIndexStore(folder,cipher);r=row();key=player_key(r['identity']);store.save(SCOPE,{key:r})
            original=store.path(SCOPE).read_bytes();store.cipher=Mock(side_effect=OSError('cannot encrypt'))
            with self.assertRaises(OSError):store.save(SCOPE,{key:row(x=11)})
            self.assertEqual(store.path(SCOPE).read_bytes(),original)


class MapIndexServiceTests(unittest.TestCase):
    """Finite searches are explicit, interleave one region at a time and retain partial observations."""

    def setUp(self):
        """Use actual persistence and a fake native transport; no emulator or server is contacted."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.worker=Mock();self.worker.guard=threading.RLock();self.worker.closing=threading.Event();self.worker.player_busy=True
        self.service=MapIndexService(self.worker,MapIndexStore(self.temp.name,cipher));self.connection=Mock()
        self.regions=[dict(x=20,y=15),dict(x=60,y=15)]
        def call(operation):
            return {'context':SCOPE,'plan':{'regions':self.regions},'cached':{'players':[row()]}}[operation]
        self.connection.map_index_call.side_effect=call

    def test_restart_loads_local_only_without_a_scan_or_profile_request(self):
        """A restart with saved users performs no list, region or hero lookup."""
        store=self.service.store;r=row();store.save(SCOPE,{player_key(r['identity']):r})
        self.service.load(self.connection);self.service.tick(self.connection)
        self.assertEqual([x.args[0]for x in self.connection.map_index_call.call_args_list],['context'])
        self.connection.query_map_index_region.assert_not_called();self.connection.query_map_index_player.assert_not_called()
        self.assertEqual(len(self.service.players),1);self.assertFalse(self.service.active)

    def test_clicked_pass_requests_each_region_once_and_keeps_missing_players(self):
        """One identity updates league/coordinates; later absent sightings do not delete earlier players."""
        self.connection.query_map_index_region.side_effect=[{'players':[row(x=30,league_id=88,observed_ms=2000),row(456)]},{'players':[]}]
        self.service.begin(self.connection)
        self.service.tick(self.connection);self.service.tick(self.connection);self.service.tick(self.connection)
        self.assertEqual(self.connection.query_map_index_region.call_count,2)
        self.assertEqual(len(self.service.players),2)
        saved=self.service.store.load(SCOPE);self.assertEqual(saved[player_key(row()['identity'])]['league_id'],88)
        self.assertEqual(saved[player_key(row()['identity'])]['x'],30)
        self.assertFalse(self.service.active);self.assertFalse(self.worker.player_busy)
        self.connection.query_map_index_player.assert_not_called()

    def test_cancel_and_map_change_keep_saved_partial_results_without_next_region(self):
        """Stopping or changing worlds cannot continue the old plan or write into another map's file."""
        self.service.begin(self.connection);self.service.stop();self.service.tick(self.connection)
        self.connection.query_map_index_region.assert_not_called();self.assertEqual(len(self.service.store.load(SCOPE)),1)
        self.service.begin(self.connection)
        self.connection.map_index_call.side_effect=None;self.connection.map_index_call.return_value={**SCOPE,'map_id':10}
        self.service.tick(self.connection);self.connection.query_map_index_region.assert_not_called()
        self.assertFalse(self.service.active);self.assertEqual(self.service.store.load({**SCOPE,'map_id':10}),{})

    def test_only_selected_saved_identity_queries_a_profile(self):
        """Index rendering and loading never query heroes; selecting a returned key requests exactly that row."""
        self.service.load(self.connection);self.service.merge([row(),row(456)])
        self.connection.query_map_index_player.assert_not_called()
        key=player_key(row(456)['identity']);self.service.query_player(self.connection,key)
        self.assertEqual(self.connection.query_map_index_player.call_args.args[1]['identity'],row(456)['identity'])
        with self.assertRaises(ValueError):self.service.query_player(self.connection,'unknown')


MAP_FIXTURE=r'''
Game.scope={186845,1};Game.cfg={[10]=81,[11]=61};Game.currentCities={};Game.loginCities={};Game.allies={}
function city(uid,x,y,league,name)return {{{x,y,0},uid[1]or 1,1},0,{uid,name or'Player','',50,league or 42,'League'}}end
Game.world.mTSLGLoginMapRsp={[2]={[4]=L(Game.loginCities)},[7]=L(Game.allies)}
function Game.world:getTMapGameDataID()return Game.scope end
function Game.world:getSignedMapTypeID()return 1 end
local points={get_Item=function(self,key)return Game.currentCities[key]end,GetDictKeys=function()
 local rows={};for i=1,#Game.currentCities do rows[#rows+1]=i end;return L(rows)end}
local chunk={ContainsKey=function(self,key)return key==1 end,get_Item=function()return points end}
Game.map={mInViewDataChunkCacheManager={mtNewPlay_Map=Game.cfg,getAllViewData=function()return L({{mViewDataCache=chunk}})end},
 getMyMainCityCoordinates=function()return {0,0,0}end}
CSLTypes.SLGMapObjectModel='map'
local previous=CSLTypes.ModelManager.sharedInstance
CSLTypes.ModelManager.sharedInstance=function()local m=previous();local get=m.getModel
 m.getModel=function(self,key)if key=='map'then return Game.map end;return get(self,key)end;return m end
CSLTypes.SLGMapUtils={logicToDisplay=function(p)return {p[1],Game.cfg[11]-p[2]}end,
 calMapP2PDistance=function(a,b)return math.abs(a[1]-b[1])+math.abs(a[2]-b[2])end}
REA_AUTO_INFANTRY={hunt_region_assert=function(seq,x,y)assert(seq==3 and x==20 and y==15,'wrong region')end}
'''


class MapIndexRuntimeTests(unittest.TestCase):
    """Execute real LuaJIT to check ID precision, region coverage, deduplication and stale-account guards."""

    def setUp(self):
        """Install passive adapters with native-shaped identity and map models."""
        self.lua=LuaRuntime(unpack_returned_tuples=True);self.lua.execute(FIXTURE+MAP_FIXTURE)
        for name in ('player_query_runtime.lua','map_index_runtime.lua'):
            self.lua.execute(Path(__file__).with_name(name).read_text(encoding='utf-8'))

    def test_context_and_full_map_plan_are_passive_and_cover_boundaries(self):
        """Every map tile is covered with the established overlap, including final partial edge blocks."""
        self.lua.execute('Game.cfg[10]=250;Game.cfg[11]=250')
        plan=json.loads(self.lua.execute('return REA_MAP_INDEX.plan()'))['regions']
        self.assertEqual(len(plan),63);self.assertEqual(len({(r['x'],r['y'])for r in plan}),63)
        for x in range(250):
            for y in range(250):self.assertTrue(any(abs(x-r['x'])<=24 and abs(y-r['y'])<=18 for r in plan))
        self.assertEqual(self.lua.execute('return #Game.sent'),0)

    def test_duplicate_city_cells_and_old_login_records_do_not_duplicate_or_override_player(self):
        """Prefer the freshly loaded region's alliance and coordinates for an already known identity."""
        self.lua.execute('''Game.loginCities[1]=city(Game.uid,1,1,42,'Old');Game.allies[1]=Game.loginCities[1]
Game.currentCities[1]=city(Game.uid,30,20,88,'New');Game.currentCities[2]=Game.currentCities[1]''')
        result=json.loads(self.lua.execute('return REA_MAP_INDEX.region_read(3,20,15)'))['players']
        self.assertEqual(len(result),1);self.assertEqual(result[0]['name'],'New')
        self.assertEqual(result[0]['league_id'],88);self.assertEqual((result[0]['x'],result[0]['y']),(30,41))
        with self.assertRaises(Exception):self.lua.execute('REA_MAP_INDEX.region_read(2,20,15)')

    def test_new_region_cities_are_read_when_initial_login_view_had_none(self):
        """An initially empty view cannot prevent discovering players from later scanned regions."""
        self.lua.execute('Game.currentCities[1]=city({456,"new-player",1,0},30,20,88,"New")')
        result=json.loads(self.lua.execute('return REA_MAP_INDEX.region_read(3,20,15)'))['players']
        self.assertEqual(len(result),1);self.assertEqual(result[0]['identity'][0],456)

    def test_scope_change_stops_reads_and_only_profile_operation_sends(self):
        """Loading cached map data sends nothing; a selected identity still requires a fresh matched profile."""
        self.lua.execute('REA_MAP_INDEX.context();REA_MAP_INDEX.cached()');self.assertEqual(self.lua.execute('return #Game.sent'),0)
        self.lua.execute('REA_MAP_INDEX.profile(Game.uid)');self.assertEqual(self.lua.execute('return Game.sent[1][1]'),754)
        self.assertFalse(json.loads(self.lua.execute('return REA_MAP_INDEX.profile_snapshot()'))['ready'])
        self.lua.execute('Game.scope[1]=999')
        with self.assertRaises(Exception):self.lua.execute('REA_MAP_INDEX.context()')


class MapIndexPanelTests(unittest.TestCase):
    """Verify that loading/filtering saved sightings cannot initiate network discovery or hero requests."""

    def test_local_reload_filtering_and_explicit_search_and_member_click(self):
        """The startup index and local alliance filter remain passive; only deliberate query controls dispatch."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=LeagueMembersPanel(root,callback);panel.update_controls(True)
            players={player_key(r['identity']):r for r in (row(),row(456,league_id=88,league_name='Other'))}
            panel.apply_index(dict(scope=SCOPE,players=public_players(players)));callback.assert_not_called()
            self.assertEqual(len(panel.comparison.get_children()),2)
            panel.comparison.selection_set('42');panel.select_league();callback.assert_not_called()
            self.assertEqual(len(panel.tree.get_children()),1)
            key=panel.tree.get_children()[0];panel.tree.selection_set(key);panel.query.invoke()
            callback.assert_called_once_with('saved_member',key[6:])
            panel.search.invoke();callback.assert_called_with('map_scan',0)
            panel.clear();self.assertFalse(panel.local_records);self.assertFalse(panel.tree.get_children())
        finally:root.destroy()

    def test_league_navigation_clears_old_profile_and_preserves_selection_on_refresh(self):
        """League selection filters saved players locally, including a league with zero discovered cities."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=LeagueMembersPanel(root,callback);panel.update_controls(True)
            players={player_key(r['identity']):r for r in (row(),row(456,league_id=88,league_name='Other'))}
            snapshot=dict(scope=SCOPE,players=public_players(players),league_snapshot=dict(confirmed_ms=2000,
                leagues=[dict(league_id=99,name='Empty',member_count=50)]))
            panel.apply_index(snapshot)
            panel.comparison.selection_set('88');panel.select_league();panel.replace_details('Previous hero')
            panel.comparison.selection_set('42');panel.select_league()
            self.assertEqual(panel.details.get('1.0','end').strip(),'')
            self.assertEqual(panel.tree.item(panel.tree.get_children()[0])['values'][0],'玩家123')
            panel.apply_index(snapshot);root.update()
            self.assertEqual(panel.selected_league,42)
            panel.comparison.selection_set('99');panel.select_league()
            self.assertFalse(panel.tree.get_children());self.assertIn('尚无本地记录',panel.status.get())
            callback.assert_not_called()
        finally:root.destroy()

    def test_busy_profile_query_does_not_switch_to_another_league(self):
        """A pending profile cannot appear under a different alliance selected while the request was in flight."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=LeagueMembersPanel(root,callback);panel.update_controls(True)
            players={player_key(r['identity']):r for r in (row(),row(456,league_id=88,league_name='Other'))}
            panel.apply_index(dict(scope=SCOPE,players=public_players(players)))
            panel.comparison.selection_set('42');panel.select_league();panel.set_busy(True)
            panel.comparison.selection_set('88');panel.select_league();root.update()
            self.assertEqual(panel.selected_league,42);self.assertEqual(panel.comparison.selection(),('42',))
            callback.assert_not_called()
        finally:root.destroy()
