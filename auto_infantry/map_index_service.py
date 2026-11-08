"""Explicit one-pass map discovery interleaved with existing worker tasks, without a periodic network timer."""
import threading
from map_index_store import MapIndexStore,scope_key,checked_player,public_players
from league_comparison import checked_league_snapshot


class MapIndexService:
    """Retain partial results, reject world changes and never infer that unseen players ceased to exist."""

    def __init__(self,worker,store=None):
        self.worker=worker;self.store=store or MapIndexStore();self.scope=None;self.players={}
        self.league_snapshot=None
        self.regions=[];self.cursor=0;self.active=False;self.cancel=threading.Event()

    def publish_index(self):
        """Publish only the safe UI projection; native identities remain in memory and encrypted storage."""
        self.worker.publish(map_index_snapshot=dict(scope=self.scope,players=public_players(self.players),league_snapshot=self.league_snapshot))

    def load(self,connection):
        """Startup reads the current scope and local file only; it never creates a search plan or area request."""
        scope=connection.map_index_call('context');scope_key(scope)
        snapshot=self.store.load_snapshot(scope)
        self.players=snapshot['players'];self.league_snapshot=snapshot['league_snapshot'];self.scope=scope;self.publish_index()

    def record_leagues(self,connection,snapshot):
        """Save totals only after the explicit league-list click succeeds; scope lookup itself is local-only."""
        current=connection.map_index_call('context');scope_key(current)
        if self.scope is None or scope_key(current)!=scope_key(self.scope):self.load(connection)
        clean=checked_league_snapshot(snapshot)
        self.store.save(self.scope,self.players,clean);self.league_snapshot=clean;self.publish_index()

    def merge(self,rows):
        """Update observed identities and preserve every earlier player missing from this region/pass."""
        combined=dict(self.players)
        for row in rows:
            key,clean=checked_player(row);previous=combined.get(key)
            if previous is None or clean['observed_ms']>=previous['observed_ms']:combined[key]=clean
        self.store.save(self.scope,combined,self.league_snapshot);self.players=combined

    def begin(self,connection):
        """A clicked search creates one finite region plan and saves currently loaded observations first."""
        self.cancel.clear();self.load(connection)
        self.regions=connection.map_index_call('plan')['regions'];self.cursor=0
        self.merge(connection.map_index_call('cached')['players']);self.active=True;self.publish_index()
        self.progress()

    def progress(self):
        """Display progress without issuing another server query."""
        self.worker.publish(map_index_progress=dict(active=self.active,done=self.cursor,total=len(self.regions),found=len(self.players)))

    def stop(self):
        """Stop after the current scoped region completes/restores, keeping all already saved observations."""
        self.cancel.set()

    def finish(self,message):
        """Release the shared manual-query gate while retaining partial results on completion/error/cancellation."""
        self.active=False;self.publish_index();self.progress()
        with self.worker.guard:self.worker.player_busy=False
        self.worker.publish(player_busy=False,league_query_status=message)

    def tick(self,connection):
        """Consume at most one planned area per worker iteration; no active click means no network work."""
        if not self.active:return
        if self.cancel.is_set()or self.worker.closing.is_set():
            self.finish(f'搜索已停止，保留本地{len(self.players)}名已发现玩家');return
        if self.cursor>=len(self.regions):
            self.finish(f'本轮区域搜索完成，已保存{len(self.players)}名玩家；不保证完整名单');return
        try:
            current=connection.map_index_call('context')
            if scope_key(current)!=scope_key(self.scope):raise RuntimeError('地图或区服已改变，未继续搜索')
            rows=connection.query_map_index_region(self.regions[self.cursor],lambda:self.cancel.is_set()or self.worker.closing.is_set())
            self.merge(rows['players']);self.cursor+=1;self.progress()
        except Exception as error:
            self.finish('搜索已停止，已保存的记录保留：'+str(error).splitlines()[0][:160])

    def query_player(self,connection,key):
        """Read only the clicked saved identity and confirm the same map before requesting fresh hero details."""
        row=self.players.get(key)
        if row is None:raise ValueError('本地玩家记录已失效，请重新加载')
        return connection.query_map_index_player(self.scope,row,self.worker.closing.is_set)
