"""One user-triggered lookup/profile exchange, with no background requests or credential persistence."""
import re
import time
from game_log import tags
from game_protocol import JceReader


def validate_player_id(value):
    """Accept decimal public IDs that the native Lua number can represent exactly."""
    text=str(value).strip()
    if not re.fullmatch(r'[0-9]{1,16}',text) or not 0<int(text)<=9007199254740991:
        raise ValueError('请输入有效的数字用户ID')
    return int(text)


def uid_key(value):
    """Compare internal identities in memory only, preserving all four platform/account components."""
    uid=tags(value)
    key=(uid.get(0,0),uid.get(1,''),uid.get(2,0),uid.get(3,0))
    if not key[0] and not key[1]:
        raise RuntimeError('玩家身份字段未返回，未继续查询')
    return key


def wait_player_receipt(log,code,target,cancelled,owner=None,timeout=8):
    """Attribute a single reply to its request and target; refuse overlapping queries without retrying."""
    sent=False;deadline=time.monotonic()+timeout
    require_public_id=owner is True and target>0
    while time.monotonic()<deadline:
        if cancelled():raise InterruptedError('玩家查询已取消')
        for record in log.drain():
            sending=record['tag'].startswith(f's_{code}_')
            receiving=record['tag'].startswith(f'r_{code}_')
            if not sending and not receiving:continue
            d=tags(JceReader(record['body']).fields())
            if sending:
                if owner is True:
                    owner=uid_key(d.get(0,[]))
                matched=d.get(0)==target if owner is None else uid_key(d.get(0,[]))==owner
                if sent or not matched:raise RuntimeError('出现其他玩家查询，无法确认结果归属，请稍后手动重查')
                sent=True
            else:
                if not sent or type(d.get(0)) is not int:raise RuntimeError('玩家查询响应无法归属')
                if owner is None and d.get(1)!=target:raise RuntimeError('用户ID查询响应不匹配')
                if d[0]!=0:
                    stage='用户ID解析' if owner is None else '玩家详情查询'
                    reason='：文本包含不可用内容，请修改再试试' if d[0]==6808 else ''
                    raise RuntimeError(f'服务器拒绝{stage}（{d[0]}）{reason}')
                if owner is None:return uid_key(tags(d.get(2,[])).get(0,[]))
                if require_public_id and d.get(16)!=target:
                    raise RuntimeError('玩家详情用户ID不匹配，未显示')
                if uid_key(tags(d.get(1,[])).get(0,[]))!=owner:raise RuntimeError('玩家详情身份不匹配，未显示')
                return None
        time.sleep(.1)
    raise TimeoutError('玩家查询超时，未自动重试；可稍后点击查询')


def query_player(connection,log,target,cancelled):
    """Fetch fresh details once; skip friend search only for an already verified public-ID mapping."""
    target=validate_player_id(target)
    if cancelled():raise InterruptedError('玩家查询已取消')
    known=connection.player_call('resolve',target)['known']
    log.drain()
    if known:
        owner=True
    else:
        meta=connection.player_call('lookup',target)
        owner=wait_player_receipt(log,meta['code'],target,cancelled)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if cancelled():raise InterruptedError('玩家查询已取消')
        # profile sends once only after the matching lookup cache is ready.
        meta=connection.player_call('profile',target)
        if meta['ready']:break
        time.sleep(.1)
    else:raise TimeoutError('用户ID已查询，但客户端资料尚未更新；未重发')
    wait_player_receipt(log,meta['code'],target,cancelled,owner=owner)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if cancelled():raise InterruptedError('玩家查询已取消')
        result=connection.player_call('snapshot',target)
        if result['ready']:return result
        time.sleep(.1)
    raise TimeoutError('玩家详情已响应，但客户端资料未能确认；未显示旧资料')
