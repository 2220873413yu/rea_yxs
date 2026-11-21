"""Clicked public-ID queries over a temporary account-bound hall connection, without world initialization."""
import json
import subprocess
import threading
import uuid
from pathlib import Path
import frida
from account_lock import ensure_account_available
from connection import Connection,ADB
from instance_config import DEVICE
from game_log import GameResponseLog
from player_query import query_player,validate_player_id

ROOT=Path(__file__).resolve().parent


def query_hall_profile(target,cancelled,clear_cache=False):
    """Use local cache or one public-profile exchange; preserve world globals and other bridge hooks."""
    if not clear_cache:target=validate_player_id(target)
    if cancelled():raise InterruptedError('玩家查询已取消')
    ensure_account_available();flags=subprocess.CREATE_NO_WINDOW
    subprocess.run([ADB,'-s',DEVICE,'forward','tcp:27042','tcp:27042'],capture_output=True,check=True,timeout=5,creationflags=flags)
    pid=int(subprocess.check_output([ADB,'-s',DEVICE,'shell','pidof','com.qqgame.mic'],text=True,timeout=5,creationflags=flags).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    client=Connection();client.player_api='_REA_HALL_PROFILE_'+uuid.uuid4().hex
    script=None;lease=client.player_api+'_LEASE'
    try:
        script=session.create_script((ROOT/'bridge.js').read_text(encoding='utf-8'));script.load();client.script=script
        if cancelled():raise InterruptedError('玩家查询已取消')
        # Install and retain in one main-thread chunk so world teardown cannot remove the hook between RPCs.
        hooks=(ROOT/'player_query_ui.lua').read_text(encoding='utf-8')
        script.exports_sync.query('local function install_hooks()\n'+hooks+'\nend\ninstall_hooks();'
            'assert(REA_PLAYER_QUERY_UI and type(REA_PLAYER_QUERY_UI.retain)=="function","旧版查询连接仍在运行，请先关闭旧助手并重启助手");'
            f'REA_PLAYER_QUERY_UI.retain();{lease}=true;return "hall_profile_lease"')
        source=(ROOT/'player_query_runtime.lua').read_text(encoding='utf-8').replace('REA_PLAYER_QUERY=api',client.player_api+'=api')
        script.exports_sync.query(source)
        scope=json.loads(script.exports_sync.query(f'return {client.player_api}.login_context()'))
        if cancelled():raise InterruptedError('玩家查询已取消')
        if clear_cache:
            client.profile_cache.clear(scope)
            return dict(cleared=True,status='已清空当前资料缓存；成员及坐标记录保留，下次查询将重新请求服务器。')
        cached=client.profile_cache.get(scope,user_id=target)
        if cached is not None:return cached
        with client._player_query_scope(cancelled)as check:
            snapshot=query_player(client,GameResponseLog(ADB),target,check)
            identity=client.player_call('identity',target)
        return client._save_player_profile(scope,snapshot,identity)
    finally:
        if script is not None:
            try:script.exports_sync.query(f'{client.player_api}=nil;return "hall_adapter_removed"')
            except Exception:pass
            try:script.exports_sync.query(f'if {lease} and REA_PLAYER_QUERY_UI then REA_PLAYER_QUERY_UI.finish();REA_PLAYER_QUERY_UI.release()end;{lease}=nil;return "hall_profile_released"')
            except Exception:pass
            try:script.exports_sync.close()
            except Exception:pass
            try:script.unload()
            except Exception:pass
        try:session.detach()
        except Exception:pass


class HallProfileSession:
    """Serialize explicit hall queries and share the world worker's manual-query gate when present."""

    def __init__(self,events,query=query_hall_profile):
        """Stay idle until clicked; creating this session never attaches or requests data."""
        self.events=events;self.query=query;self.guard=threading.Lock();self.generation=0
        self.cancel=threading.Event();self.job=None;self.closed=False

    def submit(self,target,worker=None,clear_cache=False):
        """Reserve one clicked operation, excluding concurrent league queries/scans/exports without requiring a map."""
        if not clear_cache:target=validate_player_id(target)
        with self.guard:
            if self.closed:raise RuntimeError('助手正在关闭')
            if self.job is not None and self.job.is_alive():raise RuntimeError('已有玩家查询正在进行')
            if worker is not None:
                with worker.guard:
                    if worker.player_busy:raise RuntimeError('已有玩家、联盟查询或导出正在进行')
                    worker.player_busy=True
            self.cancel=threading.Event();cancel=self.cancel;generation=self.generation
            self.job=threading.Thread(target=self._run,args=(target,worker,clear_cache,generation,cancel),daemon=True)
            try:self.job.start()
            except Exception:
                if worker is not None:
                    with worker.guard:worker.player_busy=False
                raise

    def _run(self,target,worker,clear_cache,generation,cancel):
        """Run once, release the shared gate and tag results against account replacement."""
        try:event=dict(hall_profile_snapshot=self.query(target,cancel.is_set,clear_cache))
        except Exception as error:event=dict(hall_profile_error='查询失败：'+str(error).splitlines()[0][:240])
        finally:
            if worker is not None:
                with worker.guard:worker.player_busy=False
        self.events.put(dict(hall_profile_generation=generation,**event))

    def cancel_pending(self):
        """Invalidate queued work/results when the account changes, leaving world tasks untouched."""
        with self.guard:self.cancel.set();self.generation+=1

    def close(self):
        """Revoke local waits and allow temporary native-hook cleanup before application exit."""
        with self.guard:self.closed=True;self.cancel.set();self.generation+=1

    def pending_shutdown(self):
        """Report thread lifetime only; idle status never queries the game."""
        return self.job is not None and self.job.is_alive()
