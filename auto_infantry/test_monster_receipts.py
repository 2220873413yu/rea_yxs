"""Verify actual JCE departure/quick-combat attribution and revocable hunting transport gates."""
import unittest
from unittest.mock import Mock

from connection import Connection
from game_log import GameResponseLog,HuntRejected
from test_collection_receipts import request,response


def hunt_request(hero=303,target=2792):
    """Change only the ordinary collection aim to the verified ordinary monster aim3."""
    return request(hero,target).replace(bytes.fromhex('190c0b100131'),bytes.fromhex('190c0b100331'))


def hunt_response(hero=303,target=2792,ret=0):
    """Build a normal accepted army packet, or a definite refusal without an army payload."""
    return response(hero,target,ret).replace(bytes.fromhex('500161'),bytes.fromhex('500361'))


def skip_request(army=123,target=2792):
    """Encode the verified target, army, aim3 and native quick-combat flag tags."""
    return bytes([1])+target.to_bytes(2,'big')+bytes([0x10,army,0x20,3,0x40,1])


def skip_response(army=123,target=2792,won=True,ret=0):
    """Encode the native completed/won tags7/8, keeping unrelated reward/user payloads out."""
    if ret:return bytes([1])+ret.to_bytes(2,'big')
    return bytes([0x0c,0x11])+target.to_bytes(2,'big')+bytes([0x20,army,0x30,3,0x70,1,0x80,int(won)])


