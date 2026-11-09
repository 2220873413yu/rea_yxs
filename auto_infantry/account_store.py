"""Current-user encrypted SDK profiles; only public role metadata may leave this module for the UI."""
import base64
from contextlib import closing
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET

AUTH_KEYS = {'LastOpenId', 'LastPlatfrom', 'Platform', 'login_type'}
MAX_DATABASE = 8 * 1024 * 1024


class AccountError(RuntimeError):
    """Expose a controlled, credential-free failure message to the account dialog."""


class TicketExpired(AccountError):
    """Stop one restoration and direct the user to native QR authorization instead of retrying."""


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt_profile(payload, decrypt=False):
    """Protect the entire profile with Windows DPAPI for this user; forbid interactive credential dialogs."""
    if not isinstance(payload, bytes) or len(payload) > MAX_DATABASE * 2:
        raise AccountError('本地账号文件大小异常，未读取票据')
    source = ctypes.create_string_buffer(payload)
    src = _Blob(len(payload), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    fn.restype = wintypes.BOOL
    try:
        if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(result)):
            raise AccountError('无法解密本地票据，请使用原Windows用户，或重新扫码保存' if decrypt else '本机票据加密失败，未保存')
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(source, 0, len(payload))
        if result.data:
            ctypes.memset(result.data, 0, result.size)
            kernel = ctypes.WinDLL('kernel32')
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(result.data)


def decode_sdk(value):
    """Decode SDK hex storage only for identifiers/key names; encrypted SDK token columns stay opaque."""
    if not isinstance(value, str):
        return value
    try:
        return bytes.fromhex(value).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return value


def role_name(role):
    """Decode the server's public nickname without treating it as the stable account identity."""
    raw = bytes.fromhex(role.get('nickname_hex', ''))
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('gb18030', errors='replace')


def profile_key(value):
    """Separate SDK identity, QQ/WeChat, mobile platform and protocol zone even for matching nicknames."""
    role = value['role']
    key = [value['openid'], role['open_platform'], role['mobile_platform'], value.get('zone', 1)]
    return hashlib.sha256(json.dumps(key, separators=(',', ':')).encode()).hexdigest()


def validate_profile(value):
    """Validate a decrypted profile fully before it can stop the game or replace SDK storage."""
    try:
        if not isinstance(value, dict) or value.get('format') not in (1, 2):
            raise ValueError()
        role = value['role']
        if (type(role['level']) is not int or not 0 <= role['level'] < 10000 or
                type(role['open_platform']) is not int or role['open_platform'] not in (0, 1) or
                type(role['mobile_platform']) is not int or role['mobile_platform'] not in (0, 1)):
            raise ValueError()
        if len(bytes.fromhex(role['nickname_hex'])) > 512:
            raise ValueError()
        if not isinstance(value['openid'], str) or not 1 <= len(value['openid']) <= 512:
            raise ValueError()
        if type(value.get('zone', 1)) is not int or not 0 <= value.get('zone', 1) <= 100000:
            raise ValueError()
        if type(value['no_auto_login']) is not int or value['no_auto_login'] not in (0, 1):
            raise ValueError()
        saved = value.get('saved_at', 0)
        if type(saved) not in (int, float) or not math.isfinite(saved) or not 0 <= saved < 10**12:
            raise ValueError()
        if 'ticket_status' in value and not isinstance(value['ticket_status'], str):
            raise ValueError()
        for key in ('db_sha256', 'sdk_access_token_sha256'):
            if not re.fullmatch('[0-9a-f]{64}', value[key]):
                raise ValueError()
        encoded = value['database']
        if not isinstance(encoded, str) or len(encoded) > MAX_DATABASE * 3 // 2:
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
        if not data.startswith(b'SQLite format 3\0') or not 4096 <= len(data) <= MAX_DATABASE:
            raise ValueError()
        if hashlib.sha256(data).hexdigest() != value['db_sha256']:
            raise ValueError()
        entries = value['auth_preferences']
        if not isinstance(entries, list) or len(entries) != len(AUTH_KEYS):
            raise ValueError()
        keys = []
        for item in entries:
            if not isinstance(item, str) or len(item) > 8192:
                raise ValueError()
            node = ET.fromstring(item)
            if node.tag != 'string' or list(node):
                raise ValueError()
            keys.append(decode_sdk(node.attrib.get('name', '')))
        if set(keys) != AUTH_KEYS:
            raise ValueError()
        # A profile restores exactly one SDK identity, never a hidden collection of other accounts.
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('pragma temp_store=MEMORY')
            db.deserialize(data)
            if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise ValueError()
            for table, selected in (('qq_login_info', role['open_platform'] == 1),
                                    ('wx_login_info', role['open_platform'] == 0)):
                rows = db.execute('select open_id,access_token from ' + table).fetchall()
                if len(rows) != (1 if selected else 0):
                    raise ValueError()
                if selected and (not rows[0][1] or value['openid'] not in (rows[0][0], decode_sdk(rows[0][0]))):
                    raise ValueError()
        return data
    except (KeyError, TypeError, ValueError, sqlite3.Error, ET.ParseError):
        raise AccountError('本地票据不完整或已损坏，请重新扫码保存') from None


def public_profile(key, value):
    """Return a strict public projection; no SDK IDs, token hashes, database bytes or paths reach widgets."""
    role = value['role']
    return dict(profile_id=key, name=role_name(role), level=role['level'],
                mobile='iOS' if role['mobile_platform'] else '安卓',
                platform='QQ' if role['open_platform'] else '微信',
                open_platform=role['open_platform'], mobile_platform=role['mobile_platform'],
                status=value.get('ticket_status') if value.get('ticket_status') in
                    {'最近登录成功', '需要重新扫码', '已保存，切换时验证'} else '已保存，切换时验证',
                updated=value.get('saved_at', 0))


