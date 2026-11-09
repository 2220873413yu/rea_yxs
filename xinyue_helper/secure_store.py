"""Current-Windows-user encrypted account records; raw credentials never enter public projections."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .labels import readable_name,account_name


class StoreError(RuntimeError):
    """A credential-free storage failure safe to display in the desktop UI."""


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    """Protect the entire account using Windows DPAPI and forbid interactive credential prompts."""
    if os.name != 'nt' or not isinstance(data, bytes) or len(data) > 256 * 1024:
        raise StoreError('账号加密环境或文件大小异常')
    source = ctypes.create_string_buffer(data)
    blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    method = library.CryptUnprotectData if decrypt else library.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    try:
        if not method(ctypes.byref(blob), None, None, None, None, 1, ctypes.byref(output)):
            raise StoreError('账号无法解密，请使用原Windows用户或重新扫码' if decrypt else '本机账号加密失败')
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(source, 0, len(data))
        if output.data:
            ctypes.memset(output.data, 0, output.size)
            kernel = ctypes.WinDLL('kernel32')
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(output.data)


def validate(value):
    """Validate account identity and header consistency before it can reach an API request."""
    if not isinstance(value, dict) or value.get('format') != 1 or value.get('provider') not in ('qq', 'wx'):
        raise StoreError('账号记录格式不正确')
    headers = value.get('headers')
    if not isinstance(headers, dict) or not 1 <= len(headers) <= 100:
        raise StoreError('账号登录上下文不完整')
    for key, item in headers.items():
        if not isinstance(key, str) or not isinstance(item, str) or len(key)>100 or len(item)>16384 or '\r' in key+item or '\n' in key+item:
            raise StoreError('账号请求头格式异常')
    lower = {key.lower(): item for key, item in headers.items()}
    if not all(lower.get(key) for key in ('t-access-token','t-openid','t-appid','t-account-type','cookie')):
        raise StoreError('账号缺少必要的登录信息')
    expected_type = 'qc' if value['provider'] == 'qq' else 'wx'
    if lower['t-account-type'] != expected_type:
        raise StoreError('账号登录方式与凭据不一致')
    return value


class AccountStore:
    """Keep one encrypted file per provider/OpenID without a plaintext account database."""
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/accounts'

    def save(self, credentials, headers, nickname=''):
        """Encrypt before touching disk, atomically replace the same account, and return a safe public row."""
        key = hashlib.sha256((credentials.provider+'\0'+credentials.openid).encode()).hexdigest()
        value = validate({'format':1,'profile_id':key,'provider':credentials.provider,'nickname':nickname or credentials.nickname,
            'saved_at':datetime.now(timezone.utc).isoformat(),'expires_at':credentials.expires_at,
            'headers':headers,'refresh_token':credentials.refresh_token})
        if (self.folder/(key+'.dpapi')).exists():
            try:
                old=self.load(key)
                value['role_confirmation']=old.get('role_confirmation',{})
                if old.get('game_device') in ('ios','android'):value['game_device']=old['game_device']
                if readable_name(old.get('role_name')):value['role_name']=old['role_name']
            except StoreError:
                pass
        self.write(value)
        return self.public(value)

    def write(self,value):
        """Atomically persist a validated whole account; temporary files contain only encrypted bytes."""
        validate(value)
        key=value['profile_id']
        expected=hashlib.sha256((value['provider']+'\0'+next(v for k,v in value['headers'].items() if k.lower()=='t-openid')).encode()).hexdigest()
        if key!=expected:raise StoreError('账号身份校验失败')
        encrypted = b'XYHELP1\0'+crypt(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        self.folder.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.encrypted-', dir=self.folder)
        try:
            with os.fdopen(descriptor,'wb') as file:
                file.write(encrypted); file.flush(); os.fsync(file.fileno())
            os.replace(temporary, self.folder/(key+'.dpapi'))
        finally:
            Path(temporary).unlink(missing_ok=True)

    def confirm_role(self,key,role_key,label,remember):
        """Remember explicit user consent for this account and role only; never change a server binding."""
        import time
        value=self.load(key)
        value['role_confirmation']={'role_key':role_key,'label':label,'confirmed_at':time.time(),
                                    'expires_at':time.time()+30*86400 if remember else 0}
        self.write(value)

    def set_game_device(self,key,device,clear_confirmation=False):
        """Save the person's explicit game platform encrypted; binding changes invalidate old claim consent."""
        if device not in ('ios','android'):raise StoreError('请选择安卓或iOS平台')
        value=self.load(key)
        if value.get('game_device')!=device:value.pop('role_name',None)
        value['game_device']=device
        if clear_confirmation:value.pop('role_confirmation',None)
        self.write(value)

    def remember_role(self,key,name):
        """Cache a server-confirmed display name locally, preserving credentials and their saved timestamp."""
        name=readable_name(name)
        value=self.load(key)
        if name and value.get('role_name')!=name:
            value['role_name']=name
            self.write(value)
        return self.public(value)

    def delete(self,key):
        """Remove only the selected local encrypted record; never log out, unbind or delete receipt history."""
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
            raise StoreError('账号标识无效')
        try:
            (self.folder/(key+'.dpapi')).unlink(missing_ok=True)
        except OSError:
            raise StoreError('本地账号删除失败，请检查文件权限后重试') from None

    def load(self, key):
        """Decrypt only a validated account identifier; never accept caller-supplied filesystem traversal."""
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
            raise StoreError('账号标识无效')
        path=self.folder/(key+'.dpapi')
        try:
            if not 8<path.stat().st_size<=256*1024:raise ValueError()
            raw=path.read_bytes()
            if not raw.startswith(b'XYHELP1\0'):raise ValueError()
            value=validate(json.loads(crypt(raw[8:],decrypt=True)))
            if value.get('profile_id')!=key:raise ValueError()
            return value
        except (OSError,ValueError):
            raise StoreError('账号文件不可用，请重新扫码') from None

    @staticmethod
    def public(value):
        """Expose account labels and dates only; no Token, OpenID, cookie or refresh secret reaches widgets."""
        row={key:value.get(key) for key in ('profile_id','provider','saved_at','expires_at','game_device')}
        row.update(nickname=readable_name(value.get('nickname')),role_name=readable_name(value.get('role_name')),
                   display_name=account_name(value))
        return row

    def list(self):
        """Load local records without networking; damaged records remain untouched and are omitted."""
        result=[]
        if not self.folder.exists():return result
        for path in sorted(self.folder.glob('*.dpapi')):
            try:result.append(self.public(self.load(path.stem)))
            except StoreError:continue
        return result
