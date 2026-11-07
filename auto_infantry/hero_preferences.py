"""Validate and persist explicit hero choices; never persist a spending-enabled switch."""
import json
import os
import tempfile
from pathlib import Path

PREFERENCES_PATH = Path(__file__).with_name('hero_preferences.json')


def checked_heroes(values):
    """Return unique positive game identifiers, rejecting malformed or unbounded selections."""
    if not isinstance(values, (list, tuple, set)) or len(values) > 1000:
        raise ValueError('英雄选择格式无效')
    if any(type(value) is not int or not 0 < value <= 10000000 for value in values):
        raise ValueError('英雄标识无效')
    return tuple(sorted(set(values)))


def load_heroes(path=PREFERENCES_PATH):
    """Load only selected IDs; a missing file means no hero is selected on first launch."""
    path = Path(path)
    if not path.exists():
        return ()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('英雄选择文件格式无效')
    return checked_heroes(data.get('selected_heroes'))


def save_heroes(values, path=PREFERENCES_PATH):
    """Atomically replace the selection file so interruption cannot leave a partially written list."""
    selected = checked_heroes(values)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'version': 1, 'selected_heroes': list(selected)}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return selected
