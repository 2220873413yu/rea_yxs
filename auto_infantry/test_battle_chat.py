"""No-network coverage for explicit chat clicks, native battle/account fences and real GBK wire confirmation."""
import json
import queue
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from lupa import LuaRuntime
from battle_chat import validate_message,lua_text,wire_text,wait_chat_receipt,send_battle_chat_once,BattleChatSession
from battle_chat_panel import BattleChatPanel
from test_player_query import field


def packet(direction,code,text='测试',uin=123):
    """Use the GBK string bytes observed on the actual room chat transport."""
    raw=text.encode('gbk');body=field(0,uin)+b'\x16'+bytes([len(raw)])+raw+field(2,0)
    return dict(tag=f'{direction}_{code}_1',body=body)


class BattleChatReceiptTests(unittest.TestCase):
    """Verify request/echo ownership without sending any messages."""

    def test_matching_own_10007_broadcast_confirms_one_request(self):
        """Actual chat confirmation is 10007, and sender plus literal text must both match."""
        log=Mock(drain=Mock(return_value=[packet('s',10006),packet('r',10007,uin=999),packet('r',10007)]))
        self.assertEqual(wire_text(packet('s',10006)['body']),'测试')
        result=wait_chat_receipt(log,'测试',123,lambda:False,Mock())
        self.assertIn('服务器已回推',result)
        log.drain.assert_called_once()

    def test_mismatched_or_duplicate_outgoing_send_is_never_attributed(self):
        """Manual overlapping sends cancel confirmation, even if they contain the same text."""
        for frames in ([packet('s',10006,'其他')],[packet('s',10006),packet('s',10006)]):
            with self.assertRaisesRegex(RuntimeError,'其他聊天发送'):
                wait_chat_receipt(Mock(drain=Mock(return_value=frames)),'测试',123,lambda:False,Mock())

    def test_timeout_cancel_and_changed_battle_never_retry(self):
        """Uncertainty cannot invoke any sender; only local log reads occur during bounded confirmation."""
        log=Mock()
        with self.assertRaises(TimeoutError):wait_chat_receipt(log,'测试',123,lambda:False,Mock(),timeout=0)
        log.drain.assert_not_called()
        with self.assertRaises(InterruptedError):wait_chat_receipt(log,'测试',123,lambda:True,Mock())
        check=Mock(side_effect=RuntimeError('room changed'))
        with self.assertRaisesRegex(RuntimeError,'room changed'):wait_chat_receipt(log,'测试',123,lambda:False,check)

    def test_validation_and_literal_escape(self):
        """Unsupported/oversized content is rejected before transport; quotes remain data."""
        self.assertEqual(validate_message('测试'),'测试')
        self.assertEqual(validate_message('字'*20),'字'*20)
        for value in ('','   ','字'*21,'line\nbreak','abc\x00','emoji🙂'):
            with self.assertRaises(ValueError):validate_message(value)
        lua=LuaRuntime();value='";error(1);--测试'
        self.assertEqual(lua.execute('return '+lua_text(value)),value)


FIXTURE=r'''
Game={stage='GameSceneStage',room=1,tableId=2,gameId=3,uin=123,sent={},spectator=false,clock=100}
local account={mTLoginRsp={0},getMainParam=function()return {myUserInfo={stUID={Game.uin,'private',1,0}}}end}
local game={isByStander=function()return Game.spectator end,getRoomId=function()return Game.room end,
 getTableId=function()return Game.tableId end,getGameID=function()return Game.gameId end}
local controller={sendChatMsg=function(self,text)Game.sent[#Game.sent+1]=text end}
Game.account=account;Game.controller=controller
CSLTypes={MainModel='main',GameModel='game',ModelManager={sharedInstance=function()return {
 getModel=function(self,kind)if kind=='main'then return account else return game end end}end},
 YXSUtils={UTF82GBK=function(text)return text end},RefreshTimer={getServerTimeNow=function()return Game.clock end},
 ChatController={getInstance=function()return controller end}}
package.loaded.HeroPalaceItem={__instanceDict={getCurrentStageName=function()return Game.stage end}}
'''


