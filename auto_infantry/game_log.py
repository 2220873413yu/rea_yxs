"""Verify the game's existing network log without retaining account data or retrying actions."""
import re
import subprocess
import time

from game_protocol import JceReader, read_records


def tags(fields):
    """Access bounded decoded JCE values by protocol tag rather than Lua declaration order."""
    return {field['tag']: field['value'] for field in fields}


def record_end(record):
    """Locate the end of a complete record while leaving a concurrent partial tail untouched."""
    return record['offset'] + 1 + len(record['tag']) + 1 + len(record['timestamp']) + 4 + len(record['body'])


class TrainingRejected(RuntimeError):
    """Carry an attributed server rejection even when the native model discards failed responses."""

    def __init__(self, unit, ret):
        self.unit, self.ret = unit, ret
        super().__init__(f'服务器拒绝训练：{ret}（兵种{unit}）')


class ResourceMissing(RuntimeError):
    """Represent an attributed6001 resource-detail response, never a cache miss or generic failure."""

    def __init__(self, target_id):
        self.target_id = target_id
        self.ret = 6001
        super().__init__(f'服务器确认资源田不存在：{target_id}（6001）')


class HuntRejected(RuntimeError):
    """Carry a definitive ordinary hunting rejection without treating it as permission to retry."""

    def __init__(self, ret):
        self.ret = ret
        super().__init__(f'服务器拒绝打野：{ret}')


class BeaconRejected(RuntimeError):
    """Carry a rejection only after matching the exact beacon request; timeout and foreign traffic cannot create it."""

    def __init__(self, operation, event_id, ret):
        self.operation,self.event_id,self.ret=operation,event_id,ret
        super().__init__(f'服务器拒绝烽火台{operation}：{ret}')


class BeaconCapacityUnavailable(RuntimeError):
    """The final native guard explicitly returned without sending because beacon capacity was full."""


