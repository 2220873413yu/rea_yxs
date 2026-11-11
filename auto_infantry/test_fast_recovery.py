"""Exercise bounded burst scheduling and real packet attribution without an emulator or item spending."""
import unittest
from unittest.mock import Mock,patch

from fast_recovery import FastRecovery,RecoveryReceipts,burst_size,verify_batch
from test_hero_recovery import hero_state as base_hero_state,RecoveryWorkerTests


def hero_state(**changes):
    """Use a sixteen-minute default so three complete cooldown slices can be safely batched."""
    return base_hero_state(**{'finish_ms':1300000,'remaining_ms':960000,**changes})


def integer(tag,value):
    """Encode just the signed JCE integer fields used by the native recovery request and response."""
    if value==0:return bytes([tag*16+12])
    size=1 if -128<=value<=127 else 2 if -32768<=value<=32767 else 4
    return bytes([tag*16+{1:0,2:1,4:2}[size]])+value.to_bytes(size,'big',signed=True)


def packets(count=1,hero=303,ret=0,quantity=1):
    """Create attributed protocol186 requests and replies with the exact recovery item list."""
    req=integer(1,3)+integer(2,500)+integer(3,hero)+bytes.fromhex('4900010a')+integer(0,70291)+integer(1,quantity)+b'\x0b'
    rsp=integer(0,ret)+integer(1,3)+integer(2,500)+integer(3,hero)
    return [dict(tag=f'{direction}_186_{i}',body=body) for i in range(count) for direction,body in (('s',req),('r',rsp))]


