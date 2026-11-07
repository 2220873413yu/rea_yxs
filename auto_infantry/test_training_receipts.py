"""Verify native-cache-independent training receipts using actual tagged packet decoding."""
import unittest
from unittest.mock import Mock
from game_log import GameResponseLog, TrainingRejected


class TrainingReceiptTests(unittest.TestCase):
    """Include the observed6015 packet whose response soldier identifier is zero."""

    def log(self, ret=0, unit=411, sent_unit=411):
        """Replace stream IO while preserving production request/response matching."""
        log = GameResponseLog.__new__(GameResponseLog)
        reply = bytes([1])+ret.to_bytes(2,'big')+bytes.fromhex('1c') if ret else bytes.fromhex('0c11')+unit.to_bytes(2,'big')
        log.drain=Mock(return_value=[{'tag':'s_11029_1','body':bytes([1])+sent_unit.to_bytes(2,'big')},
                                    {'tag':'r_11029_2','body':reply}])
        return log

    def test_observed_rejection_is_not_misreported_as_timeout(self):
        """6015 is an immediate attributed rejection even though its soldier field is zero."""
        with self.assertRaises(TrainingRejected) as raised:
            self.log(6015).wait_training(411)
        self.assertEqual((raised.exception.unit,raised.exception.ret),(411,6015))

    def test_success_and_foreign_response(self):
        """Only the matching troop's zero-return response may continue to native-state confirmation."""
        self.assertEqual(self.log().wait_training(411)['soldier_id'],411)
        with self.assertRaisesRegex(RuntimeError,'响应兵种'):
            self.log(unit=412).wait_training(411)

    def test_unknown_result_is_never_retried(self):
        """A timeout has no resend path and remains a conservative stop."""
        log=self.log()
        with self.assertRaises(TimeoutError):
            log.wait_training(411,timeout=0)
        log.drain.assert_not_called()

    def test_scout_response_requires_the_same803_identifier(self):
        """A native803 training receipt is accepted only for a scout request, never infantry."""
        self.assertEqual(self.log(unit=803,sent_unit=803).wait_training(803)['soldier_id'],803)
        with self.assertRaises(RuntimeError):
            self.log(unit=803).wait_training(411)
