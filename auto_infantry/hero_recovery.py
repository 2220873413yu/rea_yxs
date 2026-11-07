"""Selected-hero eligibility, fair scheduling and confirmed-result checks."""
from hero_preferences import checked_heroes


def recovery_decision(state, expected_hero_id=None):
    """Allow one item only for the expected owned, fresh and idle hero with a positive countdown."""
    hero_id = state.get('hero_id')
    name = state.get('name', str(hero_id))
    if (type(hero_id) is not int or not 0 < hero_id <= 10000000 or not state.get('found') or
            (expected_hero_id is not None and hero_id != expected_hero_id)):
        return 'wait', '未读取到对应英雄，等待数据'
    if not state.get('fresh') or not state.get('army_known'):
        return 'wait', '英雄或部队数据不明，暂不恢复'
    if state.get('hero_state') != 0 or state.get('busy'):
        return 'wait', f"{name}出战或活动中（状态 {state.get('hero_state')}），等待"
    if state.get('remaining_ms', 0) <= 0:
        return 'wait', f'{name}无需恢复，等待下一轮'
    if state.get('items', 0) <= 0:
        raise RuntimeError('五分钟英雄恢复加速已用完')
    return 'speed', f'正在为{name}使用一个五分钟恢复加速'


def choose_recovery(roster, selected, cursor):
    """Rotate through explicit selections, skipping missing/busy heroes without auto-selecting newcomers."""
    selected = checked_heroes(selected)
    by_id = {state['hero_id']: state for state in roster['heroes']}
    if len(by_id) != len(roster['heroes']):
        raise RuntimeError('英雄名单存在重复标识，已停止')
    for offset in range(len(selected)):
        index = (cursor + offset) % len(selected)
        hero_id = selected[index]
        state = by_id.get(hero_id)
        if state is not None:
            action, message = recovery_decision(state, hero_id)
            if action == 'speed':
                return state, (index + 1) % len(selected), message
    return None, cursor, '所选英雄正在活动、无需恢复或数据不明，等待下一轮'


def verify_recovery(before, after):
    """Require one-item consumption and an earlier finish, rather than accepting elapsed time alone."""
    if after.get('hero_id') != before.get('hero_id') or not after.get('found') or not after.get('fresh'):
        raise RuntimeError('恢复后英雄数据无法确认，已停止')
    if after['items'] != before['items'] - 1:
        raise RuntimeError('恢复道具扣量与预期不符，已停止')
    # A busy hero could have entered combat while the response was in flight.
    if after.get('hero_state') != 0 or after.get('busy') or not after.get('army_known'):
        raise RuntimeError('恢复期间英雄活动状态发生变化，已停止')
    expected = min(300000, before['remaining_ms'])
    if after['remaining_ms'] > 0 and before['finish_ms'] - after['finish_ms'] < expected - 2000:
        raise RuntimeError('未确认五分钟恢复效果，已停止')
