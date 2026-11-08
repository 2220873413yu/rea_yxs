"""Explicitly cleared, encrypted public-profile cache scoped by server zone/map and exact player identity."""
import copy
import json
import os
import tempfile
from pathlib import Path
from account_store import crypt_profile
from map_index_store import scope_key,player_key


def clean_profile(snapshot):
    """Keep only public display data from a confirmed successful reply; never persist credentials or native UIDs."""
    user_id=snapshot.get('display_id')
    if type(user_id)is not int or not 0<user_id<=9007199254740991:raise ValueError('玩家公开ID未确认')
    if snapshot.get('ready')is False or not isinstance(snapshot.get('nickname'),str):raise ValueError('玩家资料未确认')
    if type(snapshot.get('confirmed_ms'))is not int or snapshot['confirmed_ms']<=0:raise ValueError('资料确认时间无效')
    heroes=snapshot.get('heroes')
    if not isinstance(heroes,list)or len(heroes)>4:raise ValueError('武将资料无效')
    clean=[]
    for hero in heroes:
        if hero.get('role')not in ('最强武将','展示武将1','展示武将2','展示武将3'):raise ValueError('武将展示位置无效')
        row={k:hero[k]for k in ('role','name','power','level','star')if k in hero}
        for field,keys in (('gems',('slot','name','level','unlocked')),('equipment',('slot','name'))):
            values=hero.get(field,[])
            if not isinstance(values,list)or len(values)>32:raise ValueError('武将槽位无效')
            row[field]=[{k:item[k]for k in keys if k in item}for item in values]
        clean.append(row)
    return dict(ready=True,display_id=user_id,nickname=snapshot['nickname'],confirmed_ms=snapshot['confirmed_ms'],heroes=clean)


class PlayerProfileCache:
    """Persist successful public profiles across restarts; clearing never touches map sightings or account tickets."""

    def __init__(self,root=None,cipher=crypt_profile):
        """Create an idle cache with an injectable encryption boundary for offline regression tests."""
        self.root=Path(root)if root else Path(__file__).with_name('player_profile_caches')
        self.cipher=cipher;self.loaded={}

    def path(self,scope):
        """Use validated numeric scope IDs exclusively in filenames."""
        zone,map_id=scope_key(scope);return self.root/f'{zone}_{map_id}.dpapi'

    def load(self,scope):
        """Read local data only; corrupted files require explicit clearing rather than silent network fallback."""
        key=scope_key(scope)
        if key not in self.loaded:
            value=dict(profiles={},aliases={});path=self.path(scope)
            if path.exists():
                try:
                    if path.stat().st_size>32*1024*1024:raise ValueError('缓存过大')
                    raw=json.loads(self.cipher(path.read_bytes(),decrypt=True).decode('utf-8'))
                    if raw['format']!=1 or scope_key(raw['scope'])!=key:raise ValueError('缓存范围不匹配')
                    value['profiles']={str(clean_profile(s)['display_id']):clean_profile(s)for s in raw['profiles'].values()}
                    value['aliases']={k:v for k,v in raw['aliases'].items()if isinstance(k,str)and len(k)==64 and str(v)in value['profiles']}
                except Exception as error:raise RuntimeError('玩家资料缓存读取失败，请点击“清空资料缓存”后重试')from error
            self.loaded[key]=value
        return self.loaded[key]

    def get(self,scope,user_id=None,identity=None):
        """Return a copy with its original server-confirmation time and an explicit local-cache marker."""
        value=self.load(scope)
        if identity is not None:user_id=value['aliases'].get(player_key(identity))
        row=value['profiles'].get(str(user_id))
        if row is None:return None
        return dict(copy.deepcopy(row),from_cache=True)

    def put(self,scope,snapshot,identity=None):
        """Atomically store a successful public ID and optional hashed native-identity mapping."""
        clean=clean_profile(snapshot);key=scope_key(scope);value=copy.deepcopy(self.load(scope))
        value['profiles'][str(clean['display_id'])]=clean
        if identity is not None:value['aliases'][player_key(identity)]=clean['display_id']
        payload=json.dumps(dict(format=1,scope=dict(zip(('zone_id','map_id'),key)),**value),ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.root.mkdir(parents=True,exist_ok=True);encrypted=self.cipher(payload)
        fd,temp=tempfile.mkstemp(prefix='.profile-',suffix='.tmp',dir=self.root)
        try:
            with os.fdopen(fd,'wb')as file:file.write(encrypted);file.flush();os.fsync(file.fileno())
            os.replace(temp,self.path(scope));self.loaded[key]=value
        finally:
            if os.path.exists(temp):os.unlink(temp)

    def clear(self,scope):
        """Delete only this scope's profile cache, preserving all map records and other scopes."""
        self.path(scope).unlink(missing_ok=True);self.loaded.pop(scope_key(scope),None)
