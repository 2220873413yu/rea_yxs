"""A default-off two-hour timer; waiting never queries the game server or follows red-dot notifications."""
import time
from report_receipts import ReportRejected

INTERVAL_SECONDS = 2 * 60 * 60


class ReportService:
    """Serialize one fresh query and optional native get-all through the existing worker."""

    def __init__(self, owner):
        self.owner=owner
        self.enabled=False
        self.epoch=0
        self.due=float('inf')
        self.uncertain=False

    def alive(self, epoch):
        """Cancel old timer actions on master-off, session changes or worker close."""
        return self.enabled and self.epoch==epoch and not self.owner.closing.is_set()

    def schedule(self):
        """Set one local monotonic deadline and publish a Beijing-display timestamp, without network access."""
        self.due=time.monotonic()+INTERVAL_SECONDS
        self.owner.publish(report_next_ms=int((time.time()+INTERVAL_SECONDS)*1000))

    def switch(self, enabled):
        """Start a new two-hour interval; stopping revokes queued operations and discards the old timer."""
        with self.owner.guard:
            if enabled and self.uncertain:
                raise RuntimeError('上次军报领取结果不明，请核对游戏并重新读取账号；不会自动重发')
            self.enabled=bool(enabled)and not self.owner.closing.is_set()
            self.epoch+=1
            self.due=float('inf')
            if self.owner.connection is not None:
                self.owner.connection.set_report_enabled(self.enabled)
            if self.enabled:
                self.schedule()
            else:
                self.owner.publish(report_next_ms=None)
            self.owner.publish(report_enabled=self.enabled,report_status='已开启；两小时后首次检查并领取'if self.enabled else'自动领取军报关闭')

    def tick(self, connection):
        """Run once when due, then schedule another two hours; errors stop instead of retrying in a tight loop."""
        with self.owner.guard:
            if not self.enabled or self.owner.closing.is_set()or time.monotonic()<self.due:
                return
            epoch=self.epoch;generation=connection.report_generation
            self.due=float('inf')
        cancelled=lambda:not self.alive(epoch)
        try:
            snapshot=connection.refresh_reports(generation,cancelled)
            if cancelled():return
            self.owner.publish(report_snapshot=snapshot)
            claimed=False
            if snapshot['claimable']>0:
                with self.owner.guard:
                    if cancelled():return
                    self.uncertain=True
                receipt=connection.claim_reports(generation,cancelled)
                self.uncertain=False
                self.owner.publish(action='report_claim',receipt=receipt)
                claimed=True
                if cancelled():return
                snapshot=connection.refresh_reports(generation,cancelled)
                if cancelled():return
                self.owner.publish(report_snapshot=snapshot)
            with self.owner.guard:
                if cancelled():return
                self.schedule()
                self.owner.publish(report_status='服务器确认领取成功；两小时后再检查'if claimed else'没有可领奖励，本次跳过；两小时后再检查')
        except ReportRejected as error:
            self.uncertain=False
            if self.alive(epoch):
                self.switch(False);self.owner.publish(report_status=str(error)+'；自动领取已关闭')
        except InterruptedError:
            pass
        except Exception as error:
            if self.alive(epoch):
                self.switch(False);self.owner.publish(report_status='自动领取军报已停止：'+str(error).splitlines()[0],
                    account_changed='Account session changed'in str(error))
