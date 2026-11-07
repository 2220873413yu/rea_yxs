"""Read the existing log and print only mail-list request cursors, result codes and record counts."""
import sys
import re
import struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from game_log import GameResponseLog,tags
from game_protocol import JceReader
from connection import ADB


def main():
    """Inspect existing list traffic; never send a request or print report contents and account identifiers."""
    log=GameResponseLog.__new__(GameResponseLog);log.adb=ADB;log.device='emulator-5554'
    folder='/storage/emulated/0/Android/data/com.qqgame.mic/files/YXS/net'
    date=next(s for s in log.read('shell','ls','-t',folder).decode('ascii').split()if re.fullmatch(r'\d{4}_\d{2}_\d{2}',s))
    folder+='/'+date
    name=next(s for s in log.read('shell','ls','-t',folder).decode('ascii').split()if re.fullmatch(r'\d{2}_\d{2}_\d{2}',s))
    blob=log.read('exec-out','tail','-c','2097152',folder+'/'+name)
    code=int(sys.argv[1])
    selected=[]
    for match in re.finditer(f'[sr]_{code}_'.encode('ascii'),blob):
        at=match.start();size=blob[at-1];tag=blob[at:at+size]
        if not re.fullmatch(rb'[sr]_\d+_\w+',tag):continue
        pos=at+size;pos+=1+blob[pos]
        length=struct.unpack_from('<I',blob,pos)[0];body=blob[pos+4:pos+4+length]
        if len(body)==length:selected.append(dict(tag=tag.decode('ascii'),body=body))
    for record in selected[-6:]:
        data=tags(JceReader(record['body']).fields())
        if record['tag'].startswith('s_'):
            print(dict(direction='request',cursor=data.get(0),mail_type=data.get(1)))
        else:
            print(dict(direction='response',ret=data.get(0),rows=len(data.get(1,[])),mail_type=data.get(4)))


if __name__=='__main__':
    main()
