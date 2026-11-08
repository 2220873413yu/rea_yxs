"""Manual alliance browsing tests at the real Lua, wire, worker and Tk boundaries."""
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from lupa.luajit21 import LuaRuntime
from test_player_query import FIXTURE,field
from league_query import wait_league_receipt,query_league
from controller import Worker
from league_members_panel import LeagueMembersPanel

LEAGUE_FIXTURE=r'''
Game.ownLeague=42;Game.league={};Game.briefs={}
function Game.world:getMyLeagueId()return Game.ownLeague end
function Game.world:getTMapGameDataID()return {5,1}end
function Game.league:getTSLGGetLeagueListBriefInfoRsp()return Game.leagueList end
function Game.league:GetTSLGGetLeaguePlayerListInfoRsp()return Game.ownMembers end
Game.league._tSLGGetLeagueBriefInfoRspDic={ContainsKey=function(self,id)return Game.briefs[id]~=nil end,get_Item=function(self,id)return Game.briefs[id]end}
CSLTypes.SLGLeagueModel='league'
local previous=CSLTypes.ModelManager.sharedInstance
CSLTypes.ModelManager.sharedInstance=function()local m=previous();local get=m.getModel
 m.getModel=function(self,key)if key=='league'then return Game.league end;return get(self,key)end;return m end
local T_ID={E_SVR_MSG_ID_SLG_GET_LEAGUE_LIST_BRIEF_INFO=11137,E_SVR_MSG_ID_SLG_GET_LEAGUE_PLAYER_LIST_INFO=11094,E_SVR_MSG_ID_SLG_GET_LEAGUE_BRIEF_INFO=11138}
local controller={sendTSLGGetLeagueListBriefInfoReq=function(self)Game.sent[#Game.sent+1]={T_ID.E_SVR_MSG_ID_SLG_GET_LEAGUE_LIST_BRIEF_INFO,5}end,
 sendTSLGGetLeaguePlayerListInfoReq=function(self)Game.sent[#Game.sent+1]={T_ID.E_SVR_MSG_ID_SLG_GET_LEAGUE_PLAYER_LIST_INFO,Game.ownLeague}end,
 sendTSLGGetLeagueBriefInfoReq=function(self,id)Game.sent[#Game.sent+1]={T_ID.E_SVR_MSG_ID_SLG_GET_LEAGUE_BRIEF_INFO,id}end}
package.loaded.SLGLeagueController={__instanceDict=controller};CSLTypes.SLGLeagueController={getInstance=function()return controller end}
function leagueList()return {0,L({{42,'Own',0,44},{88,'Other',0,30}})}end
function ownRoster()return {0,L({{{456,'member',1,1},'Member'}})}end
function otherRoster()return {0,{88,'Other'},L({{{789,'other',0,1},'OtherMember'}})}end
function readyOther()
 REA_LEAGUE_QUERY.leagues();Game.leagueList=leagueList();REA_LEAGUE_QUERY.league_snapshot()
 REA_LEAGUE_QUERY.roster(88);Game.briefs[88]=otherRoster();return REA_LEAGUE_QUERY.roster_snapshot()
end
'''


