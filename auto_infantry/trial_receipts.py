"""Attribute one native trial request/response without retaining other game payloads."""
import time
from game_log import tags
from game_protocol import JceReader


class TrialRejected(RuntimeError):
    """Represent an exact server refusal; it grants no permission to retry the request."""

    def __init__(self, operation, ret):
        self.operation, self.ret = operation, ret
        super().__init__(f'服务器拒绝试炼{operation}：{ret}；自动爬塔已关闭')


def request_matches(operation, data, sent):
    """Check only the request fields identifying this selected roster, quest or battle army."""
    if operation == 'profile':
        return True
    if operation == 'available':
        return data.get(0) == sent['target'] and data.get(1) == 16
    if operation == 'select':
        rows = data.get(0, [])
        return sorted(tags(row['value']).get(0) for row in rows) == sorted(sent['heroes'])
    if operation == 'challenge':
        return (data.get(0) == sent['target'] and data.get(2) == 16 and
                tags(data.get(3, [])).get(0) == sent['hero_id'] and data.get(4, 0) in (0, False))
    if operation == 'skip':
        return data.get(0) == sent['army_id']
    return False


def wait_trial_receipt(log, operation, sent, cancelled, timeout=8):
    """Wait for one attributable acknowledgement; cancellation/timeout never resubmits or assumes victory."""
    code = sent['code']
    found = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled():
            raise InterruptedError('试炼已关闭；已提交请求不再重发')
        for record in log.drain():
            request = record['tag'].startswith(f's_{code}_')
            response = record['tag'].startswith(f'r_{code}_')
            if not request and not response:
                continue
            data = tags(JceReader(record['body']).fields())
            if request:
                if found or not request_matches(operation, data, sent):
                    raise RuntimeError('出现其他试炼请求，结果无法归属；已停止且不重发')
                found = True
            elif not found:
                raise RuntimeError('试炼响应不属于本次请求；已停止且不重发')
            else:
                ret = data.get(0)
                if type(ret) is not int:
                    raise RuntimeError('试炼响应结果无效；不重发')
                return ret
        time.sleep(.1)
    raise TimeoutError('试炼请求结果不明，已关闭且不会自动重发')
