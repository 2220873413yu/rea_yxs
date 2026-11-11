"""Exercise popup-free preparation, one-click authorization and receipt handling."""
from pathlib import Path
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from lupa import LuaRuntime

from guild_invite import INVITE, LOOKUP, invite_once, validate_target, wait_receipt
from guild_invite_panel import GuildInvitePanel

TARGET = '123456789012'


class GuildInvitePanelTests(unittest.TestCase):
    """Verify that one UI click authorizes exactly one invitation."""

    def test_single_invite_button_stays_disabled_until_receipt(self):
        """Click the real Tk controls and verify that double clicks cannot submit twice."""
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        session = Mock()
        panel = GuildInvitePanel(root, session)
        panel.update_controls(True)
        panel.target.set(TARGET)
        panel.invite_button.invoke()
        panel.invite_button.invoke()
        session.submit.assert_called_once_with(TARGET)
        self.assertFalse(panel.cancel_button.instate(['disabled']))
        panel.mark_sending()
        self.assertTrue(panel.cancel_button.instate(['disabled']))
        panel.invite_button.invoke()
        session.submit.assert_called_once_with(TARGET)
        panel.apply_result('游戏回执：邀请失败（42）')
        self.assertEqual(panel.status.get(), '游戏回执：邀请失败（42）')
        self.assertEqual(panel.target.get(), TARGET)
        self.assertFalse(panel.invite_button.instate(['disabled']))

    def test_already_in_guild_uses_friendly_text_for_local_and_web_invites(self):
        """Show the same known rejection to the owner regardless of where the invite started."""
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        panel = GuildInvitePanel(root, Mock())
        receipt = '游戏回执：邀请失败（6852）'
        panel.apply_result(receipt)
        self.assertEqual(panel.status.get(), '游戏回执：该玩家已加入公会')
        panel.mark_web_received(TARGET)
        panel.apply_result(receipt)
        self.assertEqual(panel.status.get(), f'网页邀请（{TARGET}）游戏回执：该玩家已加入公会')


class GuildInviteRuntimeTests(unittest.TestCase):
    """Use the actual Lua adapter with a fake game model and native handlers."""

    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute('''
Game={invites=0,lookups=0,allowed=true,position=9,stage='MainHallSceneStage',online=true,reconnecting=false}
local T_TYPE={E_GUILD_AUTH_TYPE_INVITE=5}
local start=function()return T_TYPE end
local uid={1,'test',0,1}
local main={myUserId=uid,mTLoginRsp={0}}
Game.main=main
local guild={getTGuildInfoRsp=function()return {0,{{0,'guild'}},0,Game.position}end}
local manager={getModel=function(_,t)return t=='main' and main or guild end}
CSLTypes={MainModel='main',GuildModel={HasAuthority=function(auth,pos)
 return Game.allowed and auth==5 and pos==9 end},ModelManager={sharedInstance=function()return manager end},
 LoginManager={sharedInstance=function()return Game end}}
function Game:isReplayLogining() return self.reconnecting end
TKLua={LuaGameSystem={Instance={IsConnected=function()return Game.online end}}}
CSLTypes.GuildInviteDialog={ShowDialog=function()error('Invite popup must not open')end,
 __instanceDict={
 OnPlayerIdInputChanged=function(input)
  Game.lookupTarget=input.mPlayerIdInput.text;Game.lookups=Game.lookups+1
 end,
 OnInviteClick=function(input)
  Game.inviteTarget=input.mPlayerIdInput.text;Game.invites=Game.invites+1
 end}}
CSLTypes.GuildMemberDialog={__instanceDict={Start=start,getCurrentStageName=function()return Game.stage end}}
''')
        source = Path(__file__).with_name('guild_invite_runtime.lua').read_text(encoding='utf-8')
        self.lua.execute(source.replace('__GUILD_INVITE_API__', 'Invite'))

    def test_prepare_without_popup_and_confirm_original_id_once(self):
        """The lobby is ready without a member dialog and can submit the prepared ID once."""
        self.assertEqual(self.lua.eval('Invite.ready()'), 'ready')
        self.assertEqual(self.lua.eval(f'Invite.prepare("{TARGET}")'), 'prepared')
        self.assertEqual(self.lua.eval('Game.lookups'), 1)
        self.assertEqual(self.lua.eval('Game.invites'), 0)
        with self.assertRaisesRegex(Exception, '玩家 ID 无效'):
            self.lua.eval('Invite.prepare("234567890123")')
        self.assertEqual(self.lua.eval('Invite.confirm()'), 'submitted')
        self.assertTrue(self.lua.eval('Invite.confirm()').startswith('not_sent:'))
        self.assertEqual(self.lua.eval('Game.invites'), 1)
        self.assertEqual(self.lua.eval('Game.lookupTarget'), TARGET)
        self.assertEqual(self.lua.eval('Game.inviteTarget'), TARGET)

    def test_disconnect_reconnect_login_or_revoked_permission_stops_before_native_invite(self):
        """Each condition disables both initial readiness and an already-prepared invitation."""
        self.lua.eval(f'Invite.prepare("{TARGET}")')
        for state in ('Game.online=false', 'Game.reconnecting=true',
                      "Game.stage='LoginStage'", 'Game.allowed=false'):
            with self.subTest(state=state):
                self.lua.execute("Game.online=true;Game.reconnecting=false;Game.stage='MainHallSceneStage';Game.allowed=true")
                self.lua.execute(state)
                with self.assertRaises(Exception):
                    self.lua.eval('Invite.ready()')
                self.assertTrue(self.lua.eval('Invite.confirm()').startswith('not_sent:'))
                self.assertEqual(self.lua.eval('Game.invites'), 0)

    def test_web_scope_must_still_match_at_submission(self):
        """Replacing the game login invalidates a claimed invite without opening a dialog."""
        self.lua.execute('_REA_GUILD_INVITE_deadbeef=Invite')
        source = Path(__file__).with_name('guild_invite_runtime.lua').read_text(encoding='utf-8')
        self.lua.execute(source.replace('__GUILD_INVITE_API__', 'WebInvite')
                         .replace('__GUILD_INVITE_SCOPE__', '_REA_GUILD_INVITE_deadbeef'))
        self.assertEqual(self.lua.eval('WebInvite.ready()'), 'ready')
        self.lua.execute(f'WebInvite.prepare("{TARGET}");Game.main.mTLoginRsp={{0}}')
        self.assertTrue(self.lua.eval('WebInvite.confirm()').startswith('not_sent:'))
        self.assertEqual(self.lua.eval('Game.invites'), 0)


