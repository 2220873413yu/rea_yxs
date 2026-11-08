"""Regression coverage for manual player queries, target attribution and default-idle scheduling."""
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from lupa import LuaRuntime
from player_query import validate_player_id, wait_player_receipt, query_player
from player_panel import hero_details, PlayerPanel
from controller import Worker


def field(tag,value):
    """Encode minimal integer/string/struct fields used by the production JCE reader."""
    def head(kind):
        """Preserve extended tags used by lFriendSequence in the profile response."""
        return bytes([(tag<<4)|kind]) if tag<15 else bytes([240|kind,tag])
    if isinstance(value,list):return head(10)+b''.join(value)+b'\x0b'
    if isinstance(value,str):
        raw=value.encode();return head(6)+bytes([len(raw)])+raw
    return head(3)+value.to_bytes(8,'big',signed=True)


def identity(tag=0,platform=0):
    """Keep the same numeric account on two platforms distinguishable in receipt tests."""
    return field(tag,[field(0,123),field(1,'test-private'),field(2,0),field(3,platform)])


class PlayerReceiptTests(unittest.TestCase):
    """Exercise real decoded wire tags without sending requests or storing account identities."""

    def log(self,code,req,rsp):
        """Present one request/reply pair at the actual protocol parsing seam."""
        return Mock(drain=Mock(return_value=[dict(tag=f's_{code}_1',body=req),dict(tag=f'r_{code}_2',body=rsp)]))

    def test_lookup_and_profile_require_the_same_platform_identity(self):
        """A public ID lookup resolves one identity and a mismatched profile cannot be displayed."""
        target=499205736196
        owner=wait_player_receipt(self.log(42,field(0,target),field(0,0)+field(1,target)+field(2,[identity()])),42,target,lambda:False)
        for platform in (0,1):
            log=self.log(754,identity(),field(0,0)+field(1,[identity(platform=platform)]))
            if platform:
                with self.assertRaisesRegex(RuntimeError,'身份不匹配'):wait_player_receipt(log,754,target,lambda:False,owner)
            else:self.assertIsNone(wait_player_receipt(log,754,target,lambda:False,owner))

    def test_foreign_lookup_rejection_timeout_and_cancel_never_retry(self):
        """Each failure terminates this manual operation instead of consuming another player's result."""
        for req,rsp in [(field(0,8),field(0,0)+field(1,7)),(field(0,7),field(0,6001)+field(1,7))]:
            with self.assertRaises(RuntimeError):wait_player_receipt(self.log(42,req,rsp),42,7,lambda:False)
        log=Mock()
        with self.assertRaises(TimeoutError):wait_player_receipt(log,42,7,lambda:False,timeout=0)
        with self.assertRaises(InterruptedError):wait_player_receipt(log,42,7,lambda:True)
        log.drain.assert_not_called()

    def test_validation_rejects_code_and_imprecise_lua_ids(self):
        """Only exact, positive decimal IDs can reach the Lua source formatter."""
        self.assertEqual(validate_player_id(' 499205736196 '),499205736196)
        for value in ('0','-1','1);error(1)','1e5','９９','9007199254740992'):
            with self.assertRaises(ValueError):validate_player_id(value)

    def test_success_without_identity_is_not_a_resolved_player(self):
        """An empty success payload cannot become a zero-valued target for the next request."""
        log=self.log(42,field(0,7),field(0,0)+field(1,7)+field(2,[]))
        with self.assertRaisesRegex(RuntimeError,'身份字段未返回'):
            wait_player_receipt(log,42,7,lambda:False)

    def test_one_click_sends_lookup_and_profile_once(self):
        """Local cache waiting is allowed; no second profile call occurs after ready=true."""
        connection=Mock();connection.player_call.side_effect=[{'known':False},{'code':42},{'ready':True,'code':754},{'ready':False},{'ready':True,'heroes':[]}]
        with patch('player_query.wait_player_receipt',side_effect=[('identity',),None]),patch('player_query.time.sleep'):
            result=query_player(connection,Mock(),7,lambda:False)
        self.assertTrue(result['ready'])
        self.assertEqual([c.args[0]for c in connection.player_call.call_args_list],['resolve','lookup','profile','snapshot','snapshot'])

    def test_known_successful_profile_does_not_repeat_rejected_id_search(self):
        """An already verified public-ID mapping can request fresh details without the failing friend search."""
        connection=Mock();connection.player_call.side_effect=[{'known':True},{'ready':True,'code':754},
            {'ready':True,'display_id':499664803896,'heroes':[]}]
        with patch('player_query.wait_player_receipt') as receipt:
            result=query_player(connection,Mock(),499664803896,lambda:False)
        self.assertEqual(result['display_id'],499664803896)
        self.assertEqual([c.args[0]for c in connection.player_call.call_args_list],['resolve','profile','snapshot'])
        self.assertIs(receipt.call_args.kwargs['owner'],True)

    def test_known_mapping_reply_requires_public_id_and_matching_identity(self):
        """Direct detail requests still reject a different public ID, even if the identity fields match."""
        for public_id in (7,8):
            log=self.log(754,identity(),field(0,0)+field(1,[identity()])+field(16,public_id))
            if public_id==7:self.assertIsNone(wait_player_receipt(log,754,7,lambda:False,owner=True))
            else:
                with self.assertRaisesRegex(RuntimeError,'用户ID不匹配'):
                    wait_player_receipt(log,754,7,lambda:False,owner=True)

    def test_6808_explains_the_rejected_lookup_stage(self):
        """The native text-content rejection is shown as a lookup failure rather than a second protocol error."""
        log=self.log(1205,field(0,7),field(0,6808)+field(1,7))
        with self.assertRaisesRegex(RuntimeError,'用户ID解析（6808）.*文本包含不可用内容'):
            wait_player_receipt(log,1205,7,lambda:False)

    def test_idle_worker_sends_nothing_and_failure_does_not_stop_automation(self):
        """Only an explicit request wakes this feature; its failure remains isolated from other switches."""
        worker=Worker(queue.Queue());connection=Mock();worker.connection=connection
        worker.player_tick(connection);connection.query_player.assert_not_called()
        worker.request_player('7')
        with self.assertRaises(RuntimeError):worker.request_player('8')
        worker.enabled=True;connection.query_player.side_effect=TimeoutError('test timeout')
        worker.player_tick(connection);worker.player_tick(connection)
        self.assertEqual(connection.query_player.call_count,1)
        self.assertTrue(worker.enabled);self.assertFalse(worker.player_busy)


