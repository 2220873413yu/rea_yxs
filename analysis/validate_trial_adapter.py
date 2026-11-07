"""Read-only installation smoke check: no trial start, selection, challenge or skip."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import Connection


def main():
    """Install and inspect the default-off adapter in the live client, then restore every hook."""
    c = Connection()
    try:
        c.attach()
        print(c.script.exports_sync.query((ROOT / 'auto_infantry/trial_runtime.lua').read_text(encoding='utf-8')))
        view = json.loads(c.script.exports_sync.query('return REA_TRIAL.status()'))
        print(json.dumps(view, ensure_ascii=False))
        print(c.script.exports_sync.query('return REA_TRIAL.close()'))
    finally:
        c.close()


if __name__ == '__main__':
    main()