class GameResponseLog:
    """Bind one current log stream and match a single ordinary collection request and its response."""

    def __init__(self, adb, device='emulator-5554'):
        """Skip historical traffic using a bounded tail, retaining any incomplete frame for later drains."""
        self.adb = adb
        self.device = device
        folder = '/storage/emulated/0/Android/data/com.qqgame.mic/files/YXS/net'
        dates = self.read('shell', 'ls', '-t', folder).decode('ascii').split()
        date = next(value for value in dates if re.fullmatch(r'\d{4}_\d{2}_\d{2}', value))
        names = self.read('shell', 'ls', '-t', folder + '/' + date).decode('ascii').split()
        name = next(value for value in names if re.fullmatch(r'\d{2}_\d{2}_\d{2}', value))
        self.path = folder + '/' + date + '/' + name
        size = int(self.read('shell', 'stat', '-c', '%s', self.path).strip())
        if size == 4:
            self.cursor = 4
            return
        offset = max(0, (size - 524288) // 4096) * 4096
        # LDPlayer14's bare dd entry reports "no such tool"; select the available Toybox applet explicitly.
        blob = self.read('exec-out', 'toybox', 'dd', 'if=' + self.path, 'bs=4096',
                         'skip=' + str(offset // 4096), 'count=129')
        for match in re.finditer(rb'[sr]_\d+_\w+', blob):
            at = match.start()
            if at == 0 or blob[at - 1] != len(match.group()):
                continue
            start = at - 1
            try:
                records = read_records(bytes.fromhex('0100ffff') + blob[start:])
            except (ValueError, UnicodeError, AssertionError):
                continue
            if records:
                self.cursor = offset + start + record_end(records[-1]) - 4
                return
        raise RuntimeError('无法定位游戏日志的完整记录，未发送请求')

    def read(self, *arguments):
        """Read binary emulator logs through hidden ADB children, avoiding console flashes under pythonw."""
        return subprocess.check_output([self.adb, '-s', self.device, *arguments], timeout=5,
                                       creationflags=subprocess.CREATE_NO_WINDOW)

    def drain(self):
        """Advance over complete existing records before dispatch, preserving a partial record for later."""
        data = self.read('exec-out', 'tail', '-c', '+' + str(self.cursor + 1), self.path)
        records = read_records(bytes.fromhex('0100ffff') + data)
        if records:
            self.cursor += record_end(records[-1]) - 4
        return records

    def wait_beacon(self, operation, event_id, hero_id=None, army_id=None, timeout=6):
        """Attribute one rescue departure/recall/claim to its exact wire request, without any resend path."""
        codes = {'dispatch':11010, 'recall':11008, 'claim':11043}
        if operation not in codes:
            raise ValueError('Invalid beacon action')
        code = codes[operation]
        sent = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for record in self.drain():
                sending = record['tag'].startswith(f's_{code}_')
                receiving = record['tag'].startswith(f'r_{code}_')
                if not sending and not receiving:
                    continue
                data = tags(JceReader(record['body']).fields())
                if sending:
                    if operation == 'dispatch':
                        owned = tags(data[0])[0] == hero_id and data[1] == 45 and data[3] == event_id
                    else:
                        owned = data[0] == (army_id if operation == 'recall' else event_id)
                    if sent or not owned:
                        raise RuntimeError('同时出现其他烽火台动作，结果无法归属；不自动重发')
                    sent = True
                    continue
                if not sent:
                    raise RuntimeError('烽火台响应不属于本次请求；不自动重发')
                if data[0] != 0:
                    raise BeaconRejected(operation,event_id,data[0])
                result = dict(ret=0, event_id=event_id, operation=operation)
                if operation == 'dispatch':
                    army = tags(tags(data[1])[0])
                    if tags(army[15])[0] != hero_id or army[5] != 45 or army[6] != event_id:
                        raise RuntimeError('烽火台出征响应的英雄或目标不匹配')
                    result.update(army_id=army[0], hero_id=hero_id, state=army[4], end_ms=army[11])
                elif operation == 'recall':
                    if data[1] != army_id:
                        raise RuntimeError('烽火台撤回响应队伍不匹配')
                    result['army_id'] = army_id
                else:
                    event = tags(data[1])
                    if tags(event[0])[1] != event_id:
                        raise RuntimeError('烽火台领奖响应事件不匹配')
                    goods = tags(data[2])
                    for tag, name in ((5, 'items'), (18, 'resources')):
                        result[name] = [dict(id=tags(row['value'])[0], count=tags(row['value'])[1])
                                        for row in goods.get(tag, [])]
                return result
            time.sleep(.1)
        raise TimeoutError('烽火台动作结果不明，已停止且不自动重发')

    def wait_beacon_scout(self, x, y, timeout=6):
        """Match one11014 destination and its returned path; an accepted scout is not a completed event."""
        deadline,sent=time.monotonic()+timeout,False
        while time.monotonic()<deadline:
            for record in self.drain():
                sending=record['tag'].startswith('s_11014_')
                receiving=record['tag'].startswith('r_11014_')
                if not sending and not receiving:
                    continue
                data=tags(JceReader(record['body']).fields())
                if sending:
                    destination=tags(data[1])
                    if sent or (destination.get(0),destination.get(1))!=(x,y):
                        raise RuntimeError('侦察请求目标无法归属，不重发')
                    sent=True
                    continue
                if not sent or data[0]!=0:
                    raise RuntimeError('侦察响应未确认成功或无法归属，不重发')
                info=tags(data[1]);path=info[2]
                if not path or (tags(path[-1]['value']).get(0),tags(path[-1]['value']).get(1))!=(x,y):
                    raise RuntimeError('侦察返回路径与目标不符，不重发')
                if not isinstance(info.get(1),(int,float)) or info[1]<=0:
                    raise RuntimeError('侦察返回结束时间无效，不重发')
                return dict(ret=0,logic_x=x,logic_y=y,end_ms=info[1])
            time.sleep(.1)
        raise TimeoutError('侦察结果不明，已停止且不自动重发')

    def wait_collection(self, hero_id, target_id, timeout=6):
        """Require this request's hero/target and a successful corresponding army response; never resubmit."""
        deadline = time.monotonic() + timeout
        sent = False
        while time.monotonic() < deadline:
            for record in self.drain():
                if record['tag'].startswith('s_11010_'):
                    data = tags(JceReader(record['body']).fields())
                    army = tags(data[0])
                    if sent or army[0] != hero_id or data[1] != 1 or data[3] != target_id:
                        raise RuntimeError('同时出现其他出征请求，采集结果无法归属，已停止')
                    sent = True
                elif record['tag'].startswith('r_11010_'):
                    if not sent:
                        raise RuntimeError('收到不属于当前采集请求的响应，已停止')
                    data = tags(JceReader(record['body']).fields())
                    if data[0] != 0:
                        raise RuntimeError(f'服务器拒绝采集：{data[0]}')
                    army = tags(tags(data[1])[0])
                    identity = tags(army[15])
                    if identity[0] != hero_id or army[5] != 1 or army[6] != target_id:
                        raise RuntimeError('采集响应的英雄或目标不符，已停止')
                    return {'hero_id': hero_id, 'target_id': target_id, 'army_id': army[0], 'ret': 0}
            time.sleep(.1)
        raise TimeoutError('采集出征结果不明，已停止且不会自动重发')

    def wait_league(self, hero_id, target_id, secondary_target, timeout=6):
        """Attribute one native aim12 departure and its reply; never infer acceptance from cached state alone."""
        deadline, sent = time.monotonic() + timeout, False
        while time.monotonic() < deadline:
            for record in self.drain():
                if record['tag'].startswith('s_11010_'):
                    data = tags(JceReader(record['body']).fields())
                    if (sent or tags(data[0])[0] != hero_id or data[1] != 12 or
                            data[3] != target_id or data.get(4, 0) != secondary_target):
                        raise RuntimeError('同时出现其他出征，联盟采集结果无法归属，不重发')
                    sent = True
                elif record['tag'].startswith('r_11010_'):
                    if not sent:
                        raise RuntimeError('联盟采集出征响应无法归属，不重发')
                    data = tags(JceReader(record['body']).fields())
                    if data[0] != 0:
                        raise RuntimeError(f'服务器拒绝联盟采集：{data[0]}')
                    army = tags(tags(data[1])[0])
                    if tags(army[15])[0] != hero_id or army[5] != 12 or army[6] != target_id:
                        raise RuntimeError('联盟采集响应的英雄或目标不符，不重发')
                    return {'ret': 0, 'hero_id': hero_id, 'target_id': target_id, 'army_id': army[0]}
            time.sleep(.1)
        raise TimeoutError('联盟采集出征结果不明，已停止且不会自动重发')

    def wait_training(self, unit, timeout=6):
        """Match one11029 request and response, including errors omitted from the game's success cache."""
        deadline, sent = time.monotonic() + timeout, False
        while time.monotonic() < deadline:
            for record in self.drain():
                if record['tag'].startswith('s_11029_'):
                    data = tags(JceReader(record['body']).fields())
                    if sent or data.get(0) != unit:
                        raise RuntimeError('同时出现其他训练请求，结果无法归属，已停止')
                    sent = True
                elif record['tag'].startswith('r_11029_'):
                    if not sent:
                        raise RuntimeError('收到不属于当前训练请求的响应，已停止')
                    data = tags(JceReader(record['body']).fields())
                    if data[0] != 0:
                        raise TrainingRejected(unit, data[0])
                    if data.get(1) != unit:
                        raise RuntimeError('响应兵种与请求不一致，已停止；请勿同时手动训练')
                    return {'ret': 0, 'soldier_id': unit}
            time.sleep(.1)
        raise TimeoutError('训练结果未确认，已停止且不会自动重发')

    def wait_hunt(self, hero_id, target_id, timeout=6):
        """Match one aim3 departure and its exact accepted army; keep identities and unrelated data out of logs."""
        deadline, sent = time.monotonic() + timeout, False
        while time.monotonic() < deadline:
            for record in self.drain():
                if record['tag'].startswith('s_11010_'):
                    data = tags(JceReader(record['body']).fields())
                    if sent or tags(data[0])[0] != hero_id or data[1] != 3 or data[3] != target_id:
                        raise RuntimeError('同时出现其他出征，打野结果无法归属，不重发')
                    sent = True
                elif record['tag'].startswith('r_11010_'):
                    if not sent:
                        raise RuntimeError('打野出征响应无法归属，不重发')
                    data = tags(JceReader(record['body']).fields())
                    if data[0] != 0:
                        raise HuntRejected(data[0])
                    army = tags(tags(data[1])[0])
                    if tags(army[15])[0] != hero_id or army[5] != 3 or army[6] != target_id:
                        raise RuntimeError('打野响应的英雄或目标不符，不重发')
                    return {'ret': 0, 'hero_id': hero_id, 'target_id': target_id, 'army_id': army[0]}
            time.sleep(.1)
        raise TimeoutError('打野出征结果不明，已停止且不会自动重发')

    def wait_hunt_skip(self, army_id, target_id, timeout=6, expected_aim=3):
        """Match native11006 completion for the exact ordinary3 or beacon45 army and retain win flags."""
        if expected_aim not in (3,45):
            raise ValueError('Invalid quick-combat aim')
        deadline, sent = time.monotonic() + timeout, False
        while time.monotonic() < deadline:
            for record in self.drain():
                if record['tag'].startswith('s_11006_'):
                    d = tags(JceReader(record['body']).fields())
                    if sent or d[0] != target_id or d[1] != army_id or d[2] != expected_aim or d.get(4) not in (1, True):
                        raise RuntimeError('同时出现其他进入或跳过战斗请求，结果无法归属')
                    sent = True
                elif record['tag'].startswith('r_11006_'):
                    if not sent:
                        raise RuntimeError('跳过战斗响应无法归属，不重发')
                    d = tags(JceReader(record['body']).fields())
                    if d[0] != 0:
                        raise HuntRejected(d[0])
                    if d[1] != target_id or d[2] != army_id or d[3] != expected_aim or d.get(7) not in (1, True):
                        raise RuntimeError('跳过战斗结果未完成或与请求不符，不重发')
                    if d.get(8) not in (0, 1):
                        raise RuntimeError('跳过战斗胜负标记缺失，不重发')
                    return {'ret': 0, 'army_id': army_id, 'target_id': target_id, 'won': d.get(8) in (1, True)}
            time.sleep(.1)
        raise TimeoutError('跳过战斗结果不明，已停止且不会自动重发')

    def wait_resource_detail(self, target_id, timeout=6):
        """Attribute one11020 reply before treating6001 as permission to remove a saved coordinate."""
        deadline, sent = time.monotonic() + timeout, False
        while time.monotonic() < deadline:
            for record in self.drain():
                if record['tag'].startswith('s_11020_'):
                    data = tags(JceReader(record['body']).fields())
                    if sent or data.get(0) != target_id:
                        raise RuntimeError('同时出现其他资源查询，结果无法归属，未删除坐标')
                    sent = True
                elif record['tag'].startswith('r_11020_'):
                    if not sent:
                        raise RuntimeError('收到不属于当前资源查询的响应，未删除坐标')
                    data = tags(JceReader(record['body']).fields())
                    if data[0] == 6001:
                        raise ResourceMissing(target_id)
                    if data[0] != 0:
                        raise RuntimeError(f'资源查询失败：{data[0]}，未删除坐标')
                    point = tags(tags(data[1])[0])
                    if tags(point[0]).get(1) != target_id:
                        raise RuntimeError('资源查询响应目标不符，未删除坐标')
                    return
            time.sleep(.1)
        raise TimeoutError('资源查询超时，未删除坐标')
