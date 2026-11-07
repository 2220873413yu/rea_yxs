"""Persist only beacon type choices, never a spending-enabled switch."""
import json
import os
import tempfile
from pathlib import Path

PREFERENCES_PATH=Path(__file__).with_name('beacon_preferences.json')


def checked_types(values):
    """Accept only the four native type identifiers and return deterministic unique choices."""
    if not isinstance(values,(list,tuple,set)) or any(type(v) is not int or v not in (1,2,3,4) for v in values):
        raise ValueError('烽火台类型选择无效')
    return tuple(sorted(set(values)))


def load_types(path=PREFERENCES_PATH):
    """Migrate existing installations to rescue-only; corrupt data never enables additional types."""
    path=Path(path)
    if not path.exists():return (1,)
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('烽火台选择文件无效')
    return checked_types(data.get('types'))


def save_types(values,path=PREFERENCES_PATH):
    """Atomically store explicit type choices without persisting automatic execution authorization."""
    values=checked_types(values);path=Path(path);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(dict(version=1,types=list(values)),stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return values
