"""Run-scoped monster records survive the game's replacement of its single regional cache."""
import time


class MonsterDiscovery:
    """Keep a finite near-first scan frontier and deduplicated sightings, never a periodic scan timer."""

    def __init__(self):
        self.regions = None
        self.cursor = 0
        self.records = {}

    def merge(self, rows):
        """Record sightings by ID; a respawn at the same coordinate supersedes its old identity."""
        for row in rows:
            point = (row['x'], row['y'])
            for identity, old in list(self.records.items()):
                if identity != row['target_id'] and (old['x'], old['y']) == point:
                    del self.records[identity]
            self.records[row['target_id']] = {**self.records.get(row['target_id'], {}), **row,
                                               'seen_at': time.monotonic()}

    def plan(self, regions):
        """Install native-distance bounds once; stable ordering makes incremental scans reproducible."""
        self.regions = sorted(regions, key=lambda r: (r['min_distance'], r['distance'], r['x'], r['y']))
        self.cursor = 0

    def next_region(self, target_distance=float('inf'), waiting_distance=float('inf')):
        """Search only unfinished regions that may contain a closer target within the permitted ring."""
        if self.regions is None or self.cursor >= len(self.regions):
            return None
        region = self.regions[self.cursor]
        return region if region['min_distance'] <= min(target_distance, waiting_distance) else None

    def accept(self, region, rows):
        """Advance only after a confirmed response; a failed region is never silently marked empty."""
        if self.regions is None or self.cursor >= len(self.regions) or self.regions[self.cursor] != region:
            raise RuntimeError('打野区域扫描进度发生变化')
        # Core rectangles are guaranteed covered; absence here can retire a dead/hidden old sighting.
        returned = {row['target_id'] for row in rows}
        for identity, old in list(self.records.items()):
            if (identity not in returned and 'logic_x' in old and 'left' in region and
                    region['left'] <= old['logic_x'] <= region['right'] and
                    region['bottom'] <= old['logic_y'] <= region['top']):
                del self.records[identity]
        self.merge(rows)
        self.cursor += 1

    def rescan(self):
        """An explicit check may rescan finite regions without dropping sightings or weak exclusions."""
        self.cursor = 0
