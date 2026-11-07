"""Read already-recorded quick-combat scalar tags, excluding player identities and unrelated records."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog,tags
from game_protocol import JceReader,read_records


def main():
    """Verify native skip tag meanings using only the previously authorized experiment's log records."""
    log=GameResponseLog(ADB)
    for r in read_records(log.read('exec-out','cat',log.path)):
        if r['tag'].startswith(('s_11006_','r_11006_')):
            d=tags(JceReader(r['body']).fields())
            target=d.get(0) if r['tag'].startswith('s_') else d.get(1)
            if target==152468:
                print(r['tag'],{k:v for k,v in d.items() if type(v) in (int,bool)})

if __name__=='__main__':main()
