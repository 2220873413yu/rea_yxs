"""Portable plaintext-ticket migration: decode the SDK columns once, re-encrypt on the destination PC."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from account_migration import MAX_PAYLOAD, MAX_PROFILES, check_cancel
from account_rekey import FIELDS, credential_columns, transform_sdk
from account_store import AccountError, validate_profile

PLAIN_KEY = 'sdk_plain'
PLAIN_HASH = 'sdk_plain_sha256'
TABLES = {0: 'wx_login_info', 1: 'qq_login_info'}


def values_digest(values):
    """Bind the four decoded columns so a hand-edited migration file cannot reach the SDK."""
    payload = json.dumps(values, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def decode_columns(profile, transform):
    """Decode one saved profile's four SDK columns; the token must still match its recorded hash."""
    validate_profile(profile)
    values = transform('decode', credential_columns(profile))
    if not isinstance(values, dict) or set(values) != set(FIELDS):
        raise AccountError('SDK票据解码结果异常，未导出可移植凭据')
    try:
        token = base64.b64decode(values['access_token'], validate=True)
        empty = [field for field in FIELDS if not base64.b64decode(values[field], validate=True)]
    except (KeyError, ValueError):
        raise AccountError('SDK票据解码结果异常，未导出可移植凭据') from None
    if not token or empty:
        raise AccountError('SDK票据不完整，未导出可移植凭据')
    if hashlib.sha256(token).hexdigest() != profile['sdk_access_token_sha256']:
        raise AccountError('SDK票据与本机账号记录不一致，未导出可移植凭据')
    return values


def portable_profile(profile, transform):
    """Return a copy carrying both the original snapshot and its decoded, hash-bound ticket columns."""
    values = decode_columns(profile, transform)
    return dict(profile, **{PLAIN_KEY: values, PLAIN_HASH: values_digest(values)})


def needs_rekey(profile):
    """Recognise an imported portable profile that this PC's SDK key cannot read yet."""
    return isinstance(profile, dict) and isinstance(profile.get(PLAIN_KEY), dict)


def rekey_profile(profile, transform):
    """Re-encrypt an exported ticket with this PC's SDK key and drop the plaintext from the result."""
    values = profile.get(PLAIN_KEY)
    if not isinstance(values, dict) or set(values) != set(FIELDS):
        raise AccountError('可移植票据不完整，未写入本机SDK')
    if profile.get(PLAIN_HASH) != values_digest(values):
        raise AccountError('可移植票据校验失败，未写入本机SDK')
    try:
        token = base64.b64decode(values['access_token'], validate=True)
    except ValueError:
        raise AccountError('可移植票据Token格式异常，未写入本机SDK') from None
    if not token or hashlib.sha256(token).hexdigest() != profile['sdk_access_token_sha256']:
        raise AccountError('可移植票据Token校验失败，未写入本机SDK')
    encrypted = transform('encode', values)
    # A separate decode call proves this SDK key can read every transformed column back.
    if transform('decode', encrypted) != values:
        raise AccountError('本机SDK回读不一致，未写入账号库')
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(validate_profile(profile))
        db.execute('update ' + TABLES[profile['role']['open_platform']] +
                   ' set access_token=?,refresh_token=?,pf=?,pf_key=?',
                   tuple(encrypted[field] for field in FIELDS))
        db.commit()
        snapshot = bytearray(db.serialize())
    except sqlite3.Error:
        raise AccountError('SDK票据写入失败，原账号未替换') from None
    finally:
        db.close()
    snapshot[18:20] = b'\x01\x01'
    snapshot = bytes(snapshot)
    result = dict(profile, database=base64.b64encode(snapshot).decode(),
                  db_sha256=hashlib.sha256(snapshot).hexdigest(),
                  ticket_status='已保存，切换时验证', no_auto_login=1)
    result.pop(PLAIN_KEY, None)
    result.pop(PLAIN_HASH, None)
    validate_profile(result)
    return result


def live_transform(transport=None):
    """Bind the SDK cipher to the currently running client; no login, restart or account selection happens."""
    from account_transport import AccountTransport
    transport = transport or AccountTransport()
    pid = transport.pid()
    if not pid or not str(pid).isdigit():
        raise AccountError('请先在本机打开游戏并停在登录页，再导出可移植凭据')
    return lambda mode, values: transform_sdk(int(pid), mode, values)


def write_atomic(destination, blob):
    """Publish one validated file atomically; an existing file survives any failure."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.yxs-portable-', delete=False) as output:
            temporary = Path(output.name)
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    except OSError:
        raise AccountError('迁移文件保存失败，原文件未替换') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_portable(store, keys, destination, cancel=None, transform=None):
    """Write selected profiles with decoded tickets; the running client supplies only the SDK cipher."""
    if (not isinstance(keys, (tuple, list)) or not 1 <= len(keys) <= MAX_PROFILES or
            any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys)):
        raise AccountError('请选择1～50个不同的账号导出')
    destination = Path(destination)
    if destination.suffix.lower() != '.yxsaccounts':
        raise AccountError('迁移文件请使用 .yxsaccounts 后缀，以便识别并排除Git提交')
    if destination.resolve().is_relative_to(store.directory.resolve()):
        raise AccountError('请将迁移文件保存在账号库目录之外')
    check_cancel(cancel)
    if transform is None:
        transform = live_transform()
    from account_lock import account_operation
    with account_operation():
        values = [portable_profile(store.load(key), transform) for key in keys]
    blob = json.dumps({'format': 2, 'portable': 1, 'profiles': values},
                      ensure_ascii=False, indent=2).encode('utf-8')
    if len(blob) > MAX_PAYLOAD:
        raise AccountError('所选账号数据超过64MiB，请分批导出')
    check_cancel(cancel)
    write_atomic(destination, blob)
    return {'exported': len(values)}
