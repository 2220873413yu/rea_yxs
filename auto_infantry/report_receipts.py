"""Match one military report list/receive request to its response without retaining report contents."""
import time
from game_log import tags
from game_log import GameResponseLog
from game_protocol import JceReader


class ReportResponseLog(GameResponseLog):
    """Use the shared bounded cursor for military-report acknowledgement matching."""


class ReportRejected(RuntimeError):
    """Carry a definitive server refusal, which must never cause an automatic retry."""

    def __init__(self, ret):
        super().__init__(f'服务器拒绝军报操作：{ret}')


def wait_report_receipt(log, operation, cancelled, timeout=8):
    """Wait for one exact ground-mail list or native get-all acknowledgement; cancellation never resends."""
    code = 11045 if operation == 'refresh' else 11046
    sent = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled():
            raise InterruptedError('自动领取军报已关闭；已提交请求不重发')
        for record in log.drain():
            sending = record['tag'].startswith(f's_{code}_')
            receiving = record['tag'].startswith(f'r_{code}_')
            if not sending and not receiving:
                continue
            data = tags(JceReader(record['body']).fields())
            if sending:
                valid = (data.get(0,0)==0 and data.get(1,0)==0) if operation=='refresh' else (
                    data.get(0,0)==0 and data.get(1)==1 and data.get(2,0)==0)
                if sent or not valid:
                    raise RuntimeError('出现其他军报请求，结果无法归属；不重发')
                sent = True
            else:
                if not sent or type(data.get(0)) is not int:
                    raise RuntimeError('军报响应无法归属；不重发')
                if data[0] != 0:
                    raise ReportRejected(data[0])
                if data.get(4 if operation=='refresh' else 3,0)!=0 or (operation=='claim' and data.get(2,0)!=0):
                    raise RuntimeError('军报响应对象不一致；不重发')
                return {'ret':0,'code':code}
        time.sleep(.1)
    raise TimeoutError('军报请求结果不明，已停止且不自动重发')