FIXTURE=r'''
function L(rows)return {get_Count=function()return #rows end,get_Item=function(self,i)return rows[i+1]end}end
Game={sent={},uid={123,'private',0,0}}
Game.account={mTLoginRsp={},getCurrUserProfileRsp=function()return Game.profile end}
Game.world={mIsMapLoaded=true,mTSLGLoginMapRsp={}}
Game.friends={GetVecFindUserInfo=function()return L({{lFriendSequence=7,iRet=0,stUserSimpleProfile={Game.uid,'Player'}}})end}
local models={account=Game.account,world=Game.world,friends=Game.friends}
CSLTypes={MainModel='account',SLGMainModel={GetMapTimeNow=function()return 1000 end},FriendSystemModel='friends',
 ModelManager={sharedInstance=function()return {getModel=function(self,key)if type(key)=='table'then return Game.world end;return models[key]end}end},
 DBSearcher={sharedInstance=function()return {searchHeroInfo=function(self,id)return {0,0,0,0,0,0,'Hero'..id}end,
 searchGemInfo=function(self,id)return {0,0,0,0,0,'Gem'..id}end,searchTNewPlay_Equip=function(self,id)return {0,'Equip'..id}end}end},
 YXSUtils={GBK2UTF8=function(v)return v end},CommonFunc={isSameUserID=function(a,b)return a[1]==b[1]and a[2]==b[2]and a[3]==b[3]and a[4]==b[4]end},
 QQGameSystem={getSystemInstance=function()return {getCurZoneID=function()return 5 end}end}}
local T_ID={E_SVR_MSG_ID_FIND_GAME_USER_INFO=42}
local friend={sendTFindUserInfoReq=function(self,id)Game.sent[#Game.sent+1]={T_ID.E_SVR_MSG_ID_FIND_GAME_USER_INFO,id}end}
package.loaded.FriendController={__instanceDict=friend};CSLTypes.FriendController={sharedInstance=function()return friend end}
CSLTypes.HallMsgMgr={sharedInstance=function()return {sendTUserProfileReq=function(self,...)Game.sent[#Game.sent+1]={754,...}end}end}
function hero(id)return {id,5,50,0,id,L({{true,1,1,10}}),12345,L({{1,1,99,30}})}end
function profile(uid)
 local p={};p[1]=uid;p[10]=hero(100);p[11]=L({{10,20,0,50,100}})
 p[25]=L({hero(200)});p[26]=L({{10,21,0,35,200}})
 return {0,p,0,50,'Player'}
end
Game.profile=profile(Game.uid)
'''


