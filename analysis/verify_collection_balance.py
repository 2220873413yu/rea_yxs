"""Read-only smoke check of initialization and resource forecasts, with every action gate left closed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'auto_infantry'))
from connection import Connection


def main():
    """Read the current account once and print only resource allocation data, then detach."""
    connection=Connection()
    try:
        connection.open()
        connection.refresh_heroes()
        result=connection.collection_balance(lambda:False)
        print(result['balance'])
        print('all_action_gates=default_closed')
    finally:
        connection.close()


if __name__=='__main__':
    main()
