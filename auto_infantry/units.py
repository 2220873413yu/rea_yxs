"""Verified world-mode troop identities, shared by the UI and controller."""

UNIT_NAMES = {411: '步兵', 412: '弓兵', 413: '骑兵', 803: '斥候'}


def checked_units(units):
    """Validate an explicit nonempty troop selection without coercing unknown identifiers."""
    units = tuple(units)
    selected = tuple(unit for unit in UNIT_NAMES if unit in units)
    if not selected or any(type(unit) is not int or unit not in UNIT_NAMES for unit in units):
        raise ValueError('请至少勾选一个受支持的兵种')
    return selected
