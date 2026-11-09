"""Safe public account labels; role hints never replace OAuth identity or authorize an action."""
import unicodedata


def readable_name(value):
    """Remove nonprinting characters and reject names containing only spaces or combining marks."""
    if not isinstance(value, str):
        return ''
    cleaned = ''.join(char for char in value if char.isprintable()).strip()
    return cleaned[:120] if any(unicodedata.category(char)[0] not in 'CMZ' for char in cleaned) else ''


def account_name(account):
    """Prefer a visible account nickname, then a verified cached role name, then a provider-specific label."""
    return (readable_name(account.get('nickname')) or readable_name(account.get('role_name')) or
            ('已保存微信账号' if account.get('provider') == 'wx' else '已保存QQ账号'))
