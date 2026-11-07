"""Validate the exact wire evidence required before removing any resource-list entry."""
import unittest
from unittest.mock import Mock
from game_log import GameResponseLog,ResourceMissing


class ResourceMissingReceiptTests(unittest.TestCase):
    """Keep6001 distinct from view restrictions, foreign queries and uncertain responses."""

    def log(self,ret=0,target=2792,response_target=2792):
        """Exercise actual tagged decoding with a substituted packet stream."""
        log=GameResponseLog.__new__(GameResponseLog)
        response=(bytes([1])+ret.to_bytes(2,'big')) if ret else bytes.fromhex('0c1a0a0a11')+response_target.to_bytes(2,'big')+bytes.fromhex('0b0b0b')
        log.drain=Mock(return_value=[{'tag':'s_11020_1','body':bytes([1])+target.to_bytes(2,'big')},
                                    {'tag':'r_11020_2','body':response}])
        return log

    def test_only_matched6001_is_a_confirmed_missing_resource(self):
        """The exception retains the requested resource ID even when the native error body has no ID."""
        with self.assertRaises(ResourceMissing) as raised:
            self.log(6001).wait_resource_detail(2792)
        self.assertEqual(raised.exception.target_id,2792)
        self.log().wait_resource_detail(2792)

    def test_other_errors_and_ambiguous_identity_never_authorize_deletion(self):
        """Not-in-view6109 and generic errors must not be confused with a missing resource field."""
        for log in (self.log(6109),self.log(6002),self.log(6003),self.log(6001,target=2793),self.log(response_target=2793)):
            with self.subTest(log=log),self.assertRaises(RuntimeError) as raised:
                log.wait_resource_detail(2792)
            self.assertNotIsInstance(raised.exception,ResourceMissing)

    def test_timeout_never_authorizes_deletion(self):
        """A request without an attributable response is unknown, not proof of disappearance."""
        with self.assertRaises(TimeoutError):
            self.log().wait_resource_detail(2792,timeout=0)
