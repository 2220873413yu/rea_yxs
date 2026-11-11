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
ROOT = Path(__file__).resolve().parent.parent


def transform_sdk(pid, mode, values, endpoint='127.0.0.1:27042'):
    """Run only the SDK cipher against one already-running process; never issue auth or persist SDK rows."""
    if type(pid) is not int or pid <= 1 or mode not in {'decode', 'encode'} or set(values) != set(FIELDS):
        raise AccountError('迁移参数无效，未操作SDK')
    directory = ROOT / '.analysis-tools/xinyue-tools'
    if not (directory / 'node_modules/frida-java-bridge/index.js').is_file():
        raise AccountError('缺少本地Java桥，未操作SDK')
    temporary, session, script = None, None, None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.js', delete=False) as file:
            temporary = Path(file.name)
            file.write(Path(__file__).with_name('account_rekey_agent.js').read_bytes())
        compiled = frida.Compiler().build(str(temporary))
        session = frida.get_device_manager().add_remote_device(endpoint).attach(pid)
        script = session.create_script(compiled)
        script.load()
        result = script.exports_sync.transform(mode, values)
        if not result.get('ok') or set(result.get('values', {})) != set(FIELDS):
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
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def credential_columns(profile):
    """Validate one saved WeChat profile before reading its four SDK-encrypted columns in memory."""
    data = validate_profile(profile)
    if profile['role']['open_platform'] != 0:
        raise AccountError('本次迁移仅支持已验证的微信票据')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(data)
        row = db.execute('select access_token,refresh_token,pf,pf_key from wx_login_info').fetchone()
    return dict(zip(FIELDS, row))


def seal_source(profile, transform):
    """Seal SDK-decoded bytes with current-user DPAPI only after matching the original token hash."""
    values = transform('decode', credential_columns(profile))
    try:
        token = base64.b64decode(values['access_token'], validate=True)
        if not token or hashlib.sha256(token).hexdigest() != profile['sdk_access_token_sha256']:
            raise ValueError()
        if any(not base64.b64decode(values[field], validate=True) for field in FIELDS):
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
    credential_columns(profile)
    values = value['values']
    token = base64.b64decode(values['access_token'], validate=True)
    if hashlib.sha256(token).hexdigest() != profile['sdk_access_token_sha256']:
        raise AccountError('迁移Token校验失败')
    encrypted = transform('encode', values)
    # A separate decode call proves the destination key can read every transformed field.
    if transform('decode', encrypted) != values:
        raise AccountError('新版SDK票据回读不一致，未写入账号库')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(validate_profile(profile))
        db.execute('update wx_login_info set access_token=?,refresh_token=?,pf=?,pf_key=?',
                   tuple(encrypted[field] for field in FIELDS))
        db.commit()
        snapshot = db.serialize()
    profile['database'] = base64.b64encode(snapshot).decode('ascii')
    profile['db_sha256'] = hashlib.sha256(snapshot).hexdigest()
    profile['ticket_status'] = '已保存，切换时验证'
    profile['no_auto_login'] = 1
    validate_profile(profile)
    return profile