class LeagueQueryRuntimeTests(unittest.TestCase):
    """Ensure only explicit clicks send native requests and cache updates match the current selection."""

    def setUp(self):
        """Install both actual Lua adapters without invoking any lookup."""
        self.lua=LuaRuntime(unpack_returned_tuples=True);self.lua.execute(FIXTURE+LEAGUE_FIXTURE)
        for name in ('player_query_runtime.lua','league_query_runtime.lua'):
            self.lua.execute(Path(__file__).with_name(name).read_text(encoding='utf-8'))

    def test_passive_install_and_fresh_list_without_automatic_roster_request(self):
        """Old cached league lists must not populate a new manual query."""
        self.assertEqual(self.lua.execute('return #Game.sent'),0)
        self.lua.execute('Game.leagueList=leagueList();REA_LEAGUE_QUERY.leagues()')
        self.assertFalse(json.loads(self.lua.execute('return REA_LEAGUE_QUERY.league_snapshot()'))['ready'])
        self.lua.execute('Game.leagueList=leagueList()')
        result=json.loads(self.lua.execute('return REA_LEAGUE_QUERY.league_snapshot()'))
        self.assertEqual([r['league_id']for r in result['leagues']],[42,88])
        self.assertEqual(self.lua.execute('return #Game.sent'),1)

    def test_large_league_id_retains_every_decimal_digit(self):
        """Real league IDs can exceed Lua's default tostring precision while still fitting exact doubles."""
        self.lua.execute('Game.ownLeague=317983897897842.0')
        meta=json.loads(self.lua.execute('return REA_LEAGUE_QUERY.roster(0)'))
        self.assertEqual(meta['league_id'],317983897897842)

    def test_own_and_other_league_use_different_native_requests(self):
        """Own roster uses current league context; another league uses only its returned public brief."""
        self.lua.execute('REA_LEAGUE_QUERY.roster(0);Game.ownMembers=ownRoster()')
        result=json.loads(self.lua.execute('return REA_LEAGUE_QUERY.roster_snapshot()'))
        self.assertFalse(result['public']);self.assertEqual(result['members'][0]['name'],'Member')
        self.assertEqual(self.lua.execute('return Game.sent[1][1]'),11094)
        other=json.loads(self.lua.execute('return readyOther()'))
        self.assertTrue(other['public']);self.assertEqual(other['name'],'Other')
        self.assertEqual(self.lua.execute('return Game.sent[#Game.sent][1]'),11138)
        self.assertNotIn('other',json.dumps(other))

    def test_roster_handles_cannot_be_reused_after_refresh_and_foreign_profile_is_hidden(self):
        """Old selection handles are never silently rebound to a different member in a refreshed list."""
        first=json.loads(self.lua.execute('return readyOther()'));key=first['members'][0]['member_key']
        self.lua.execute(f'REA_LEAGUE_QUERY.member({key});Game.profile=profile(Game.uid)')
        self.assertFalse(json.loads(self.lua.execute(f'return REA_LEAGUE_QUERY.member_snapshot({key})'))['ready'])
        self.lua.execute('Game.profile=profile({789,"other",0,1});Game.profile[17]=77')
        result=json.loads(self.lua.execute(f'return REA_LEAGUE_QUERY.member_snapshot({key})'))
        self.assertEqual(result['display_id'],77)
        self.lua.execute('REA_LEAGUE_QUERY.roster(88);Game.briefs[88]=otherRoster();REA_LEAGUE_QUERY.roster_snapshot()')
        with self.assertRaises(Exception):self.lua.execute(f'REA_LEAGUE_QUERY.member({key})')

    def test_changed_account_unknown_league_and_no_membership_send_nothing(self):
        """Reject invalid targets before sending a native query."""
        with self.assertRaises(Exception):self.lua.execute('REA_LEAGUE_QUERY.roster(999)')
        self.lua.execute('Game.ownLeague=0')
        with self.assertRaises(Exception):self.lua.execute('REA_LEAGUE_QUERY.roster(0)')
        self.lua.execute('Game.account.mTLoginRsp={}')
        with self.assertRaises(Exception):self.lua.execute('REA_LEAGUE_QUERY.leagues()')
        self.assertEqual(self.lua.execute('return #Game.sent'),0)

    def test_league_list_refresh_revokes_old_member_handles(self):
        """A new league list click cannot leave old roster identities callable behind cleared UI rows."""
        first=json.loads(self.lua.execute('return readyOther()'))
        self.lua.execute('REA_LEAGUE_QUERY.leagues()')
        with self.assertRaises(Exception):self.lua.execute(f"REA_LEAGUE_QUERY.member({first['members'][0]['member_key']})")

    def test_member_profile_has_no_identity_exposed_to_ui(self):
        """Successful snapshots contain public fields only; no internal account key crosses the adapter."""
        result=json.loads(self.lua.execute('return readyOther()'));key=result['members'][0]['member_key']
        self.lua.execute(f'REA_LEAGUE_QUERY.member({key});Game.profile=profile({{789,"other",0,1}});Game.profile[17]=77')
        raw=self.lua.execute(f'return REA_LEAGUE_QUERY.member_snapshot({key})')
        self.assertNotIn('"uid"',raw);self.assertNotIn('"other"',raw)
        with self.assertRaises(Exception):self.lua.execute('REA_PLAYER_QUERY.bind_member({})')