class BattleChatRuntimeTests(unittest.TestCase):
    """Run the production Lua exactly once per fake click without changing any input-widget state."""

    def setUp(self):
        """Initialize a native-shaped battle with a frozen account/room identity."""
        self.lua=LuaRuntime(unpack_returned_tuples=True);self.lua.execute(FIXTURE)
        self.source=Path(__file__).with_name('battle_chat_runtime.lua').read_text(encoding='utf-8').replace('__CHAT_API__','TEST_CHAT')

    def test_install_is_passive_send_is_once_and_no_world_model_is_required(self):
        """The battle-only bridge exposes no automation gates and initialization never sends."""
        meta=json.loads(self.lua.execute(self.source));self.assertEqual(meta['own_uin'],123)
        self.assertEqual(self.lua.execute('return #Game.sent'),0)
        self.lua.execute('TEST_CHAT.send("测试")')
        with self.assertRaisesRegex(Exception,'重复发送'):self.lua.execute('TEST_CHAT.send("测试")')
        self.assertEqual(self.lua.execute('return #Game.sent'),1)

    def test_stage_spectator_room_and_account_changes_block_sending(self):
        """Each context change is detected before the native sender can run."""
        for change in ('Game.stage="ReadySceneStage"','Game.spectator=true','Game.room=9','Game.tableId=9',
                       'Game.gameId=9','Game.uin=456','Game.account.mTLoginRsp={0}'):
            with self.subTest(change=change):
                self.setUp();self.lua.execute(self.source);self.lua.execute(change)
                with self.assertRaises(Exception):self.lua.execute('TEST_CHAT.send("测试")')
                self.assertEqual(self.lua.execute('return #Game.sent'),0)

    def test_not_in_battle_and_native_duplicate_rule_are_preserved(self):
        """Invalid stage prevents installation; matching recent text keeps the native duplicate gate."""
        self.lua.execute('Game.stage="ZhuQueMatchingStage"')
        with self.assertRaisesRegex(Exception,'实际战斗'):self.lua.execute(self.source)
        self.setUp();self.lua.execute(self.source)
        self.lua.execute('Game.controller.chatStringCache="测试";Game.controller.chatTimestamp=98')
        with self.assertRaisesRegex(Exception,'五秒'):self.lua.execute('TEST_CHAT.send("测试")')
        self.assertEqual(self.lua.execute('return #Game.sent'),0)


class BattleChatSessionTests(unittest.TestCase):
    """Thread ownership is click-only, cancellation-safe and never a retry loop."""

    def test_idle_double_click_cancel_and_close(self):
        """Only submit invokes the sender; account change marks old replies with the preceding generation."""
        events=queue.Queue();entered=threading.Event();release=threading.Event()
        def sender(message,cancelled):
            """Hold one fake send until the test explicitly releases it."""
            entered.set();release.wait(2);return 'confirmed'
        fake=Mock(side_effect=sender);session=BattleChatSession(events,fake)
        fake.assert_not_called();session.submit('测试');self.assertTrue(entered.wait(1))
        with self.assertRaisesRegex(RuntimeError,'已有消息'):session.submit('测试')
        session.cancel_pending();release.set();session.job.join(2)
        event=events.get_nowait();self.assertNotEqual(event['chat_generation'],session.generation)
        fake.assert_called_once();session.close()
        with self.assertRaises(RuntimeError):session.submit('测试')

    def test_timeout_results_in_one_failure_event_without_retry(self):
        """A missing confirmation never restarts a transport or silently clears the user's draft."""
        events=queue.Queue();sender=Mock(side_effect=TimeoutError('unknown'))
        session=BattleChatSession(events,sender);session.submit('测试');session.job.join(2)
        sender.assert_called_once();self.assertFalse(events.get_nowait()['battle_chat_result']['success'])


