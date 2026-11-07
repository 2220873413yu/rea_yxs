"""Match one military report list/receive request to its response without retaining report contents."""
import time
import re
from game_log import tags
from game_log import GameResponseLog, record_end
from game_protocol import JceReader, read_records


class ReportResponseLog(GameResponseLog):
    """Start at the last complete frame using a bounded log tail, so a two-hour idle period never reads the whole file."""

    def __init__(self, adb, device='emulator-5554'):
        self.adb,self.device=adb,device
        folder='/storage/emulated/0/Android/data/com.qqgame.mic/files/YXS/net'
        date=next(s for s in self.read('shell','ls','-t',folder).decode('ascii').split()if re.fullmatch(r'\d{4}_\d{2}_\d{2}',s))
        folder+='/'+date
        name=next(s for s in self.read('shell','ls','-t',folder).decode('ascii').split()if re.fullmatch(r'\d{2}_\d{2}_\d{2}',s))
        self.path=folder+'/'+name
        size=int(self.read('shell','stat','-c','%s',self.path).strip())
        if size==4:
            self.cursor=4;return
        offset=max(0,(size-524288)//4096)*4096
        blob=self.read('exec-out','dd','if='+self.path,'bs=4096','skip='+str(offset//4096),'count=129')
        for match in re.finditer(rb'[sr]_\d+_\w+',blob):
            at=match.start()
            if at==0 or blob[at-1]!=len(match.group()):continue
            start=at-1
            try:
                records=read_records(bytes.fromhex('0100ffff')+blob[start:])
            except (ValueError,UnicodeError,AssertionError):
                continue
            if records:
                self.cursor=offset+start+record_end(records[-1])-4
                return
        raise RuntimeError('无法定位军报日志的完整记录，未发送请求')


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
