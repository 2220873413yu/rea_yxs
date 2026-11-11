"""One serial event-driven trial run, with no fixed server polling and no automatic retries or revival."""
import time
from trial_receipts import TrialRejected
from hunt_reconnect import connection_lost

MUTATIONS = {'select', 'challenge', 'skip', 'return_after_win'}


class TrialService:
    """Own the world-to-battle transition until manual handoff returns to an authenticated map."""

    def __init__(self, owner):
        self.owner = owner
        self.enabled = False
        self.holding = False
        self.epoch = 0
        self.uncertain = False
        self.phase = 'off'
        self.deadline = float('inf')
        self.local_due = 0
        self.before = 0
        self.selected_ids = None
        self.quest = None
        self.won_floor = None
        self.last_snapshot = None
        self.reconnect_requested = False

    def switch(self, enabled):
        """Explicit starts reset planning only; stops immediately revoke queued trial requests without touching the game."""
        with self.owner.guard:
            if enabled and self.uncertain:
                raise RuntimeError('上次试炼动作结果不明，请核对游戏并重新连接；不会自动重试')
            if enabled and self.holding:
                raise RuntimeError('请先手动处理结算并返回地图，等待助手重新读取后再开启')
            self.enabled = bool(enabled) and not self.owner.closing.is_set()
            self.epoch += 1
            if self.owner.connection is not None:
                self.owner.connection.set_trial_enabled(self.enabled)
            if self.enabled:
                self.holding = True
                self.phase = 'begin'
                self.local_due = 0
                self.reconnect_requested = False
                self.selected_ids = None
                self.quest = None
            elif self.holding:
                self.phase = 'handoff'
                self.owner.publish(trial_status='自动爬塔已关闭；当前战斗/结算由你处理，不再跳过或挑战')
            self.owner.publish(trial_enabled=self.enabled, trial_exclusive=self.holding)

    def alive(self, epoch):
        """Reject work from an older checkbox generation or a closing worker."""
        return self.enabled and self.epoch == epoch and not self.owner.closing.is_set()

    def stop_with(self, message, uncertain=False):
        """Preserve the game screen on defeat/refusal/uncertainty and never issue a retry, return or revive."""
        self.uncertain = self.uncertain or uncertain
        self.switch(False)
        self.owner.publish(trial_enabled=False, trial_status=message)

    def action(self, connection, operation, snapshot, next_phase, timeout=10):
        """Reserve one action under the UI generation, then wait only for its exact native acknowledgement."""
        epoch = self.epoch
        with self.owner.guard:
            if not self.alive(epoch):
                return
            generation = connection.trial_generation
            if operation in MUTATIONS:
                self.uncertain = True
        receipt = connection.trial_action(operation, generation, lambda: not self.alive(epoch))
        with self.owner.guard:
            self.uncertain = False
            if not self.alive(epoch):
                return
            self.before = snapshot['available_seq'] if operation == 'query_available' else snapshot['profile_seq']
            self.phase = next_phase
            self.deadline = time.monotonic() + timeout
            if operation == 'select':
                self.selected_ids = sorted(receipt['heroes'])
            if operation == 'challenge':
                self.quest = receipt['target']
                self.won_floor = snapshot['today_floor'] + 1
                self.uncertain = True
            self.owner.publish(action='trial_' + operation, receipt=receipt)

    def profile_ready(self, connection, s):
        """Continue an existing server roster, or obtain fresh trial-specific eligibility before selecting anyone."""
        if s['profile_ret'] != 0:
            raise RuntimeError('试炼主资料读取失败，未挑战')
        if s['next_quest'] <= 0 or (s['total'] > 0 and s['today_floor'] >= s['total']):
            self.stop_with('本轮试炼已完成，自动爬塔已关闭')
        elif len(s['heroes']) == 3:
            if self.selected_ids is not None and sorted(h['id'] for h in s['heroes']) != self.selected_ids:
                raise RuntimeError('服务器确认的三人名单与本次选择不同，已停止')
            self.phase = 'challenge'
        elif s['heroes']:
            raise RuntimeError('本轮名单不是完整三人，请手动处理；不自动重置试炼')
        elif s['remaining'] <= 0:
            self.stop_with('试炼次数已用完，自动爬塔已关闭')
        else:
            self.action(connection, 'query_available', s, 'roster')

    def tick(self, connection):
        """Advance on cached responses, a native deadline or local round changes; never poll the game server on a timer."""
        if not self.holding:
            return False
        if self.reconnect_requested or time.monotonic() < self.local_due:
            return True
        self.local_due = time.monotonic() + .25
        try:
            s = connection.trial_call('status')
            self.last_snapshot = s
            self.owner.publish(trial_snapshot={**s, 'phase': self.phase, 'enabled': self.enabled})
            if not self.enabled:
                if s['world_ready']:
                    self.reconnect_requested = True
                    self.owner.publish(trial_reconnect=True)
                return True
            if self.phase == 'begin':
                connection.trial_call('begin', generation=connection.trial_generation)
                self.action(connection, 'query_profile', s, 'profile')
            elif self.phase in ('profile', 'selected', 'next_profile') and s['profile_seq'] > self.before:
                if self.phase == 'next_profile' and s['next_quest'] == self.quest:
                    raise RuntimeError('胜利后未确认下一层进度，已关闭；不重打当前层')
                self.profile_ready(connection, s)
            elif self.phase == 'roster' and s['available_seq'] > self.before:
                if s['available_ret'] != 0:
                    raise RuntimeError('试炼可用英雄名单被服务器拒绝')
                self.action(connection, 'select', s, 'selected')
            elif self.phase == 'challenge':
                self.action(connection, 'challenge', s, 'battle', 45)
            elif self.phase == 'battle' and s['battle_ready']:
                self.phase = 'skip'
                self.deadline = time.monotonic() + max(60, (s['skip_at_ms'] - s['server_now_ms']) / 1000 + 30)
            elif self.phase in ('skip', 'result') and s.get('result') is not None:
                result = s['result']
                if result['ret'] != 0 or type(result['win']) is not bool:
                    raise RuntimeError('本场结算异常，已停止；不自动重试')
                if not result['win']:
                    self.uncertain = False
                    self.stop_with(f"第{self.won_floor}层战败，自动爬塔已关闭；请手动接着打，不自动复活或重试")
                else:
                    self.phase = 'won'
                    self.owner.publish(trial_status=f'第{self.won_floor}层胜利，准备返回并确认下一层')
            elif self.phase == 'skip' and s['can_skip']:
                self.action(connection, 'skip', s, 'result', 45)
                # Acknowledging skip is not a confirmed win; retain uncertainty until the actual result.
                self.uncertain = True
            elif self.phase == 'won':
                self.uncertain = False
                self.action(connection, 'return_after_win', s, 'returning', 60)
            elif self.phase == 'returning' and s['world_ready']:
                if s['profile_seq'] > self.before and s['next_quest'] != self.quest:
                    self.profile_ready(connection, s)
                else:
                    self.action(connection, 'query_profile', s, 'next_profile')
            elif time.monotonic() >= self.deadline:
                raise TimeoutError('等待本次试炼阶段超时，已关闭；不会自动重发或重试')
        except TrialRejected as error:
            self.uncertain = False
            self.stop_with(str(error))
        except InterruptedError:
            return True
        except Exception as error:
            if connection_lost(error):
                raise
            if not self.enabled:
                if any(message in str(error) for message in ('switched off', 'Trial switch changed')):
                    return True
                self.reconnect_requested = True
                self.owner.publish(ready=False, trial_status='连接状态无法读取，爬塔保持关闭；请核对游戏后重新读取账号')
            else:
                self.stop_with('自动爬塔已停止：' + str(error).splitlines()[0], self.uncertain)
        return True