class AccountStore:
    """Read/write only DPAPI ciphertext outside the repository; each stable identity has one atomic file."""

    def __init__(self, directory=None, cipher=crypt_profile):
        self.directory = Path(directory) if directory else Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'REA_YXS/accounts'
        self.cipher = cipher

    def _path(self, key):
        """Reject caller-controlled paths; the dialog may select only fixed-length profile keys."""
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            raise AccountError('请选择已保存的账号')
        return self.directory / (key + '.dpapi')

    def load(self, key):
        """Decrypt into memory and authenticate the profile key before any game state can be changed."""
        try:
            path = self._path(key)
            if path.stat().st_size > MAX_DATABASE * 2:
                raise AccountError('本地账号文件过大，未读取')
            raw = path.read_bytes()
            value = json.loads(self.cipher(raw, True))
            validate_profile(value)
            if profile_key(value) != key:
                raise AccountError('本地账号标识不一致，请重新扫码保存')
            return value
        except (OSError, ValueError, TypeError):
            raise AccountError('无法读取本地账号，请重新扫码保存') from None

    def save(self, value, status='已保存，切换时验证'):
        """Update the same identity atomically after encryption and readback validation, retaining older files on failure."""
        validate_profile(value)
        value = dict(value, format=2, saved_at=time.time(), ticket_status=status)
        key = profile_key(value)
        path = self._path(key)
        self.directory.mkdir(parents=True, exist_ok=True)
        encrypted = self.cipher(json.dumps(value, separators=(',', ':')).encode(), False)
        if json.loads(self.cipher(encrypted, True)) != value:
            raise AccountError('加密票据回读校验失败，未替换原账号')
        temp = path.with_suffix('.pending')
        try:
            with temp.open('wb') as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            temp.replace(path)
        except OSError:
            raise AccountError('本地票据保存失败，原账号记录仍保留') from None
        finally:
            if temp.exists():
                temp.unlink()
        return public_profile(key, value)

    def mark_scan_required(self, key):
        """Retain the old ciphertext record for replacement by the next successful scan, but never retry it automatically."""
        return self.save(self.load(key), '需要重新扫码')

    def import_profiles(self, values, cancel=None):
        """Stage a fully validated batch in local ciphertext, skip existing identities and roll back new files on failure."""
        from account_lock import account_operation
        from account_migration import check_cancel, validate_batch
        validate_batch(values)
        with account_operation():
            check_cancel(cancel)
            self.directory.mkdir(parents=True, exist_ok=True)
            skipped = 0
            prepared = []
            created = []
            with tempfile.TemporaryDirectory(prefix='.import-', dir=self.directory) as staging:
                try:
                    # Every imported ticket is unverified on this PC; explicit expired marks remain expired.
                    for value in values:
                        check_cancel(cancel)
                        key = profile_key(value)
                        path = self._path(key)
                        if path.exists():
                            skipped += 1
                            continue
                        status = '需要重新扫码' if value.get('ticket_status') == '需要重新扫码' else '已保存，切换时验证'
                        record = dict(value, format=2, saved_at=time.time(), ticket_status=status)
                        encrypted = self.cipher(json.dumps(record, separators=(',', ':')).encode(), False)
                        if json.loads(self.cipher(encrypted, True)) != record:
                            raise AccountError('本机加密回读校验失败，未导入账号')
                        staged = Path(staging) / path.name
                        with staged.open('wb') as output:
                            output.write(encrypted)
                            output.flush()
                            os.fsync(output.fileno())
                        prepared.append((staged, path))
                    check_cancel(cancel)
                    # Create only new names. A competing file cannot be overwritten, even across processes.
                    for staged, path in prepared:
                        os.link(staged, path)
                        created.append(path)
                except Exception:
                    for path in created:
                        path.unlink(missing_ok=True)
                    raise
            return {'imported': len(created), 'skipped': skipped}

    def delete(self, key):
        """Forget one local ciphertext record and block legacy re-import; leave the running game and SDK untouched."""
        from account_lock import account_operation
        with account_operation():
            path = self._path(key)
            try:
                # Persist this first so a restart cannot resurrect the deleted profile from an old experiment.
                path.with_suffix('.deleted').touch(exist_ok=True)
                path.unlink(missing_ok=True)
            except OSError:
                raise AccountError('删除本地账号失败，列表将保留实际仍存在的记录，请稍后重试') from None

    def list(self):
        """Expose public metadata only; a damaged file must not hide healthy saved accounts."""
        result = []
        for path in sorted(self.directory.glob('*.dpapi')):
            if not re.fullmatch('[0-9a-f]{64}', path.stem):
                continue
            try:
                result.append(public_profile(path.stem, self.load(path.stem)))
            except AccountError:
                result.append(dict(profile_id=path.stem, name='无法读取的本地账号', level='—', mobile='—', platform='—',
                                   status='文件损坏或Windows用户不符，请重新扫码', updated=0, unreadable=True))
        return sorted(result, key=lambda row: row['updated'], reverse=True)

    def import_legacy(self, paths):
        """Serialize legacy migration with deletion; never resurrect a forgotten identity from experimental backups."""
        from account_lock import account_operation
        with account_operation():
            self._import_legacy(paths)

    def _import_legacy(self, paths):
        """Read only explicitly supplied backups, preserving newer records and durable deletion markers."""
        for path in paths:
            if not path.exists():
                continue
            try:
                value = json.loads(self.cipher(path.read_bytes(), True))
                validate_profile(value)
                target = self._path(profile_key(value))
                if not target.exists() and not target.with_suffix('.deleted').exists():
                    self.save(value)
            except (OSError, ValueError, AccountError):
                continue