class BattleChatTransportTests(unittest.TestCase):
    """Exercise temporary-bridge lifetime with all device/network boundaries mocked, never posting real messages."""

    def transport(self,fail=False):
        """Provide only the prepare/send/cleanup RPCs expected from a one-click bridge."""
        session=Mock();script=session.create_script.return_value
        def query(source):
            """Simulate native outcomes without interpreting or sending any message content."""
            if 'local mm=CSLTypes.ModelManager'in source:return '{"own_uin":123}'
            if '.send('in source:
                if fail:raise RuntimeError('RPC response unknown')
                return 'native_called_once'
            return 'chat_scope_removed'
        script.exports_sync.query.side_effect=query
        return session,script

    def test_success_owns_one_send_and_detaches_only_its_private_bridge(self):
        """Cleanup must not rebind or close the world helper or call a second native sender."""
        session,script=self.transport()
        with patch('battle_chat.ensure_account_available'),patch('battle_chat.subprocess.run'),\
             patch('battle_chat.subprocess.check_output',return_value='123'),\
             patch('battle_chat.frida.get_device_manager')as manager,patch('battle_chat.GameResponseLog'),\
             patch('battle_chat.wait_chat_receipt',return_value='confirmed')as wait:
            manager.return_value.add_remote_device.return_value.attach.return_value=session
            self.assertEqual(send_battle_chat_once('测试',lambda:False),'confirmed')
        sources=[call.args[0]for call in script.exports_sync.query.call_args_list]
        self.assertEqual(sum(source.startswith('return _REA_CHAT_CLICK_')and'.send('in source for source in sources),1)
        self.assertFalse(any('bindsession'in source or 'REA_AUTO_INFANTRY'in source for source in sources))
        wait.assert_called_once();script.exports_sync.bindsession.assert_not_called()
        script.exports_sync.close.assert_called_once();script.unload.assert_called_once();session.detach.assert_called_once()

    def test_rpc_error_never_retries_or_claims_safely_unsent(self):
        """After dispatch uncertainty, keep a single call and clean the bridge even if confirmation is unavailable."""
        session,script=self.transport(fail=True)
        with patch('battle_chat.ensure_account_available'),patch('battle_chat.subprocess.run'),\
             patch('battle_chat.subprocess.check_output',return_value='123'),\
             patch('battle_chat.frida.get_device_manager')as manager,patch('battle_chat.GameResponseLog'):
            manager.return_value.add_remote_device.return_value.attach.return_value=session
            with self.assertRaisesRegex(RuntimeError,'结果未确认，未重试'):
                send_battle_chat_once('测试',lambda:False)
        self.assertEqual(sum(c.args[0].startswith('return _REA_CHAT_CLICK_')and'.send('in c.args[0]for c in script.exports_sync.query.call_args_list),1)
        session.detach.assert_called_once()


class BattleChatPanelTests(unittest.TestCase):
    """Opening the tab, pressing unrelated keys and updating status do not submit messages."""

    def test_explicit_button_and_confirmation_state(self):
        """Disable duplicate clicks; clear confirmed text only; clearing account state remains passive."""
        import tkinter as tk
        root=tk.Tk();root.withdraw();callback=Mock()
        try:
            panel=BattleChatPanel(root,callback);panel.update_controls(True)
            panel.send_button.invoke();callback.assert_not_called()
            panel.message.set('测试');panel.send_button.invoke();callback.assert_called_once_with('测试')
            panel.send_button.invoke();callback.assert_called_once()
            panel.apply_result(dict(success=False,status='未确认'));self.assertEqual(panel.message.get(),'测试')
            panel.apply_result(dict(success=True,status='confirmed'));self.assertEqual(panel.message.get(),'')
            self.assertFalse(panel.entry.bind('<Return>'))
            panel.clear();self.assertIn('disabled',panel.send_button.state());callback.assert_called_once()
        finally:root.destroy()


if __name__=='__main__':unittest.main()
