"""Verify exact rescue wire receipts and the independent stop gate with real JCE parsing."""
import unittest
from unittest.mock import Mock

from connection import Connection
from game_log import GameResponseLog,BeaconRejected,BeaconCapacityUnavailable
from test_collection_receipts import request, response
from test_monster_receipts import skip_request,skip_response


def rescue_request(hero=303,target=2792):
    """Encode aim45 in the normal native departure request."""
    return request(hero,target).replace(bytes.fromhex('190c0b100131'),bytes.fromhex('190c0b102d31'))


def rescue_response(hero=303,target=2792,ret=0):
    """Encode the accepted hero, beacon aim, target and server marching deadline."""
    return response(hero,target,ret).replace(bytes.fromhex('500161'),bytes.fromhex('4002502d61')).replace(
        bytes.fromhex('fa0f01'),bytes.fromhex('b2000186a0fa0f01'))


class BeaconReceiptTests(unittest.TestCase):
    """Neither unrelated traffic nor an unknown outcome may authorize an automatic retry."""

    def log(self,code,sent,received):
        """Substitute the binary stream while preserving production decoding and attribution."""
        log=GameResponseLog.__new__(GameResponseLog)
        log.drain=Mock(return_value=[dict(tag=f's_{code}_1',body=sent),dict(tag=f'r_{code}_2',body=received)])
        return log

    def test_exact_departure_receipt_and_foreign_refused_responses(self):
        """Require the same hero, aim45 and event on both sides of a successful departure."""
        result=self.log(11010,rescue_request(),rescue_response()).wait_beacon('dispatch',2792,303)
        self.assertEqual((result['army_id'],result['state'],result['end_ms']),(123,2,100000))
        for sent,received in ((request(),rescue_response()),(rescue_request(),response()),
                              (rescue_request(),rescue_response(hero=304)),
                              (rescue_request(),rescue_response(target=2793)),
                              (rescue_request(),rescue_response(ret=6012))):
            with self.subTest(sent=sent),self.assertRaises(RuntimeError):
                self.log(11010,sent,received).wait_beacon('dispatch',2792,303)

    def test_only_exact_sent_request_can_produce_capacity_rejection(self):
        """The recoverable6395 signal must originate from the matched wire request, not an unrelated response."""
        with self.assertRaises(BeaconRejected) as caught:
            self.log(11010,rescue_request(),rescue_response(ret=6395)).wait_beacon('dispatch',2792,303)
        self.assertEqual((caught.exception.ret,caught.exception.operation,caught.exception.event_id),(6395,'dispatch',2792))
        with self.assertRaises(RuntimeError) as foreign:
            self.log(11010,rescue_request(hero=304),rescue_response(ret=6395)).wait_beacon('dispatch',2792,303)
        self.assertNotIsInstance(foreign.exception,BeaconRejected)

    def test_explicit_local_capacity_full_does_not_wait_for_an_unsent_response(self):
        """The final native capacity guard reports no send, so the transport must not wait or retry."""
        c=Connection();c.response_log=Mock()
        c.beacon_call=Mock(return_value=dict(not_sent=True,reason='capacity_full',event_id=2792))
        with self.assertRaises(BeaconCapacityUnavailable):c.beacon_action('dispatch',2792,8,303)
        c.response_log.wait_beacon.assert_not_called()
        c.beacon_call.assert_called_once_with('beacon_dispatch',(2792,303),8,303)

    def test_recall_and_claim_require_exact_identifiers(self):
        """A completed rescue reward uses event identity, while retreat uses owned army identity."""
        sent=bytes.fromhex('01007b');received=bytes.fromhex('0c11007b')
        self.assertEqual(self.log(11008,sent,received).wait_beacon('recall',2792,303,123)['army_id'],123)
        with self.assertRaises(RuntimeError):
            self.log(11008,sent,bytes.fromhex('0c11007c')).wait_beacon('recall',2792,303,123)
        sent=bytes.fromhex('010ae8')
        received=bytes.fromhex('0c1a0a110ae80b0b2a590cf9120c0b')
        result=self.log(11043,sent,received).wait_beacon('claim',2792)
        self.assertEqual((result['items'],result['resources']),([],[]))
        with self.assertRaises(RuntimeError):
            self.log(11043,sent,received.replace(bytes.fromhex('110ae8'),bytes.fromhex('110ae9'))).wait_beacon('claim',2792)

    def test_timeout_never_resends_and_transport_has_its_own_epoch(self):
        """Only explicit action operations use the beacon gate; elapsed deadlines never resend."""
        log=GameResponseLog.__new__(GameResponseLog);log.drain=Mock()
        with self.assertRaises(TimeoutError):log.wait_beacon('claim',2792,timeout=0)
        log.drain.assert_not_called()
        c=Connection();c.script=Mock();c.script.exports_sync.query.return_value='{}'
        c.beacon_call('beacon_dispatch',(2792,303),8,303)
        self.assertEqual(c.script.exports_sync.query.call_args.args[1:],('beacon',303,8))
        with self.assertRaises(ValueError):c.beacon_call('beacon_dispatch',('1);evil()',))
        c.response_log=Mock();c.response_log.wait_beacon.side_effect=TimeoutError('unknown')
        c.beacon_call=Mock()
        with self.assertRaises(TimeoutError):c.beacon_action('dispatch',2792,8,303)
        c.beacon_call.assert_called_once_with('beacon_dispatch',(2792,303),8,303)

    def test_beacon_skip_must_match_aim45_not_ordinary_hunting(self):
        """The same11006 protocol cannot attribute ordinary aim3 combat to a beacon event."""
        sent=skip_request().replace(bytes.fromhex('2003'),bytes.fromhex('202d'))
        received=skip_response().replace(bytes.fromhex('3003'),bytes.fromhex('302d'))
        result=self.log(11006,sent,received).wait_hunt_skip(123,2792,expected_aim=45)
        self.assertTrue(result['won'])
        for a,b in ((skip_request(),received),(sent,skip_response())):
            with self.assertRaises(RuntimeError):self.log(11006,a,b).wait_hunt_skip(123,2792,expected_aim=45)

    def test_scout_receipt_requires_matching_destination_and_returned_path(self):
        """Scout acceptance supplies a journey deadline, never event completion or a reward claim."""
        # Destination(86,181), with a single-position native path ending at that destination.
        sent=bytes.fromhex('1a00561100b50b')
        received=bytes.fromhex('0c1a0c1107d02900010a00561100b50b0b')
        result=self.log(11014,sent,received).wait_beacon_scout(86,181)
        self.assertEqual(result['end_ms'],2000)
        # Replay the magnitude observed in the real receipt; it is already an epoch millisecond value.
        epoch=1794278362771
        live=bytes.fromhex('0c1a0c13')+epoch.to_bytes(8,'big')+bytes.fromhex('2900010a00561100b50b0b')
        self.assertEqual(self.log(11014,sent,live).wait_beacon_scout(86,181)['end_ms'],epoch)
        for a,b in ((sent.replace(bytes.fromhex('0056'),bytes.fromhex('0057')),received),
                    (sent,received.replace(bytes.fromhex('0056'),bytes.fromhex('0057')))):
            with self.assertRaises(RuntimeError):self.log(11014,a,b).wait_beacon_scout(86,181)

    def test_monster_detail_precedes_availability_and_cancel_prevents_selection(self):
        """Connection prepares the correct quest once before requesting the hero list, with no retries."""
        c=Connection();c.beacon_call=Mock();c._wait_beacon_read=Mock(return_value={'ready':True})
        c.query_beacon_candidates(2792,8)
        self.assertEqual([call.args[0] for call in c.beacon_call.call_args_list],
                         ['beacon_target_query','beacon_candidates_query'])
        self.assertEqual([call.args[0] for call in c._wait_beacon_read.call_args_list],
                         ['beacon_target_result','beacon_candidates_result'])
        c.beacon_call.reset_mock();c._wait_beacon_read.side_effect=TimeoutError('detail timeout')
        with self.assertRaises(TimeoutError):c.query_beacon_candidates(2792,8)
        self.assertEqual([call.args[0] for call in c.beacon_call.call_args_list],
                         ['beacon_target_query','beacon_cancel_query'])


if __name__=='__main__':unittest.main()