class LeagueQueryReceiptTests(unittest.TestCase):
    """Exercise production protocol matching, cancellation and exactly-once click dispatch."""

    def log(self,code,req,rsp):
        """Present a bounded native-shaped request/reply pair."""
        return Mock(drain=Mock(return_value=[dict(tag=f's_{code}_1',body=req),dict(tag=f'r_{code}_2',body=rsp)]))

    def test_map_and_league_ids_are_checked(self):
        """A response from another league or a request for another map must be rejected."""
        meta=dict(code=11137,scope='map',map_id=5,zone_id=1)
        wait_league_receipt(self.log(11137,field(0,[field(0,5),field(1,1)]),field(0,0)),meta,lambda:False)
        with self.assertRaises(RuntimeError):wait_league_receipt(self.log(11137,field(0,[field(0,6),field(1,1)]),field(0,0)),meta,lambda:False)
        meta=dict(code=11138,scope='public',league_id=88)
        for league_id in (88,89):
            log=self.log(11138,field(0,88),field(0,0)+field(1,[field(0,league_id)]))
            if league_id==88:wait_league_receipt(log,meta,lambda:False)
            else:
                with self.assertRaises(RuntimeError):wait_league_receipt(log,meta,lambda:False)

    def test_rejection_cancel_timeout_do_not_retry(self):
        """Every uncertain or rejected query stops at this click, with no resend mechanism."""
        meta=dict(code=11094,scope='own',league_id=42)
        with self.assertRaisesRegex(RuntimeError,'6001'):
            wait_league_receipt(self.log(11094,field(0,42),field(0,6001)),meta,lambda:False)
        log=Mock()
        with self.assertRaises(InterruptedError):wait_league_receipt(log,meta,lambda:True)
        with self.assertRaises(TimeoutError):wait_league_receipt(log,meta,lambda:False,timeout=0)
        log.drain.assert_not_called()

    def test_one_click_queries_only_selected_member_and_idle_worker_does_nothing(self):
        """A selected member sends one profile request, while snapshots only read the cache."""
        c=Mock();c.league_query_call.side_effect=[{'code':754},{'ready':False},{'ready':True,'heroes':[]}]
        with patch('league_query.wait_player_receipt')as receipt,patch('league_query.time.sleep'):
            query_league(c,Mock(),'member',3,lambda:False)
        self.assertEqual([x.args[0]for x in c.league_query_call.call_args_list],['member','member_snapshot','member_snapshot'])
        self.assertIs(receipt.call_args.kwargs['owner'],True)
        w=Worker(queue.Queue());w.connection=c
        w.player_tick(c);c.query_league_members.assert_not_called()
        w.request_league_query('roster',0)
        with self.assertRaises(RuntimeError):w.request_player('7')
        c.query_league_members.return_value={'ready':True}
        w.player_tick(c);w.player_tick(c);self.assertEqual(c.query_league_members.call_count,1)

    def test_existing_alliance_mining_query_keeps_its_no_argument_contract(self):
        """LeagueService calls query_league() with no browse parameters; a duplicate method must not replace it."""
        import inspect
        from connection import Connection
        inspect.signature(Connection.query_league).bind(Connection())


class LeagueMembersPanelTests(unittest.TestCase):
    """Verify UI browsing and selection remain passive until a deliberate query action."""

    def test_selection_and_rendering_do_not_query_and_account_clear_discards_handles(self):
        """Only the buttons/double-click callback can dispatch, and busy controls prevent duplicates."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=LeagueMembersPanel(root,callback);panel.update_controls(True)
            panel.apply_leagues(dict(own_league_id=42,leagues=[dict(league_id=42,name='Own'),dict(league_id=88,name='Other')]))
            panel.comparison.selection_set('88');panel.select_league();callback.assert_not_called()
            panel.load.invoke();callback.assert_called_once_with('roster',88)
            panel.apply_roster(dict(league_id=88,name='Other',public=True,confirmed_ms=1000,members=[dict(member_key=3,name='Member')]))
            root.update();self.assertTrue(panel.tree.exists('3'))
            panel.tree.selection_set('3');self.assertEqual(callback.call_count,1)
            panel.query.invoke();callback.assert_called_with('member',3)
            panel.set_busy(True);panel.query_member();self.assertEqual(callback.call_count,2)
            panel.clear();self.assertFalse(panel.tree.get_children());self.assertIsNone(panel.selected_league)
        finally:root.destroy()
