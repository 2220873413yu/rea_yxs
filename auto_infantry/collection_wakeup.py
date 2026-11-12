"""Wake collection on server stage deadlines or passive hints, without periodic server polling."""


class CollectionWakeup:
    """Coalesce local push hints and one-shot deadlines with a1s discovery throttle."""

    def __init__(self):
        self.poll_due = 0
        self.sequence = None
        self.pending = False
        self.next_check = float('-inf')
        self.timers = {}
        self.fired = {}

    @property
    def next_deadline(self):
        """Keep the earliest unconsumed stage deadline available when a fresh read fails."""
        return min((value[0] for value in self.timers.values()), default=float('inf'))

    def schedule(self, snapshot, now):
        """Map server epoch deadlines onto monotonic time, independent of rates, levels and PC clock."""
        server_now = snapshot['server_now_ms']
        if type(server_now) not in (int, float) or server_now <= 0:
            raise ValueError('服务器时间无效，未安排采集检查')
        timers = {}
        active = set()
        for row in snapshot['stages']:
            key = (row['army_id'], row['state'])
            end = row['end_ms']
            active.add(key)
            if row['state'] not in (2, 3, 6, 9) or type(end) not in (int, float) or end <= 0:
                continue
            # An unchanged or already-expired stage cannot schedule an endless confirmation loop.
            fired = self.fired.get(key)
            if fired == end or (end <= server_now and fired is not None):
                continue
            timers[key] = (now + max(0, (end - server_now) / 1000) + 1, end)
        self.timers = timers
        self.fired = {key: end for key, end in self.fired.items() if key in active}
        return self.next_deadline

    def poll(self, connection, now):
        """Sample local notification state, merging bursts without issuing any server query."""
        if now < self.poll_due:
            return
        sequence = connection.collection_push_sequence()
        self.poll_due = now + .25
        if self.sequence is not None and sequence != self.sequence:
            self.pending = True
        self.sequence = sequence

    def begin(self, now, deadline_due):
        """Consume due stage timers before I/O, preserving new pushes for one later bounded check."""
        if now < self.next_check or (not self.pending and now < deadline_due):
            return False
        self.pending = False
        self.next_check = now + 1
        for key, (due, end) in list(self.timers.items()):
            if due <= now:
                self.fired[key] = end
                del self.timers[key]
        return True
