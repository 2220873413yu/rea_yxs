"""Explicit same-PC SDK rekeying; local DPAPI capsule and destination store never replace the source."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

import frida
from account_store import AccountError, crypt_profile, validate_profile

FIELDS = ('access_token', 'refresh_token', 'pf', 'pf_key')
QQ_FIELDS = ('access_token', 'pay_token', 'pf', 'pf_key')
CIPHER_FIELDS = ('access_token', 'refresh_token', 'pay_token', 'pf', 'pf_key')
TABLES = {0: 'wx_login_info', 1: 'qq_login_info'}
AGENT = Path(__file__).with_name('account_rekey_agent.js')
BUNDLE = Path(__file__).with_name('account_rekey_agent.bundle.js')


def cipher_fields(profile):
    """Name the encrypted columns of one platform; QQ stores a pay token instead of a refresh token."""
    return FIELDS if profile['role']['open_platform'] == 0 else QQ_FIELDS


def agent_source():
    """Prefer the committed bundle so a fresh clone needs no npm package; compile only when it is absent."""
    if BUNDLE.is_file():
        return BUNDLE.read_text(encoding='utf-8')
    directory = Path(__file__).resolve().parent.parent / '.analysis-tools/xinyue-tools'
    if not (directory / 'node_modules/frida-java-bridge/package.json').is_file():
        raise AccountError('SDK票据脚本缺失，请重新拉取仓库或按README重新生成agent')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.js', delete=False) as file:
            temporary = Path(file.name)
            file.write(AGENT.read_bytes())
        return frida.Compiler().build(str(temporary))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def transform_sdk(pid, mode, values, endpoint='127.0.0.1:27042'):
    """Run only the SDK cipher against one already-running process; never issue auth or persist SDK rows."""
    if (type(pid) is not int or pid <= 1 or mode not in {'decode', 'encode'} or
            not isinstance(values, dict) or not values or not set(values) <= set(CIPHER_FIELDS)):
        raise AccountError('迁移参数无效，未操作SDK')
    session, script = None, None
    try:
        source = agent_source()
        session = frida.get_device_manager().add_remote_device(endpoint).attach(pid)
        script = session.create_script(source, name='rea-sdk-cipher')
        script.load()
        result = script.exports_sync.transform(mode, values)
        if not result.get('ok') or set(result.get('values', {})) != set(values):
            raise AccountError('SDK迁移解密或回读校验失败，未发起登录')
        return result['values']
    except AccountError:
        raise
    except Exception:
        raise AccountError('SDK迁移连接失败，未发起登录') from None
    finally:
        if script is not None:
            script.unload()
        if session is not None:
            session.detach()


def credential_columns(profile):
    """Validate one saved profile, then read only its platform's SDK-encrypted columns in memory."""
    data = validate_profile(profile)
    fields = cipher_fields(profile)
    with sqlite3.connect(':memory:') as db:
        db.deserialize(data)
        row = db.execute('select ' + ','.join(fields) + ' from ' +
                         TABLES[profile['role']['open_platform']]).fetchone()
    return dict(zip(fields, row))


def seal_source(profile, transform):
    """Seal SDK-decoded bytes with current-user DPAPI only after matching the original token hash."""
    fields = cipher_fields(profile)
    values = transform('decode', credential_columns(profile))
    try:
        token = base64.b64decode(values['access_token'], validate=True)
        if not token or hashlib.sha256(token).hexdigest() != profile['sdk_access_token_sha256']:
            raise ValueError()
        if any(not base64.b64decode(values[field], validate=True) for field in fields):
            raise ValueError()
    except (KeyError, ValueError):
        raise AccountError('源票据校验不一致，未生成迁移数据') from None
    return crypt_profile(json.dumps({'format': 1, 'profile': profile, 'values': values}).encode('utf-8'))


def rekey_destination(blob, transform):
    """Re-encrypt under the destination SDK and return a separate profile, never modifying saved source data."""
    value = json.loads(crypt_profile(blob, True))
    if value.get('format') != 1:
        raise AccountError('迁移数据版本不匹配')
    profile = copy.deepcopy(value['profile'])
    fields = cipher_fields(profile)
    credential_columns(profile)
    values = value['values']
    if set(values) != set(fields):
        raise AccountError('迁移数据版本不匹配')
    token = base64.b64decode(values['access_token'], validate=True)
    if hashlib.sha256(token).hexdigest() != profile['sdk_access_token_sha256']:
        raise AccountError('迁移Token校验失败')
    encrypted = transform('encode', values)
    # A separate decode call proves the destination key can read every transformed field.
    if transform('decode', encrypted) != values:
        raise AccountError('新版SDK票据回读不一致，未写入账号库')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(validate_profile(profile))
        db.execute('update ' + TABLES[profile['role']['open_platform']] + ' set ' +
                   ','.join(field + '=?' for field in fields),
                   tuple(encrypted[field] for field in fields))
        db.commit()
        snapshot = db.serialize()
    profile['database'] = base64.b64encode(snapshot).decode('ascii')
    profile['db_sha256'] = hashlib.sha256(snapshot).hexdigest()
    profile['ticket_status'] = '已保存，切换时验证'
    profile['no_auto_login'] = 1
    validate_profile(profile)
    return profile
