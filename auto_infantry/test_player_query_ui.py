"""Exercise production navigation hooks through native-shaped request, cache, and notification calls."""
import json
import unittest
from pathlib import Path
from lupa import LuaRuntime
from test_player_query import FIXTURE


class PlayerQueryUITests(unittest.TestCase):
    """Keep helper replies silent while real foreground queries retain the full original path."""

    def setUp(self):
        """Build the actual adapter fixture plus native response and scene dispatch seams."""
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FIXTURE)
        self.lua.execute('''
Game.shown=0;Game.modelUpdates=0;Game.sceneChanges=0;Game.notifications={}
local notifierMethods={notifyStateChange=function(self,id)
 Game.notifications[#Game.notifications+1]=id
 if id==1039 then Game.sceneChanges=Game.sceneChanges+1;Game.shown=Game.shown+1 end
end}
local notifier=setmetatable({},{__index=notifierMethods})
package.loaded.SceneNotifier={__instanceDict=notifierMethods}
CSLTypes.SceneNotifier={getInstance=function()return notifier end}
local hallMethods={sendTUserProfileReq=function(self,...)Game.sent[#Game.sent+1]={754,...}end,
 parseTUserProfileRsp=function(self,rsp)
  if rsp[1]~=0 then return end
  Game.profile=rsp;Game.modelUpdates=Game.modelUpdates+1
  notifier:notifyStateChange(900)
  if Game.throwParser then error('parser failure')end
  notifier:notifyStateChange(1039)
 end}
local hall=setmetatable({},{__index=hallMethods})
package.loaded.HallMsgMgr={__instanceDict=hallMethods}
CSLTypes.HallMsgMgr={sharedInstance=function()return hall end}
Game.hall=hall;Game.notifier=notifier
Game.originalSend=hall.sendTUserProfileReq;Game.originalParse=hall.parseTUserProfileRsp
Game.originalNotify=notifier.notifyStateChange
Game.registeredParser=hall.parseTUserProfileRsp
''')
        self.source=Path(__file__).with_name('player_query_ui.lua').read_text(encoding='utf-8')
        self.lua.execute(self.source)
        self.lua.execute(Path(__file__).with_name('player_query_runtime.lua').read_text(encoding='utf-8'))

    def test_helper_lookup_profile_updates_cache_without_scene_or_page_change(self):
        """Run the real lookup/profile adapter through the wrappers, including protocol upvalue resolution."""
        self.lua.execute('REA_PLAYER_QUERY.resolve(7);REA_PLAYER_QUERY.lookup(7);REA_PLAYER_QUERY.profile(7)')
        self.assertEqual(self.lua.execute('return Game.sent[1][1]'),42)
        self.lua.execute('Game.registeredParser(Game.hall,profile(Game.uid))')
        result=json.loads(self.lua.execute('return REA_PLAYER_QUERY.snapshot(7)'))
        self.assertTrue(result['ready'])
        self.assertEqual(self.lua.execute('return Game.modelUpdates'),1)
        self.assertEqual(self.lua.execute('return Game.notifications[1]'),900)
        self.assertEqual(self.lua.execute('return Game.shown+Game.sceneChanges'),0)

    def test_manual_query_before_during_and_after_helper_remains_native(self):
        """A concurrent same-target click cancels the helper and never mutes the manual UI."""
        self.lua.execute('Game.hall:sendTUserProfileReq(Game.uid);Game.hall:parseTUserProfileRsp(profile(Game.uid))')
        self.assertEqual(self.lua.execute('return Game.shown'),1)
        self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);Game.hall:sendTUserProfileReq(Game.uid)')
        with self.assertRaisesRegex(Exception,'手动查询'):
            self.lua.execute('REA_PLAYER_QUERY.snapshot(0)')
        self.lua.execute('REA_PLAYER_QUERY_UI.finish();Game.hall:parseTUserProfileRsp(profile(Game.uid));Game.hall:parseTUserProfileRsp(profile(Game.uid))')
        self.assertEqual(self.lua.execute('return Game.shown'),3)
        self.lua.execute('Game.hall:sendTUserProfileReq(Game.uid);Game.hall:parseTUserProfileRsp(profile(Game.uid))')
        self.assertEqual(self.lua.execute('return Game.shown'),4)

    def test_foreign_request_and_friend_lookup_interrupt_helper(self):
        """Both game entry points revoke helper ownership before a response can populate its panel."""
        for request in ('Game.hall:sendTUserProfileReq({321,"other",0,0})',
                        'CSLTypes.FriendController.sharedInstance():sendTFindUserInfoReq(8)'):
            with self.subTest(request=request):
                self.setUp()
                self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);'+request)
                with self.assertRaisesRegex(Exception,'手动查询'):
                    self.lua.execute('REA_PLAYER_QUERY_UI.check()')

    def test_timeout_late_reply_does_not_open_page_or_mix_with_next_query(self):
        """A timed-out request retains its identity marker until its late response is handled."""
        self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);REA_PLAYER_QUERY_UI.finish()')
        with self.assertRaisesRegex(Exception,'等待响应'):
            self.lua.execute('REA_PLAYER_QUERY_UI.begin()')
        self.lua.execute('Game.hall:parseTUserProfileRsp(profile(Game.uid));REA_PLAYER_QUERY_UI.begin()')
        self.assertEqual(self.lua.execute('return Game.shown'),0)

    def test_error_and_parser_exception_restore_notification_scope(self):
        """Neither server rejection nor an exception can leave navigation globally suppressed."""
        self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);Game.hall:parseTUserProfileRsp({6808})')
        self.lua.execute('REA_PLAYER_QUERY_UI.finish(true);REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);Game.throwParser=true')
        with self.assertRaisesRegex(Exception,'parser failure'):
            self.lua.execute('Game.hall:parseTUserProfileRsp(profile(Game.uid))')
        self.lua.execute('Game.throwParser=false;REA_PLAYER_QUERY_UI.finish();Game.hall:sendTUserProfileReq(Game.uid);Game.hall:parseTUserProfileRsp(profile(Game.uid))')
        self.assertEqual(self.lua.execute('return Game.shown'),1)

    def test_idle_install_reinstall_other_notifications_and_disconnect(self):
        """Hooks are passive and idempotent; disconnect restores exact native functions."""
        self.assertEqual(self.lua.execute('return #Game.sent'),0)
        self.lua.execute(self.source)
        self.lua.execute('Game.notifier:notifyStateChange(1035)')
        self.assertEqual(self.lua.execute('return Game.notifications[1]'),1035)
        self.lua.execute('REA_PLAYER_QUERY_UI.close()')
        self.assertTrue(self.lua.execute('return Game.hall.sendTUserProfileReq==Game.originalSend and Game.hall.parseTUserProfileRsp==Game.originalParse and Game.notifier.notifyStateChange==Game.originalNotify'))
        self.lua.execute('Game.hall:sendTUserProfileReq(Game.uid);Game.hall:parseTUserProfileRsp(profile(Game.uid))')
        self.assertEqual(self.lua.execute('return Game.shown'),1)

    def test_pending_foreground_query_prevents_helper_from_claiming_it(self):
        """A foreground request already observed by the hook has priority over a new helper query."""
        self.lua.execute('Game.hall:sendTUserProfileReq(Game.uid)')
        with self.assertRaisesRegex(Exception,'等待响应'):
            self.lua.execute('REA_PLAYER_QUERY_UI.begin()')

    def test_hall_lease_survives_world_close_and_restores_when_last_user_releases(self):
        """A world reconnect cannot remove a hall query's navigation filter halfway through its reply."""
        self.lua.execute('REA_PLAYER_QUERY_UI.claim();REA_PLAYER_QUERY_UI.retain();REA_PLAYER_QUERY_UI.close()')
        self.assertTrue(self.lua.execute('return REA_PLAYER_QUERY_UI~=nil and Game.notifier.notifyStateChange~=Game.originalNotify'))
        self.lua.execute('REA_PLAYER_QUERY_UI.release()')
        self.assertTrue(self.lua.execute('return REA_PLAYER_QUERY_UI==nil and Game.notifier.notifyStateChange==Game.originalNotify'))

    def test_hall_release_keeps_an_active_world_owners_hooks(self):
        """Finishing a temporary hall query does not tear down the map worker's shared hook."""
        self.lua.execute('REA_PLAYER_QUERY_UI.claim();REA_PLAYER_QUERY_UI.retain();REA_PLAYER_QUERY_UI.release()')
        self.assertTrue(self.lua.execute('return REA_PLAYER_QUERY_UI~=nil'))
        self.lua.execute('REA_PLAYER_QUERY_UI.close()')
        self.assertTrue(self.lua.execute('return Game.notifier.notifyStateChange==Game.originalNotify'))

    def test_own_profile_navigation_is_filtered_only_for_matching_helper_reply(self):
        """The alternate own-profile notification shares the identity gate; unrelated 1035 stays native."""
        self.lua.execute('REA_PLAYER_QUERY.bind_member(Game.uid);REA_PLAYER_QUERY.profile(0);Game.profile=profile(Game.uid);Game.notifier:notifyStateChange(1035)')
        self.assertEqual(self.lua.execute('local a,b,c,n=REA_PLAYER_QUERY_UI.status();return n'),1)
        self.assertEqual(self.lua.execute('return #Game.notifications'),0)
        self.lua.execute('REA_PLAYER_QUERY_UI.finish();Game.notifier:notifyStateChange(1035)')
        self.assertEqual(self.lua.execute('return Game.notifications[1]'),1035)


if __name__=='__main__':unittest.main()