class FastRecoveryTests(unittest.TestCase):
    """Preserve a single shared budget and stop latch across batches, cancellation and uncertainty."""

    def setup_transport(self,count=3):
        """Provide a synthetic monotonic clock and defer all wire receipts until after the sends."""
        now=[100.0];sent=[];connection=Mock();log=Mock()
        def step(*args,**kwargs):
            sent.append(now[0]);return {'sent':True}
        connection.hero_call.side_effect=step
        connection.refresh_hero.return_value=hero_state(items=30-count,finish_ms=1300000-count*300000,
                                                        remaining_ms=max(0,960000-count*300000))
        def drain():
            if not sent:return []
            return packets(len(sent))
        log.drain.side_effect=drain
        self.enterContext(patch('fast_recovery.time.monotonic',side_effect=lambda:now[0]))
        self.enterContext(patch('fast_recovery.time.sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)))
        return FastRecovery(),connection,log,now,sent

    def test_burst_cap_stock_remainder_and_native_response_matching(self):
        """Never schedule more five-minute slices than the hero needs or the account owns."""
        self.assertEqual(burst_size(hero_state()),3)
        self.assertEqual(burst_size(hero_state(remaining_ms=300001)),1)
        self.assertEqual(burst_size(hero_state(remaining_ms=600001)),2)
        self.assertEqual(burst_size(hero_state(remaining_ms=1000)),1)
        self.assertEqual(burst_size(hero_state(items=2)),2)
        self.assertEqual(burst_size(hero_state(busy=True)),0)
        ledger=RecoveryReceipts(303);ledger.accept(packets(3))
        self.assertEqual((ledger.sent,ledger.received),(3,3))
        for changed in ({'hero':304},{'quantity':2},{'ret':6012}):
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):
                RecoveryReceipts(303).accept(packets(**changed))

    def test_send_three_before_receipts_then_verify_once(self):
        """All three native sends precede the first receipt drain; no per-item state refresh is hidden inside."""
        fast,c,log,now,sent=self.setup_transport()
        result=fast.recover(c,hero_state(),7,lambda:False,log)
        self.assertEqual(len(sent),3)
        self.assertGreaterEqual(sent[1]-sent[0],.334-1e-9)
        self.assertLess(sent[-1]-sent[0],1)
        self.assertEqual(result['recovery_count'],3)
        self.assertEqual(log.drain.call_count,2)
        c.refresh_hero.assert_called_once_with(hero_id=303)
        self.assertFalse(fast.uncertain)

    def test_rate_limit_survives_batch_boundaries(self):
        """Four sends cannot fit in a rolling one-second window even when each verified batch has one item."""
        fast,c,log,now,sent=self.setup_transport(count=1)
        for _ in range(4):
            log.drain.side_effect=[[],packets()]
            fast.recover(c,hero_state(remaining_ms=1000),7,lambda:False,log)
        self.assertGreater(sent[-1]-sent[0],1)

    def test_cancel_stops_future_sends_but_settles_already_sent_item(self):
        """Turning off after one send does not abandon its result or consume the two remaining planned items."""
        fast,c,log,now,sent=self.setup_transport(count=1)
        result=fast.recover(c,hero_state(),7,lambda:len(sent)>=1,log)
        self.assertEqual(len(sent),1)
        self.assertEqual(result['recovery_count'],1)
        self.assertFalse(fast.uncertain)

    def test_missing_receipt_and_bad_inventory_latch_without_retry(self):
        """Neither a late/missing reply nor an inconsistent authoritative snapshot authorizes another burst."""
        for missing in (True,False):
            with self.subTest(missing=missing):
                fast,c,log,now,sent=self.setup_transport()
                if missing:log.drain.return_value=[];log.drain.side_effect=None
                else:c.refresh_hero.return_value=hero_state(items=29)
                with self.assertRaises((TimeoutError,RuntimeError)):
                    fast.recover(c,hero_state(),7,lambda:False,log,timeout=0)
                self.assertTrue(fast.uncertain)
                with self.assertRaises(RuntimeError):fast.recover(c,hero_state(),7,lambda:False,log)
                self.assertEqual(len(sent),3)

    def test_early_native_completion_stops_remaining_steps(self):
        """A native completed response ends a precomputed three-item batch and settles only what was sent."""
        fast,c,log,now,sent=self.setup_transport(count=1)
        def step(*args,**kwargs):
            if sent:return {'sent':False,'reason':'complete'}
            sent.append(now[0]);return {'sent':True}
        c.hero_call.side_effect=step
        result=fast.recover(c,hero_state(),7,lambda:False,log)
        self.assertEqual(result['recovery_count'],1)
        self.assertEqual(c.hero_call.call_count,2)

    def test_bridge_timeout_never_resends_a_possibly_submitted_step(self):
        """Latch before the RPC, not after its return, because a timeout may follow a successful native send."""
        fast,c,log,now,sent=self.setup_transport()
        c.hero_call.side_effect=TimeoutError('bridge return missing')
        with self.assertRaises(TimeoutError):fast.recover(c,hero_state(),7,lambda:False,log)
        self.assertTrue(fast.uncertain)
        with self.assertRaises(RuntimeError):fast.recover(c,hero_state(),7,lambda:False,log)
        c.hero_call.assert_called_once()

    def test_aggregate_verification_rejects_clock_only_and_busy_state(self):
        """Every accepted batch needs item deduction and real cooldown advancement, not passage of time alone."""
        for after in (hero_state(items=27),hero_state(items=27,finish_ms=100000,busy=True),
                      hero_state(items=28,finish_ms=100000)):
            with self.assertRaises(RuntimeError):verify_batch(hero_state(),after,3)


class FastWorkerTests(RecoveryWorkerTests):
    """Run the actual shared worker selection, gate and exception paths in fast mode."""

    def test_fast_mode_shared_selection_and_uncertain_restart_block(self):
        """A failed fast batch closes recovery/collection and cannot be revived by changing mode or the switch."""
        worker,c=self.make_worker()
        worker.set_recovery_mode('fast');worker.switch_hero(True,(303,))
        c.refresh_hero.return_value=hero_state()
        c.recover_hero_fast.side_effect=TimeoutError('uncertain burst')
        worker.hero_tick(c)
        self.assertFalse(worker.hero_enabled)
        self.assertTrue(worker.hero_uncertain)
        c.recover_hero.assert_not_called()
        with self.assertRaises(RuntimeError):worker.switch_hero(True,(303,))
        with self.assertRaises(RuntimeError):worker.set_recovery_mode('normal')
        worker.hero_tick(c);c.recover_hero_fast.assert_called_once()

    def test_mode_is_default_normal_and_frozen_while_active(self):
        """UI mode changes cannot affect a live burst or secretly change normal-mode startup behavior."""
        worker,c=self.make_worker()
        self.assertEqual(worker.recovery_mode,'normal')
        worker.switch_hero(True,(303,))
        with self.assertRaises(RuntimeError):worker.set_recovery_mode('fast')
        worker.switch_hero(False)
        worker.set_recovery_mode('fast')
        self.assertEqual(worker.recovery_mode,'fast')
