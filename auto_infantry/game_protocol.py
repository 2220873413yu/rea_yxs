"""Bounded Tars/JCE and game-log frame decoding, with no network access or credential output."""
import struct


class JceReader:
    """Read bounded Tars/JCE fields while retaining their numeric tags."""

    def __init__(self, data):
        self.data = data
        self.position = 0

    def take(self, size):
        """Consume an exact byte span; truncated fields are rejected."""
        end = self.position + size
        if size < 0 or end > len(self.data):
            raise ValueError('Truncated JCE field')
        result = self.data[self.position:end]
        self.position = end
        return result

    def field(self, depth=0):
        """Decode one tagged field, with a depth limit for nested structures."""
        if depth > 32:
            raise ValueError('JCE nesting exceeds analysis limit')
        head = self.take(1)[0]
        tag, kind = head >> 4, head & 15
        if tag == 15:
            tag = self.take(1)[0]
        if kind in (0, 1, 2, 3):
            value = int.from_bytes(self.take(1 << kind), 'big', signed=True)
        elif kind in (4, 5):
            value = struct.unpack('>f' if kind == 4 else '>d', self.take(4 if kind == 4 else 8))[0]
        elif kind in (6, 7):
            size = int.from_bytes(self.take(1 if kind == 6 else 4), 'big')
            value = self.take(size).decode('utf-8', errors='replace')
        elif kind in (8, 9):
            count = self.field(depth + 1)['value']
            if not isinstance(count, int) or not 0 <= count <= len(self.data):
                raise ValueError('Invalid JCE collection length')
            value = [self.field(depth + 1) for _ in range(count * (2 if kind == 8 else 1))]
        elif kind == 10:
            value = []
            while True:
                child = self.field(depth + 1)
                if child['wire_type'] == 11:
                    break
                value.append(child)
        elif kind == 11:
            value = None
        elif kind == 12:
            value = 0
        elif kind == 13:
            if self.take(1)[0] != 0:
                raise ValueError('Unsupported JCE simple-list subtype')
            count = self.field(depth + 1)['value']
            value = {'bytes_hex': self.take(count).hex()}
        else:
            raise ValueError(f'Unsupported JCE type {kind}')
        return dict(tag=tag, wire_type=kind, value=value)

    def fields(self):
        """Decode the complete body and fail on an invalid trailing field."""
        result = []
        while self.position < len(self.data):
            result.append(self.field())
        return result


def read_records(data):
    """Parse complete game log records; leave a concurrently written tail unparsed."""
    position = 4
    assert data[:4] == bytes.fromhex('0100ffff')
    records = []
    while position < len(data):
        start = position
        size = data[position]
        position += 1
        tag = data[position:position + size].decode('ascii')
        position += size
        if position >= len(data):
            break
        size = data[position]
        position += 1
        stamp = data[position:position + size].decode('ascii')
        position += size
        if position + 4 > len(data):
            break
        size = struct.unpack_from('<I', data, position)[0]
        position += 4
        if position + size > len(data):
            break
        records.append(dict(offset=start, tag=tag, timestamp=stamp, body=data[position:position + size]))
        position += size
    return records
