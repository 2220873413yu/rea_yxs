"""Deterministic two-hour scheduling and request attribution without live reward collection."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from report_service import ReportService
from report_receipts import wait_report_receipt,ReportRejected,ReportResponseLog


class ReportServiceTests(unittest.TestCase):
    """Ensure no network work before the deadline and no reward resend on cancellation or uncertainty."""

    def setUp(self):
        self.clock=patch('report_service.time.monotonic',return_value=100)
        self.now=self.clock.start();self.addCleanup(self.clock.stop)
        self.events=[];self.c=Mock(report_generation=1)
        self.c.refresh_reports.return_value={'claimable':2}
        self.c.claim_reports.return_value={'ret':0,'code':11046}
        self.owner=SimpleNamespace(guard=threading.RLock(),closing=threading.Event(),connection=self.c,publish=lambda **v:self.events.append(v))
        self.s=ReportService(self.owner)

    def test_default_off_and_enable_wait_two_hours_without_any_network_polling(self):
        self.s.tick(self.c);self.c.refresh_reports.assert_not_called()
        self.s.switch(True)
        for value in (100,101,1000,7299):
            self.now.return_value=value;self.s.tick(self.c)
        self.c.refresh_reports.assert_not_called();self.c.claim_reports.assert_not_called()
        self.now.return_value=7300;self.s.tick(self.c)
        self.assertEqual(self.c.refresh_reports.call_count,2)
        self.c.claim_reports.assert_called_once()
        self.assertEqual(self.s.due,14500)
        self.s.tick(self.c);self.c.claim_reports.assert_called_once()

    def test_no_rewards_skips_receive_and_reschedules(self):
        self.c.refresh_reports.return_value={'claimable':0}
        self.s.switch(True);self.now.return_value=7300;self.s.tick(self.c)
        self.c.claim_reports.assert_not_called()
        self.assertTrue(self.s.enabled);self.assertEqual(self.s.due,14500)

    def test_switch_off_discards_deadline_and_restart_waits_another_full_interval(self):
        self.s.switch(True);self.now.return_value=5000;self.s.switch(False)
        self.now.return_value=7400;self.s.tick(self.c);self.c.refresh_reports.assert_not_called()
        self.s.switch(True);self.assertEqual(self.s.due,14600)

    def test_unknown_claim_stops_and_never_retries_or_reenables(self):
        self.c.claim_reports.side_effect=TimeoutError('No acknowledgement')
        self.s.switch(True);self.now.return_value=7300;self.s.tick(self.c)
        self.assertFalse(self.s.enabled);self.assertTrue(self.s.uncertain)
        self.now.return_value=20000;self.s.tick(self.c);self.c.claim_reports.assert_called_once()
        with self.assertRaises(RuntimeError):self.s.switch(True)

    def test_disable_during_query_never_sends_receive(self):
        def cancel_query(*args):
            """Simulate stopping while the list response is being processed."""
            self.s.switch(False);return {'claimable':10}
        self.c.refresh_reports.side_effect=cancel_query
        self.s.switch(True);self.now.return_value=7300;self.s.tick(self.c)
        self.c.claim_reports.assert_not_called();self.assertFalse(self.s.enabled)

    def test_server_refusal_is_definitive_but_does_not_grant_automatic_retry(self):
        self.c.claim_reports.side_effect=ReportRejected(6001)
        self.s.switch(True);self.now.return_value=7300;self.s.tick(self.c)
        self.assertFalse(self.s.enabled);self.assertFalse(self.s.uncertain)
        self.s.tick(self.c);self.c.claim_reports.assert_called_once()

    def test_trial_start_and_worker_stop_cancel_report_timer(self):
        from controller import Worker
        w=Worker(Mock());w.connection=Mock()
        w.report.switch(True);w.switch_trial(True)
        self.assertFalse(w.report.enabled);self.assertEqual(w.report.due,float('inf'))
        w.stop();self.assertFalse(w.report.enabled)


class ReportReceiptTests(unittest.TestCase):
    """Match the native get-all parameter order and reject foreign, duplicate or unowned responses."""

    def log(self, operation, request, response):
        code=11045 if operation=='refresh'else 11046
        return Mock(drain=Mock(return_value=[{'tag':f's_{code}_Req','body':request},{'tag':f'r_{code}_Rsp','body':response}]))

    def test_native_get_all_request_and_successful_response(self):
        # JCE: id0, getAll1, mailType0; response ret0, id0, mailType0.
        log=self.log('claim',bytes.fromhex('0c10012c'),bytes.fromhex('0c2c3c'))
        self.assertEqual(wait_report_receipt(log,'claim',lambda:False)['ret'],0)

    def test_wrong_get_all_or_mail_type_is_rejected(self):
        for payload in ('0c1c2001','0c1c2c'):
            with self.assertRaises(RuntimeError):wait_report_receipt(self.log('claim',bytes.fromhex(payload),b'\x0c'),'claim',lambda:False)

    def test_cancel_does_not_consume_log_or_send_anything(self):
        log=Mock()
        with self.assertRaises(InterruptedError):wait_report_receipt(log,'claim',lambda:True)
        log.drain.assert_not_called()

    def test_bounded_log_reader_avoids_reading_old_history_and_preserves_partial_tail(self):
        tag=b'r_11045_Rsp';stamp=b'00:00:00';body=b'\x0c'
        frame=bytes([len(tag)])+tag+bytes([len(stamp)])+stamp+len(body).to_bytes(4,'little')+body
        size=10000000;offset=max(0,(size-524288)//4096)*4096
        with patch.object(ReportResponseLog,'read',side_effect=[b'2026_11_08',b'00_00_00',str(size).encode(),b'junk'+frame+frame[:8]]) as read:
            log=ReportResponseLog('adb')
        self.assertEqual(log.cursor,offset+4+len(frame))
        self.assertIn('count=129',read.call_args.args)