class PlayerRuntimeTests(unittest.TestCase):
    """Run production Lua against native-shaped caches to detect stale target or gem-slot mixing."""

    def setUp(self):
        """Install the adapter into an isolated runtime; installation must be passive."""
        self.lua=LuaRuntime(unpack_returned_tuples=True);self.lua.execute(FIXTURE)
        self.lua.execute(Path(__file__).with_name('player_query_runtime.lua').read_text(encoding='utf-8'))

    def test_fresh_profile_and_separate_strongest_showcase_gem_records(self):
        """Identical gem record IDs in separate lists still resolve using the correct hero's list."""
        self.assertEqual(self.lua.execute('return #Game.sent'),0)
        self.lua.execute('REA_PLAYER_QUERY.lookup(7);REA_PLAYER_QUERY.profile(7)')
        self.assertFalse(json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(7)'))['ready'])
        self.lua.execute('Game.profile=profile(Game.uid)')
        snapshot=json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(7)'))
        self.assertEqual([h['gems'][0]['name']for h in snapshot['heroes']],['Gem20','Gem21'])
        self.assertIn('Equip30',hero_details(snapshot))
        self.assertEqual(self.lua.execute('return Game.sent[2][7]'),True)

    def test_foreign_or_changed_account_never_returns_stale_heroes(self):
        """Even a successful foreign profile cannot populate a target or survive a session change."""
        self.lua.execute('REA_PLAYER_QUERY.lookup(7);REA_PLAYER_QUERY.profile(7);Game.profile=profile({456,"foreign",0,0})')
        self.assertFalse(json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(7)'))['ready'])
        self.lua.execute('Game.account.mTLoginRsp={}')
        with self.assertRaises(Exception):self.lua.execute('REA_PLAYER_QUERY.lookup(7)')

    def test_verified_mapping_sends_only_fresh_profile_not_friend_search(self):
        """A prior successful exact-ID response supplies only the identity; its old hero data is not displayed."""
        self.lua.execute('Game.profile[17]=7')
        self.assertFalse(json.loads(self.lua.execute('return REA_PLAYER_QUERY.resolve(8)'))['known'])
        self.assertTrue(json.loads(self.lua.execute('return REA_PLAYER_QUERY.resolve(7)'))['known'])
        self.lua.execute('REA_PLAYER_QUERY.profile(7)')
        self.assertEqual(self.lua.execute('return #Game.sent'),1)
        self.assertEqual(self.lua.execute('return Game.sent[1][1]'),754)
        self.assertFalse(json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(7)'))['ready'])

    def test_deserialized_identity_matches_native_reply_by_all_fields(self):
        """Saved UID arrays lack native type metadata, but equal four-field identities must still match."""
        self.lua.execute('''local compare=CSLTypes.CommonFunc.isSameUserID
CSLTypes.CommonFunc.isSameUserID=function(a,b)return not not(a.native and b.native and compare(a,b))end
Game.uid.native=true
REA_PLAYER_QUERY.bind_member({Game.uid[1],Game.uid[2],Game.uid[3],Game.uid[4]})
REA_PLAYER_QUERY.profile(0);Game.profile=profile(Game.uid);Game.profile[17]=7''')
        snapshot=json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(0)'))
        self.assertTrue(snapshot['ready']);self.assertEqual(snapshot['display_id'],7)

    def test_saved_identity_rejects_any_changed_component(self):
        """Numeric account, OpenID, login platform and mobile platform must each match the clicked player."""
        for uid in ('{124,"private",0,0}','{123,"foreign",0,0}','{123,"private",1,0}','{123,"private",0,1}'):
            self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);Game.profile=profile('+uid+')')
            self.assertFalse(json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(0)'))['ready'])


class PlayerPanelTests(unittest.TestCase):
    """Verify the actual Tk panel sends nothing until clicked and clears old-account results."""

    def test_manual_only_busy_controls_and_account_clear(self):
        """Rendering, readiness updates and result display never invoke the query callback."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=PlayerPanel(root,callback);panel.update_controls(True)
            callback.assert_not_called();panel.button.invoke();callback.assert_called_once()
            panel.set_busy(True);self.assertIn('disabled',panel.button.state())
            panel.button.invoke();self.assertEqual(callback.call_count,1)
            panel.apply_snapshot(dict(nickname='Player',display_id=7,confirmed_ms=1000,heroes=[]))
            self.assertIn('未返回',panel.details.get('1.0','end'))
            panel.clear();self.assertFalse(panel.busy)
            self.assertEqual(panel.details.get('1.0','end').strip(),'')
            self.assertEqual(callback.call_count,1)
        finally:root.destroy()
