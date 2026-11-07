"""Treat the map's configured refresh times as one-shot scan hints, never proof of a monster respawn."""
import math
import re


class MonsterRefresh:
    """Coalesce crossed server-clock boundaries until native capacity permits one fresh scan."""

    def __init__(self):
        self.config = None
        self.seconds = ()
        self.next_ms = None
        self.pending = False

    def observe(self, server_now_ms, text):
        """Read the existing local server clock; crossing multiple slots queues only one scan hint."""
        if (type(server_now_ms) not in (int, float) or not math.isfinite(server_now_ms) or
                server_now_ms <= 0 or not isinstance(text, str)):
            raise ValueError('野怪刷新参考时间无效，未安排重扫')
        if text != self.config:
            self.seconds = self.parse(text)
            self.config = text
            self.next_ms = self.next_after(server_now_ms)
            return False
        if self.next_ms is not None and server_now_ms >= self.next_ms:
            first_hint = not self.pending
            self.pending = True
            self.next_ms = self.next_after(server_now_ms)
            return first_hint
        return False

    @staticmethod
    def parse(text):
        """Normalize midnight24:00 to00:00 and reject malformed map configuration instead of guessing."""
        values = set()
        if not text:
            return ()
        for slot in text.split('|'):
            match = re.fullmatch(r'(\d{2}):(\d{2}):(\d{2})', slot)
            if not match:
                raise ValueError('地图野怪刷新时刻配置无法识别')
            hour, minute, second = map(int, match.groups())
            if hour > 24 or minute > 59 or second > 59 or (hour == 24 and (minute or second)):
                raise ValueError('地图野怪刷新时刻配置无效')
            values.add((hour * 3600 + minute * 60 + second) % 86400)
        return tuple(sorted(values))

    def next_after(self, server_now_ms):
        """Find the next configured Beijing-time boundary from server epoch time, independent of PC timezone."""
        if not self.seconds:
            return None
        day_ms = ((server_now_ms + 28800000) // 86400000) * 86400000 - 28800000
        candidates = [day_ms + second * 1000 for second in self.seconds]
        return min((value for value in candidates if value > server_now_ms),
                   default=day_ms + 86400000 + self.seconds[0] * 1000)

    def consume(self):
        """Clear one queued hint only when the caller is actually ready to begin a fresh scan."""
        pending = self.pending
        self.pending = False
        return pending