class InviteReceiptTests(unittest.TestCase):
    """Match the same target on each phase and preserve the actual invite return code."""

    def test_preview_rejection_and_invite_success_are_distinct(self):
        """A nonzero preview result is separate from the later invitation result."""
        request = b'\x03' + int(TARGET).to_bytes(8, 'big')
        log = Mock()
        log.drain.return_value = [{'tag': 's_1421_1', 'body': request}, {'tag': 'r_1421_2', 'body': b'\x01\x1a\xd5'}]
        self.assertEqual(wait_receipt(log, LOOKUP, TARGET, threading.Event()), 6869)
        log.drain.return_value = [{'tag': 's_1415_3', 'body': request}, {'tag': 'r_1415_4', 'body': b'\x0c'}]
        self.assertEqual(wait_receipt(log, INVITE, TARGET, threading.Event()), 0)
        log.drain.return_value.insert(1, {'tag': 's_1415_5', 'body': request})
        with self.assertRaisesRegex(RuntimeError, '其他请求'):
            wait_receipt(log, INVITE, TARGET, threading.Event())

    def test_one_click_looks_up_then_invites_without_waiting_for_another_click(self):
        """Run the real orchestration with simulated lookup success, failure or cancellation."""
        for outcome in ('success', 'cancelled', 'timeout'):
            with self.subTest(outcome=outcome):
                cancel = threading.Event()
                script = Mock()
                query = script.exports_sync.query
                def is_click(source):
                    """Distinguish invoking the callback from installing its Lua definition."""
                    return source.startswith('return _REA_GUILD_INVITE_') and source.endswith('.confirm()')
                query.side_effect = lambda source: ('submitted' if is_click(source) else
                                                   'prepared' if source.startswith('return ') and '.prepare(' in source else 'ok')
                def begin_submission():
                    """Verify that lookup finished before the native invite handler can run."""
                    self.assertFalse(any(is_click(call.args[0]) for call in query.call_args_list))
                    self.assertEqual(receipt.call_args.args[1], LOOKUP)
                def wait_reply(log, code, target, event):
                    """Simulate a cancellation or a missing lookup response before submission."""
                    if code == LOOKUP and outcome == 'cancelled':
                        event.set()
                    if code == LOOKUP and outcome == 'timeout':
                        raise TimeoutError('测试查询超时')
                    return 0
                with patch('guild_invite.ensure_account_available'), patch('guild_invite.subprocess.run'), \
                     patch('guild_invite.Connection.read_process_identity', return_value=(1, 'boot', 2)), \
                     patch('guild_invite.frida.get_device_manager') as manager, \
                     patch('guild_invite.GameResponseLog') as log, patch('guild_invite.wait_receipt', side_effect=wait_reply) as receipt:
                    session = manager.return_value.add_remote_device.return_value.attach.return_value
                    session.create_script.return_value = script
                    log.return_value.drain.return_value = []
                    if outcome != 'success':
                        with self.assertRaisesRegex(RuntimeError, '未发送邀请'):
                            invite_once(TARGET, cancel, begin_submission)
                    else:
                        self.assertEqual(invite_once(TARGET, cancel, begin_submission), '游戏回执：邀请成功')
                    count = sum(is_click(call.args[0]) for call in query.call_args_list)
                    self.assertEqual(count, 1 if outcome == 'success' else 0)
                    self.assertEqual([call.args[1] for call in receipt.call_args_list],
                                     [LOOKUP, INVITE] if outcome == 'success' else [LOOKUP])

    def test_validation_preserves_decimal_text_and_rejects_invalid_length(self):
        """Accept a formatted ID as a single target and reject lists or invalid input."""
        self.assertEqual(validate_target('0001 2345 6789'), '000123456789')
        for value in ('123', '000000000000', '123456789012\n123456789012'):
            with self.assertRaises(ValueError):
                validate_target(value)

    def test_web_invite_uses_the_relay_bridge_for_all_native_steps(self):
        """A web claim must never attach a second bridge while the relay is active."""
        query = Mock(side_effect=['guild_invite_ready', 'prepared', 'submitted', 'same', 'closed'])
        parent = '_REA_GUILD_INVITE_deadbeef'
        with patch('guild_invite.native_invite_scope') as attach, \
             patch('guild_invite.GameResponseLog') as log, patch('guild_invite.wait_receipt', return_value=0):
            log.return_value.drain.return_value = []
            result = invite_once(TARGET, threading.Event(), Mock(), relay_scope=(query, parent))
        attach.assert_not_called()
        self.assertEqual(result, '游戏回执：邀请成功')
        calls = [call.args[0] for call in query.call_args_list]
        self.assertIn(parent, calls[0])
        self.assertEqual(sum(source.endswith('.confirm()') for source in calls), 1)
