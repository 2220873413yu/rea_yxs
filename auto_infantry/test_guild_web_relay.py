"""Verify the handoff, lease and result without contacting the game."""
import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

from guild_invite import GuildInviteSession
from guild_web_relay import GuildWebRelay, WebInvite, public_receipt


class GuildWebRelayTests(unittest.TestCase):
    def test_expired_lease_cannot_submit(self):
        """A late native readiness check cannot issue an expired invite."""
        native_send = Mock()

        def send(target, cancel, begin_submission, relay_scope):
            """Model the native sender's checked call boundary."""
            begin_submission()
            native_send(target)

        session = GuildInviteSession(queue.Queue(), send)
        web = WebInvite((Mock(), 'scope'), threading.Event(), time.monotonic() - 1, queue.Queue())
        session.submit('123456789012', web=web)
        self.assertEqual(web.reply.get(timeout=1), '网页请求已失效')
        native_send.assert_not_called()
        session.close()

    def test_claim_hands_off_once_and_returns_real_result(self):
        """A failed web receipt upload never causes another native submission."""
        session = Mock()
        scope = (Mock(), 'scope')

        def reply(target, web):
            """Send a synthetic game receipt from the claimed scope."""
            self.assertEqual(web.scope, scope)
            web.reply.put('游戏回执：邀请失败（321）')

        session.submit.side_effect = reply
        relay = GuildWebRelay(session, queue.Queue())
        with patch('guild_web_relay.connector_request', side_effect=TimeoutError) as request:
            relay._process('key', 'client', {'target': '123456789012', 'id': 'claim'},
                           time.monotonic(), scope, threading.Event())
        session.submit.assert_called_once()
        request.assert_called_once_with('key', 'result', 'client', id='claim', state='failed', code=321)
        self.assertEqual(public_receipt('邀请结果未确认，未重试：超时'), {'state': 'unknown'})
