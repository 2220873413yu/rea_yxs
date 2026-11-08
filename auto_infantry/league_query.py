"""Manual alliance directory and member queries with request/reply attribution and no periodic work."""
import time
from game_log import tags
from game_protocol import JceReader
from player_query import wait_player_receipt


def wait_league_receipt(log,meta,cancelled,timeout=8):
    """Match the actual map/league request before accepting one response; never retry uncertainty."""
    code=meta['code'];sent=False;deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if cancelled():raise InterruptedError('联盟查询已取消')
        for record in log.drain():
            sending=record['tag'].startswith(f's_{code}_')
            receiving=record['tag'].startswith(f'r_{code}_')
            if not sending and not receiving:continue
            d=tags(JceReader(record['body']).fields())
            if sending:
                if meta['scope']=='map':
                    map_id=tags(d.get(0,[]));matched=map_id.get(0)==meta['map_id'] and map_id.get(1)==meta['zone_id']
                else:matched=d.get(0)==meta['league_id']
                if sent or not matched:raise RuntimeError('同时出现其他联盟查询，结果无法归属，请稍后手动重查')
                sent=True
            else:
                if not sent or type(d.get(0)) is not int:raise RuntimeError('联盟查询响应无法归属')
                if d[0]!=0:raise RuntimeError(f'服务器拒绝联盟查询：{d[0]}')
                if meta['scope']=='public'and tags(d.get(1,[])).get(0)!=meta['league_id']:
                    raise RuntimeError('联盟资料与所选联盟不匹配')
                return
        time.sleep(.1)
    raise TimeoutError('联盟查询超时，未自动重试；可稍后手动查询')


def query_league(connection,log,operation,value,cancelled):
    """Each click sends one list, roster or selected-player request; waiting reads local data only."""
    if operation not in {'leagues','roster','member'}:raise ValueError('Invalid league browsing operation')
    if cancelled():raise InterruptedError('联盟查询已取消')
    log.drain();meta=connection.league_query_call(operation,value)
    if operation=='member':wait_player_receipt(log,meta['code'],0,cancelled,owner=True)
    else:wait_league_receipt(log,meta,cancelled)
    snapshot={'leagues':'league_snapshot','roster':'roster_snapshot','member':'member_snapshot'}[operation]
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if cancelled():raise InterruptedError('联盟查询已取消')
        result=connection.league_query_call(snapshot,value)
        if result['ready']:return result
        time.sleep(.1)
    raise TimeoutError('服务器已响应，但新资料尚未确认；未显示旧资料')
