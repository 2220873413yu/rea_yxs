"""Atomic, local-user encrypted map player indexes, isolated by protocol zone and map ID."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from account_store import crypt_profile
from league_comparison import checked_league_snapshot


def scope_key(scope):
    """Validate server-supplied scope IDs before using them in a local filename."""
    values=tuple(scope.get(k)for k in ('zone_id','map_id'))
    if any(type(v)is not int or not 0<=v<=9007199254740991 for v in values):
        raise ValueError('地图或区服标识无效')
    return values


def player_key(identity):
    """Separate users by all four native identity fields; names, coordinates and league membership may change."""
    if (not isinstance(identity,list)or len(identity)!=4 or type(identity[0])is not int or
        not 0<=identity[0]<=9007199254740991 or not isinstance(identity[1],str)or len(identity[1])>512 or
        not(identity[0]or identity[1])or any(type(v)is not int or not 0<=v<=1000 for v in identity[2:])):
        raise ValueError('地图玩家身份字段无效')
    return hashlib.sha256(json.dumps(identity,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def checked_player(row):
    """Persist only the explicit identity/name/league/coordinate observation, never an entire native object."""
    key=player_key(row['identity'])
    for k in ('name','league_name'):
        if not isinstance(row.get(k),str)or len(row[k])>512:raise ValueError('地图玩家名称字段无效')
    for k in ('league_id','x','y','observed_ms'):
        if type(row.get(k))is not int or not 0<=row[k]<=9007199254740991:raise ValueError('地图玩家记录字段无效')
    return key,{k:row[k]for k in ('identity','name','league_id','league_name','x','y','observed_ms')}


class MapIndexStore:
    """Keep one encrypted file per world; missing sightings never delete an earlier player observation."""

    def __init__(self,root=None,cipher=crypt_profile):
        self.root=Path(root)if root else Path(__file__).with_name('map_player_indexes')
        self.cipher=cipher

    def path(self,scope):
        """Build a scope-only filename, independent of nicknames or arbitrary user text."""
        zone,map_id=scope_key(scope)
        return self.root/f'{zone}_{map_id}.dpapi'

    def load(self,scope):
        """Keep the existing player-only reader compatible with indexes that also store league totals."""
        return self.load_snapshot(scope)['players']

    def load_snapshot(self,scope):
        """Read this world's players and optional totals; older indexes have no totals and need no migration query."""
        path=self.path(scope)
        if not path.exists():return dict(players={},league_snapshot=None)
        try:
            if path.stat().st_size>16*1024*1024:raise ValueError('文件过大')
            value=json.loads(self.cipher(path.read_bytes(),decrypt=True).decode('utf-8'))
            if value.get('format')!=1 or scope_key(value['scope'])!=scope_key(scope):raise ValueError('地图不匹配')
            players={}
            for row in value['players']:
                key,clean=checked_player(row);players[key]=clean
            return dict(players=players,league_snapshot=checked_league_snapshot(value.get('league_snapshot')))
        except Exception as error:raise RuntimeError('本地地图玩家记录读取失败，未自动覆盖文件')from error

    def save(self,scope,players,league_snapshot=None):
        """Atomically encrypt players and their independently timed alliance totals in the same map-scoped file."""
        path=self.path(scope);self.root.mkdir(parents=True,exist_ok=True)
        clean=[checked_player(row)[1]for row in players.values()]
        payload=json.dumps(dict(format=1,scope=dict(zip(('zone_id','map_id'),scope_key(scope))),players=clean,
            league_snapshot=checked_league_snapshot(league_snapshot)),ensure_ascii=False).encode('utf-8')
        encrypted=self.cipher(payload);temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root,prefix='.index-',suffix='.tmp',delete=False)as file:
                temporary=Path(file.name);file.write(encrypted);file.flush();os.fsync(file.fileno())
            os.replace(temporary,path)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)


def public_players(players):
    """Project records for Tk/events without exporting the native identity to UI or action logs."""
    return [dict(record_key=key,**{k:v for k,v in row.items()if k!='identity'})
            for key,row in sorted(players.items(),key=lambda x:(x[1]['league_name'],x[1]['name'],x[0]))]