class MonsterReceiptTests(unittest.TestCase):
    """Accept only one matching request/reply; foreign traffic and ambiguity never permit a retry."""

    def log(self, protocol, sent, received):
        """Exercise production binary parsing over a fake two-record log stream."""
        log=GameResponseLog.__new__(GameResponseLog)
        log.drain=Mock(return_value=[{'tag':f's_{protocol}_1','body':sent},{'tag':f'r_{protocol}_2','body':received}])
        return log

    def test_hunt_matches_hero_target_and_ordinary_aim(self):
        """A successful hunt receipt binds exactly the requested hero and target to its new army."""
        self.assertEqual(self.log(11010,hunt_request(),hunt_response()).wait_hunt(303,2792)['army_id'],123)
        for sent,received in ((request(),hunt_response()),(hunt_request(),response()),
                              (hunt_request(hero=305),hunt_response()),(hunt_request(),hunt_response(target=2793))):
            with self.subTest(sent=sent,received=received),self.assertRaises(RuntimeError):
                self.log(11010,sent,received).wait_hunt(303,2792)
        with self.assertRaises(HuntRejected) as caught:
            self.log(11010,hunt_request(),hunt_response(ret=6109)).wait_hunt(303,2792)
        self.assertEqual(caught.exception.ret,6109)

    def test_skip_attributes_completion_and_defeat_without_claiming_victory(self):
        """Completed server defeat remains defeat, and another army/target cannot satisfy our skip."""
        for won in (True,False):
            r=self.log(11006,skip_request(),skip_response(won=won)).wait_hunt_skip(123,2792)
            self.assertEqual(r['won'],won)
        for sent,received in ((skip_request(army=124),skip_response()),(skip_request(),skip_response(target=2793)),
                              (skip_request(),skip_response(army=124))):
            with self.subTest(sent=sent,received=received),self.assertRaises(RuntimeError):
                self.log(11006,sent,received).wait_hunt_skip(123,2792)

    def test_uncertainty_never_resubmits(self):
        """Neither departure nor skip has an automatic spending retry path after a missing response."""
        log=GameResponseLog.__new__(GameResponseLog);log.drain=Mock()
        with self.assertRaises(TimeoutError):log.wait_hunt(303,2792,timeout=0)
        with self.assertRaises(TimeoutError):log.wait_hunt_skip(123,2792,timeout=0)
        log.drain.assert_not_called()

    def test_transport_spending_categories_are_separate_from_collection(self):
        """Departures and skips both carry hunting generation; reads cannot smuggle Lua or string parameters."""
        c=Connection();c.script=Mock();c.script.exports_sync.query.return_value='sent'
        for op in ('hunt_dispatch','hunt_skip'):
            c.hunt_call(op,(1,303),generation=8,hero_id=303)
            self.assertEqual(c.script.exports_sync.query.call_args.args[1:],('hunt',303,8))
        with self.assertRaises(ValueError):c.hunt_call('hunt_query',('1);evil()',))
        with self.assertRaises(ValueError):c.hunt_call('unknown')

    def test_expired_preflight_refreshes_once_without_changing_the_spending_gate(self):
        """Only known pre-send guards permit one fresh read and another guarded local attempt."""
        for operation, guard, result in (
                ('hunt_schedule', 'Fresh own-army response required', '{}'),
                ('hunt_skip', 'Fresh busy hero required', 'hunt_skip_submitted')):
            with self.subTest(operation=operation):
                c=Connection();c.script=Mock();c.refresh_heroes=Mock()
                c.script.exports_sync.query.side_effect=[RuntimeError('rea-auto-infantry:401: '+guard),result]
                c.hunt_call(operation,(1,303,10),generation=8,hero_id=303)
                c.refresh_heroes.assert_called_once_with()
                calls=c.script.exports_sync.query.call_args_list
                self.assertEqual(len(calls),2)
                self.assertEqual(calls[0],calls[1])

    def test_failed_refresh_or_second_stale_guard_stops_without_unbounded_retry(self):
        """Persistent staleness and refresh failures terminate the original event-triggered check."""
        c=Connection();c.script=Mock();c.refresh_heroes=Mock()
        c.script.exports_sync.query.side_effect=RuntimeError('Fresh busy hero required')
        with self.assertRaises(RuntimeError):c.hunt_call('hunt_skip',(1,303,10),8,303)
        self.assertEqual(c.script.exports_sync.query.call_count,2)
        c.refresh_heroes.assert_called_once_with()
        c.script.exports_sync.query.reset_mock()
        c.refresh_heroes.side_effect=TimeoutError('refresh timed out')
        with self.assertRaises(TimeoutError):c.hunt_call('hunt_skip',(1,303,10),8,303)
        self.assertEqual(c.script.exports_sync.query.call_count,1)

    def test_uncertain_transport_and_other_guards_never_trigger_a_second_attempt(self):
        """A timeout, already-submitted skip or wrong army must never be treated as pre-send staleness."""
        for operation, error in (
                ('hunt_skip',TimeoutError('RPC timed out')),
                ('hunt_skip',RuntimeError('Quick combat was already submitted; do not retry')),
                ('hunt_skip',RuntimeError('Hunt army is not waiting at its target')),
                ('hunt_dispatch',RuntimeError('Fresh busy hero required'))):
            with self.subTest(operation=operation,error=str(error)):
                c=Connection();c.script=Mock();c.refresh_heroes=Mock()
                c.script.exports_sync.query.side_effect=error
                with self.assertRaises(type(error)):c.hunt_call(operation,(1,303,10),8,303)
                c.script.exports_sync.query.assert_called_once()
                c.refresh_heroes.assert_not_called()

    def test_target_check_refreshes_expired_own_state_but_not_real_busy_heroes(self):
        """New monster replies cannot turn expired own-state eligibility into an indefinite busy wait."""
        ready={'own_state_fresh':True,'target':{'fresh':True},'formations':[]}
        stale={**ready,'own_state_fresh':False}
        c=Connection();c.refresh_heroes=Mock()
        c._query_monster_once=Mock(side_effect=[stale,ready])
        self.assertIs(c.query_monster(2792),ready)
        c.refresh_heroes.assert_called_once_with()
        self.assertEqual(c._query_monster_once.call_count,2)
        c.refresh_heroes.reset_mock()
        c._query_monster_once=Mock(return_value=ready)
        self.assertIs(c.query_monster(2792),ready)
        c._query_monster_once.assert_called_once_with(2792,6)
        c.refresh_heroes.assert_not_called()

    def test_target_check_has_a_bounded_freshness_recheck_without_spending(self):
        """Slow target/hero reads get at most two query rounds, with no dispatch or timed polling fallback."""
        for own_fresh in (False,True):
            with self.subTest(own_fresh=own_fresh):
                c=Connection();c.refresh_heroes=Mock();c.hunt_call=Mock()
                c._query_monster_once=Mock(return_value={
                    'own_state_fresh':own_fresh,'target':{'fresh':False},'formations':[]})
                with self.assertRaisesRegex(RuntimeError,'持续过期'):c.query_monster(2792)
                self.assertEqual(c._query_monster_once.call_count,2)
                self.assertEqual(c.refresh_heroes.call_count,0 if own_fresh else 1)
                c.hunt_call.assert_not_called()


if __name__=='__main__':unittest.main()
