"""Population gaps remain informational; totals and sightings persist on independent manual update paths."""
import json
import queue
import tempfile
import unittest
from unittest.mock import Mock
from league_comparison import compare_leagues
from map_index_store import MapIndexStore,player_key,public_players
from map_index_service import MapIndexService
from controller import Worker
from league_members_panel import LeagueMembersPanel
from test_map_index import row,cipher,SCOPE


def totals(count=50,time=2000,league_id=42):
    """Represent a successful explicit league-list reply without extra profile or identity data."""
    return dict(confirmed_ms=time,leagues=[dict(league_id=league_id,name='联盟',member_count=count)])


class LeagueComparisonTests(unittest.TestCase):
    """Exercise missing/zero/excess populations and the latest identity-to-league association."""

    def test_gap_and_absent_players_are_not_errors_or_deletions(self):
        """A destroyed or unseen city may leave a valid gap; the comparator cannot infer its cause."""
        players=public_players({player_key(row(i)['identity']):row(i)for i in range(1,44)})
        result=compare_leagues(players,totals())[0]
        self.assertEqual((result['total'],result['discovered'],result['difference']),(50,43,7))
        self.assertEqual(result['note'],'差额仅供参考');self.assertEqual(len(players),43)

    def test_unknown_api_count_zero_found_and_excess_are_distinct(self):
        """Never display unknown totals as zero, negative gaps as missing players, or API-only leagues as absent."""
        players=public_players({'key':row()})
        unknown=compare_leagues(players)[0];self.assertIsNone(unknown['total']);self.assertIsNone(unknown['difference'])
        empty=compare_leagues([],totals())[0];self.assertEqual((empty['discovered'],empty['difference']),(0,50))
        excess=compare_leagues(players,totals(count=0))[0]
        self.assertEqual(excess['difference'],-1);self.assertEqual(excess['note'],'人数或归属可能已变化')

    def test_duplicate_identity_uses_latest_recorded_league_and_independent_time(self):
        """A moving member counts once, with no implied refresh of the API population timestamp."""
        key=player_key(row()['identity'])
        players=[dict(record_key=key,**row(observed_ms=1000)),dict(record_key=key,**row(league_id=88,league_name='新盟',observed_ms=3000))]
        groups={r['league_id']:r for r in compare_leagues(players,totals())}
        self.assertEqual(groups[42]['discovered'],0);self.assertEqual(groups[88]['discovered'],1)
        self.assertEqual(groups[42]['confirmed_ms'],2000);self.assertEqual(groups[88]['observed_ms'],3000)


class LeagueComparisonPersistenceTests(unittest.TestCase):
    """Old indexes stay readable and new totals survive searches, restarts and map separation."""

    def setUp(self):
        """Use real atomic storage with a deterministic encryption boundary and no game transport."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=MapIndexStore(self.temp.name,cipher)
        self.worker=Worker(queue.Queue());self.service=MapIndexService(self.worker,self.store)
        self.connection=Mock();self.connection.map_index_call.return_value=SCOPE

    def test_old_index_without_totals_loads_without_any_fetch(self):
        """Read the exact previous payload shape rather than silently migrating through a server request."""
        self.store.root.mkdir(exist_ok=True)
        old=dict(format=1,scope=SCOPE,players=[row()])
        self.store.path(SCOPE).write_bytes(cipher(json.dumps(old).encode()))
        self.service.load(self.connection)
        self.assertEqual(len(self.service.players),1);self.assertIsNone(self.service.league_snapshot)
        self.assertEqual([c.args[0]for c in self.connection.map_index_call.call_args_list],['context'])
        self.connection.query_league_members.assert_not_called()

    def test_manual_totals_save_and_new_sightings_keep_their_own_timestamps(self):
        """A scan changes local sightings only; restart loads both saved sources without another league query."""
        self.service.load(self.connection);self.service.merge([row()])
        self.service.record_leagues(self.connection,totals())
        self.service.merge([row(x=30,observed_ms=3000)])
        restarted=MapIndexService(self.worker,self.store);restarted.load(self.connection)
        self.assertEqual(restarted.league_snapshot['confirmed_ms'],2000)
        self.assertEqual(next(iter(restarted.players.values()))['observed_ms'],3000)
        self.assertIsNone(self.store.load_snapshot({**SCOPE,'map_id':999})['league_snapshot'])
        self.connection.query_league_members.assert_not_called()

    def test_only_the_explicit_league_list_job_updates_totals(self):
        """Worker idle cycles and a manual map search never add a league-population request."""
        self.worker.map_index=self.service;self.worker.connection=self.connection
        self.worker.player_tick(self.connection);self.connection.query_league_members.assert_not_called()
        reply={**totals(),'own_league_id':42,'ready':True}
        self.connection.query_league_members.return_value=reply
        self.worker.request_league_query('leagues',0);self.worker.player_tick(self.connection)
        self.assertEqual(self.connection.query_league_members.call_count,1)
        self.assertEqual(self.service.league_snapshot['leagues'][0]['member_count'],50)
        self.connection.map_index_call.side_effect=lambda op:{'context':SCOPE,'plan':{'regions':[]},'cached':{'players':[]}}[op]
        self.service.begin(self.connection);self.service.tick(self.connection)
        self.assertEqual(self.connection.query_league_members.call_count,1)


class LeagueComparisonUITests(unittest.TestCase):
    """Render and select comparisons entirely locally, including missing/unknown and over-capacity sightings."""

    def test_display_counts_times_and_saved_totals_with_no_callbacks(self):
        """Table interaction, local filtering and account clear do not generate any server query."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=LeagueMembersPanel(root,callback)
            panel.apply_index(dict(scope=SCOPE,players=public_players({'key':row()}),league_snapshot=totals(count=0)))
            values=panel.comparison.item('42')['values']
            self.assertEqual(str(values[1]),'0');self.assertEqual(str(values[2]),'1')
            self.assertEqual(values[3],'超出1');self.assertIn('可能已变化',panel.comparison_note.get())
            panel.comparison.selection_set('42');panel.update_comparison_time()
            self.assertIn('人数更新',panel.comparison_time.get());self.assertIn('本地记录',panel.comparison_time.get())
            callback.assert_not_called()
            panel.apply_index(dict(scope=SCOPE,players=[],league_snapshot=totals()))
            self.assertEqual(str(panel.comparison.item('42')['values'][2]),'0')
            self.assertTrue(panel.comparison.exists('42'))
            panel.clear();self.assertFalse(panel.comparison.get_children());callback.assert_not_called()
        finally:root.destroy()
