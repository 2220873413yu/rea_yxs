"""Apply an explicit game-platform choice to isolated heart-club request headers, never OAuth credentials."""
from .transport import ServiceError


def request_headers(account, device=None):
    """Copy headers and honor the explicit/persisted platform without changing tokens, cookies or the account."""
    selected = account.get('game_device') if device is None else device
    headers = dict(account['headers'])
    # Legacy records without a choice keep their recorded context; never infer a platform from a role name.
    if selected is None:
        return headers
    if selected not in ('android', 'ios'):
        raise ServiceError('请选择安卓或iOS平台，未发送请求。')
    headers = {key: value for key, value in headers.items() if key.lower() != 't-device-type'}
    headers['T-DEVICE-TYPE'] = selected
    return headers


def account_context(account, device):
    """Scope a role-picker operation to its explicit choice without changing the saved account selection."""
    return {**account, 'game_device': device, 'headers': request_headers(account, device)}
