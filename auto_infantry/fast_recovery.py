"""Bounded nonblocking-send recovery bursts with wire attribution and authoritative settlement."""
import time

from game_log import tags
from game_protocol import JceReader
from hero_recovery import recovery_decision


def burst_size(state):
    """Batch only complete five-minute slices; settle a short final remainder separately to avoid oversending."""
    if recovery_decision(state,state['hero_id'])[0]!='speed':
        return 0
    return min(3,state['items'],max(1,int(state['remaining_ms']//300000)))


def verify_batch(before,after,count):
    """Require exact aggregate stock consumption and cooldown progress for the same idle, fresh hero."""
    if (not 1<=count<=3 or after.get('hero_id')!=before['hero_id'] or not after.get('found') or
            not after.get('fresh') or not after.get('army_known') or after.get('busy') or after.get('hero_state')!=0):
        raise RuntimeError('快速恢复后英雄状态无法确认，已停止，不自动重试')
    if before['items']-after['items']!=count:
        raise RuntimeError('快速恢复道具扣量不符，已停止，不自动重试')
    expected=min(300000*count,before['remaining_ms'])
    if after['remaining_ms']>0 and before['finish_ms']-after['finish_ms']<expected-2000:
        raise RuntimeError('快速恢复冷却变化不符，已停止，不自动重试')


class RecoveryReceipts:
    """Count every request and successful response; the native last-response cache cannot count a burst."""

    def __init__(self,hero_id):
        self.hero_id=hero_id
        self.sent=0
        self.received=0

    def accept(self,records):
        """Reject foreign/concurrent acceleration and overcount before accepting a response as this batch's."""
        for record in records:
            parts=record['tag'].split('_')
            if len(parts)<3 or parts[1]!='186' or parts[0] not in ('s','r'):
                continue
            data=tags(JceReader(record['body']).fields())
            if (data.get(1),data.get(2),data.get(3))!=(3,500,self.hero_id):
                raise RuntimeError('快速恢复期间出现其他加速请求或响应，停止以免串数据')
            if parts[0]=='s':
                items=[tags(row['value']) for row in data.get(4,[])]
                if items!=[{0:70291,1:1}]:
                    raise RuntimeError('快速恢复道具或数量不属于本批次')
                self.sent+=1
                if self.sent>3:raise RuntimeError('快速恢复请求数量异常')
            else:
                if data.get(0)!=0 or self.received>=self.sent:
                    raise RuntimeError('快速恢复响应失败或无法归属，已停止，不自动重试')
                self.received+=1


class FastRecovery:
    """Serialize batches on the existing worker, while sending within a batch without waiting for replies."""

    def __init__(self):
        self.next_send=0
        self.uncertain=False

    def recover(self,connection,before,generation,cancelled,log,timeout=6):
        """Send at most three guarded items at >=334ms spacing, then settle once; uncertainty blocks reuse."""
        if self.uncertain:
            raise RuntimeError('上批快速恢复结果不明，请核对游戏并重新连接助手')
        maximum=burst_size(before)
        if not maximum:return {**before,'recovery_count':0}
        log.drain()
        receipts=RecoveryReceipts(before['hero_id'])
        sent=0
        try:
            for _ in range(maximum):
                while time.monotonic()<self.next_send and not cancelled():
                    time.sleep(max(0,min(.03,self.next_send-time.monotonic())))
                if cancelled():break
                # Mark unknown before entering the bridge: even an RPC timeout may have dispatched the item.
                self.uncertain=True
                step=connection.hero_call('hero_speed_step',generation,hero_id=before['hero_id'])
                self.next_send=time.monotonic()+.334
                if not step['sent']:
                    if step['reason']!='complete':
                        raise RuntimeError('快速恢复期间英雄或道具状态变化，已停止')
                    break
                sent+=1
            if not sent:
                self.uncertain=False
                return {**before,'recovery_count':0}
            # The next batch cannot start until all three evidence sources agree. Never resend a missing receipt.
            deadline=time.monotonic()+timeout
            while True:
                receipts.accept(log.drain())
                if receipts.sent==sent and receipts.received==sent:break
                if time.monotonic()>=deadline:
                    raise TimeoutError('快速恢复响应不完整，结果不明；已停止，不自动重试')
                time.sleep(.1)
            after=connection.refresh_hero(hero_id=before['hero_id'])
            verify_batch(before,after,sent)
            self.uncertain=False
            return {**after,'recovery_count':sent}
        except Exception:
            # Preserve the latch across switch changes, mode changes and later collection recovery demands.
            raise
