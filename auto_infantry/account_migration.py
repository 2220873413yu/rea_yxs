"""Password-encrypted portable account archives; decrypted tickets stay in memory until local DPAPI storage."""
import json
import os
from pathlib import Path
import tempfile

from account_store import AccountError, profile_key, validate_profile
from account_lock import account_operation

MAGIC = b'REA-YXS-ACCOUNTS\x01'
SALT_SIZE = 16
NONCE_SIZE = 12
HEADER_SIZE = len(MAGIC) + SALT_SIZE + NONCE_SIZE
MAX_PROFILES = 50
MAX_PAYLOAD = 64 * 1024 * 1024
MAX_FILE = HEADER_SIZE + MAX_PAYLOAD + 16
MIN_PASSWORD = 12


def check_cancel(cancel):
    """Cancel before a file transaction; never interrupt the commit of an already validated batch."""
    if cancel is not None and cancel.is_set():
        raise InterruptedError('账号迁移已取消，自动功能保持关闭')


def password_bytes(password):
    """Require an explicit portable password without trimming or normalizing its exact Unicode spelling."""
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= 1024:
        raise AccountError('迁移密码需为12～1024个字符；请妥善记住，不会保存密码')
    try:
        return password.encode('utf-8')
    except UnicodeError:
        raise AccountError('迁移密码包含无法编码的字符') from None


def crypto():
    """Load the authenticated encryption dependency only when migration is explicitly requested."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        from cryptography.exceptions import InvalidTag
    except ImportError:
        raise AccountError('缺少账号迁移加密组件，请按README安装 requirements.txt 后重试') from None
    return AESGCM, Scrypt, InvalidTag


def validate_batch(values):
    """Reject malformed, duplicate or excessive identities before any destination profile can be written."""
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_PROFILES:
        raise AccountError('迁移文件必须包含1～50个账号')
    seen = set()
    for value in values:
        validate_profile(value)
        key = profile_key(value)
        if key in seen:
            raise AccountError('迁移文件包含重复账号，未导入')
        seen.add(key)
    return values


def encrypt_archive(values, password):
    """Seal one complete batch using a fresh salt/nonce, scrypt and AES-256-GCM including header integrity."""
    secret = password_bytes(password)
    validate_batch(values)
    payload = json.dumps({'format': 1, 'profiles': values}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_PAYLOAD:
        raise AccountError('所选账号数据超过64MiB，请分批导出')
    AESGCM, Scrypt, _ = crypto()
    salt, nonce = os.urandom(SALT_SIZE), os.urandom(NONCE_SIZE)
    header = MAGIC + salt + nonce
    key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(secret)
    return header + AESGCM(key).encrypt(nonce, payload, header)


def decrypt_archive(blob, password):
    """Authenticate a bounded versioned archive and validate every profile before returning in-memory tickets."""
    secret = password_bytes(password)
    if (not isinstance(blob, bytes) or not HEADER_SIZE + 16 < len(blob) <= MAX_FILE or
            not blob.startswith(MAGIC)):
        raise AccountError('不是受支持的账号迁移文件，或文件大小异常')
    AESGCM, Scrypt, InvalidTag = crypto()
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE:HEADER_SIZE]
    key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(secret)
    try:
        payload = AESGCM(key).decrypt(nonce, blob[HEADER_SIZE:], blob[:HEADER_SIZE])
    except InvalidTag:
        raise AccountError('密码错误或迁移文件已损坏，未导入任何账号') from None
    try:
        value = json.loads(payload)
        if not isinstance(value, dict) or type(value.get('format')) is not int or value['format'] != 1:
            raise ValueError()
        return validate_batch(value['profiles'])
    except (ValueError, KeyError, RecursionError):
        raise AccountError('迁移文件内容格式异常，未导入任何账号') from None


def export_accounts(store, keys, destination, password, cancel=None):
    """Read only selected profiles, then atomically write ciphertext; no plaintext temporary files or game calls."""
    password_bytes(password)
    if (not isinstance(keys, (tuple, list)) or not 1 <= len(keys) <= MAX_PROFILES or
            any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys)):
        raise AccountError('请选择1～50个不同的账号导出')
    destination = Path(destination)
    if destination.suffix.lower() != '.yxsaccounts':
        raise AccountError('迁移文件请使用 .yxsaccounts 后缀，以便识别并排除Git提交')
    if destination.resolve().is_relative_to(store.directory.resolve()):
        raise AccountError('请将迁移文件保存在账号库目录之外')
    check_cancel(cancel)
    with account_operation():
        values = [store.load(key) for key in keys]
    blob = encrypt_archive(values, password)
    check_cancel(cancel)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.yxs-export-', delete=False) as output:
            temporary = Path(output.name)
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
        check_cancel(cancel)
        temporary.replace(destination)
    except OSError:
        raise AccountError('迁移文件保存失败，原文件未替换') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'exported': len(values)}


def import_accounts(store, source, password, cancel=None):
    """Decrypt locally and hand validated profiles to the atomic DPAPI importer without restoring or logging in."""
    password_bytes(password)
    check_cancel(cancel)
    try:
        with Path(source).open('rb') as file:
            blob = file.read(MAX_FILE + 1)
    except OSError:
        raise AccountError('无法读取账号迁移文件') from None
    values = decrypt_archive(blob, password)
    check_cancel(cancel)
    try:
        return store.import_profiles(values, cancel)
    except OSError:
        raise AccountError('本机账号库写入失败，请检查账号列表及目录权限；未登录游戏') from None
