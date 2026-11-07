"""Validate and atomically save resource coordinates without persisting spending switches."""
import json
import os
import re
import tempfile
from pathlib import Path

PREFERENCES_PATH = Path(__file__).with_name('resource_preferences.json')


def checked_coordinates(values):
    """Return at most100 unique display-coordinate pairs, preserving the user's entry order."""
    if not isinstance(values, (list, tuple)) or len(values) > 100:
        raise ValueError('资源清单最多100个坐标')
    result = []
    for value in values:
        if (not isinstance(value, (list, tuple)) or len(value) != 2 or
                any(type(n) is not int or not 0 <= n <= 10000 for n in value)):
            raise ValueError('每个资源坐标必须是两个0至10000的整数')
        pair = tuple(value)
        if pair not in result:
            result.append(pair)
    return tuple(result)


def parse_coordinates(text):
    """Parse one x,y per nonblank line, accepting Chinese commas and whitespace separators."""
    pairs = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(\d+)\s*[,，\s]\s*(\d+)\s*', line)
        if not match:
            raise ValueError(f'第{line_no}行格式不对，请填写 x,y，例如97,192')
        pairs.append(tuple(map(int, match.groups())))
    return checked_coordinates(pairs)


def load_coordinates(path=PREFERENCES_PATH):
    """Load saved coordinates only; a missing file means an empty user-owned list."""
    path = Path(path)
    if not path.exists():
        return ()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('资源清单文件格式无效')
    return checked_coordinates(data.get('coordinates'))


def save_coordinates(values, path=PREFERENCES_PATH):
    """Atomically replace the validated list; failed writes leave the previous file intact."""
    coordinates = checked_coordinates(values)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'version': 1, 'coordinates': coordinates}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return coordinates


def remove_coordinate(coordinate, path=PREFERENCES_PATH):
    """Remove one confirmed missing coordinate from the latest saved list, preserving all other entries."""
    pair = checked_coordinates((coordinate,))[0]
    current = load_coordinates(path)
    remaining = tuple(point for point in current if point != pair)
    return save_coordinates(remaining, path) if remaining != current else current
