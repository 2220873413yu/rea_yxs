"""Official independent QR authorization; no Android/ADB/Frida dependency."""
from dataclasses import dataclass, field
import base64
import ast
import hashlib
import json
import random
import re
import time
import urllib.parse
from .transport import Session, ServiceError
from . import protocol

QQ_APP_ID = '101484782'
WX_APP_ID = 'wxa09391bb0085f4b0'
BGW = 'https://bgw.xinyue.qq.com/'
QQ_GRANT_HOSTS = frozenset(('openmobile.qq.com', 'xui.ptlogin2.qq.com',
    'ssl.ptlogin2.qq.com', 'ptlogin2.qq.com', 'graph.qq.com', 'connect.qq.com'))


def public_headers(provider):
    """Construct fresh public client headers without borrowing another account's login context."""
    return {'User-Agent': 'tgclub/6.5.4.34', 'T-APPID': WX_APP_ID if provider == 'wx' else QQ_APP_ID,
        'T-ACCOUNT-TYPE': 'qc' if provider == 'qq' else 'wx', 'T-DEVICE-TYPE': 'android', 'T-REAL-VERSION': '6.5.4.34',
        'T-VERSION': '6.5.4.34', 'T-MODE': 'true',
        'Referer': 'http://apps.game.qq.com/php/tgclub/v2/'}


@dataclass(repr=False)
class Credentials:
    """Sensitive OAuth output remains private until encrypted by the account store."""
    provider: str
    access_token: str = field(repr=False)
    openid: str = field(repr=False)
    expires_at: float | None = None
    refresh_token: str = field(default='', repr=False)
    nickname: str = ''

    def headers(self):
        """Build account-specific request headers and cookie from this authorization only."""
        if self.provider not in ('qq', 'wx') or not self.access_token or not self.openid:
            raise ServiceError('登录凭据不完整')
        headers = public_headers(self.provider)
        appid = WX_APP_ID if self.provider == 'wx' else QQ_APP_ID
        headers.update({'T-ACCESS-TOKEN': self.access_token, 'T-OPENID': self.openid,
            'Content-Type': 'application/proto', 'Accept': 'application/proto',
            'Cookie': 'xyapp_login_type=' + ('wx' if self.provider == 'wx' else 'qc')
                + ';access_token=' + self.access_token + ';openid=' + self.openid
                + ';appid=' + appid + ';acctype=' + ('qc' if self.provider == 'qq' else 'wx')})
        return headers


@dataclass(repr=False)
class Challenge:
    """A bounded QR authorization session, never persisted as an account until validated."""
    image: bytes = field(repr=False)
    expires_at: float
    state: dict = field(repr=False)


class WeChatAuth:
    """Request an official SDK QR challenge and exchange user-approved authorization codes."""
    def __init__(self, session=None):
        self.session = session or Session()

    def begin(self):
        """Obtain server-signed anonymous parameters, then fetch the official WeChat QR image."""
        result = self.session.json(BGW + 'XySrv.UserSrv/WechatLoginScan', {}, public_headers('wx'))
        if result.get('ret', -1) != 0:
            raise ServiceError('微信扫码初始化被拒绝：' + str(result.get('ret')))
        data = result.get('data')
        if isinstance(data, str):
            import json
            try:
                data = json.loads(data)
            except ValueError:
                raise ServiceError('微信扫码初始化数据异常') from None
        if not isinstance(data, dict) or not all(data.get(key) for key in ('noncestr', 'timestamp', 'signature')):
            raise ServiceError('微信扫码参数不完整')
        query = urllib.parse.urlencode({'appid': WX_APP_ID, 'scope': 'snsapi_userinfo,snsapi_delegate',
            'noncestr': data['noncestr'], 'timestamp': data['timestamp'], 'signature': data['signature']})
        qr = self.session.json('https://open.weixin.qq.com/connect/sdk/qrconnect?' + query)
        if qr.get('errcode', 0) != 0 or not qr.get('uuid'):
            raise ServiceError('微信二维码申请失败：' + str(qr.get('errcode', 'unknown')))
        try:
            image = base64.b64decode(qr['qrcode']['qrcodebase64'], validate=True)
        except (KeyError, ValueError, TypeError):
            raise ServiceError('微信二维码数据异常') from None
        if not image.startswith((b'\x89PNG', b'\xff\xd8\xff', b'GIF87a', b'GIF89a')) or len(image) > 1024 * 1024:
            raise ServiceError('微信二维码图片格式异常')
        return Challenge(image, time.monotonic() + 180, {'uuid': qr['uuid'], 'last': ''})

    def poll(self, challenge):
        """Check only this QR session; exchange a confirmed code once and never retry the exchange."""
        if time.monotonic() >= challenge.expires_at:
            return 'expired', None
        query = {'f': 'json', 'uuid': challenge.state['uuid']}
        if challenge.state['last']:
            query['last'] = challenge.state['last']
        result = self.session.json('https://long.open.weixin.qq.com/connect/l/qrconnect?' + urllib.parse.urlencode(query))
        code = result.get('wx_errcode')
        if code in (402, 403):
            return 'expired', None
        if code == 404:
            challenge.state['last'] = '404'
            return 'scanned', None
        if code == 408:
            return 'waiting', None
        if code != 405 or not result.get('wx_code'):
            raise ServiceError('微信授权返回未知状态：' + str(code))
        if challenge.state.get('exchanged'):
            raise ServiceError('本次授权码已经处理，请重新扫码')
        challenge.state['exchanged'] = True
        return 'authorized', self.exchange(result['wx_code'])

    def exchange(self, code):
        """Exchange one user-approved code through the exact native heart-club token service."""
        headers = public_headers('wx')
        headers['Content-Type'] = 'application/proto'
        response = self.session.request(BGW + 'XySrv.UserSrv/WechatGetToken', protocol.message_string(1, code), headers)
        if response.status != 200:
            raise ServiceError('微信授权码交换HTTP错误：' + str(response.status))
        fields = protocol.parse(response.body)
        ret = protocol.get(fields, 1, 0)
        data = protocol.get(fields, 3)
        if ret != 0 or not isinstance(data, bytes):
            raise ServiceError('微信登录凭据交换失败：' + str(ret))
        token = protocol.parse(data)
        access = protocol.text(protocol.get(token, 1, b''))
        openid = protocol.text(protocol.get(token, 4, b''))
        refresh = protocol.text(protocol.get(token, 3, b''))
        expires = protocol.get(token, 2, 0)
        if not access or not openid or not isinstance(expires, int):
            raise ServiceError('微信登录凭据字段未通过校验')
        return Credentials('wx', access, openid, time.time() + expires if expires else None, refresh)

    def user_info(self,credentials):
        """Read the native post-token WechatUserInfo endpoint with this wx ticket; never bind or claim."""
        if credentials.provider!='wx':raise ServiceError('微信用户资料查询要求微信票据')
        body=protocol.message_string(1,credentials.access_token)+protocol.message_string(2,credentials.openid)
        response=self.session.request(BGW+'XySrv.UserSrv/WechatUserInfo',body,credentials.headers())
        if response.status!=200:raise ServiceError('微信用户资料查询HTTP错误：'+str(response.status))
        fields=protocol.parse(response.body);ret=protocol.get(fields,1,0);raw=protocol.get(fields,3)
        if ret!=0 or not isinstance(raw,bytes):raise ServiceError('微信用户资料查询未确认，返回码：'+str(ret))
        return protocol.text(protocol.get(protocol.parse(raw),1,b''))


class QQAuth:
    """Use QQ's official mobile OAuth QR flow in an isolated HTTPS/cookie session."""
    def __init__(self, session=None):
        self.session = session or Session()
        self.login_page = ''

    def browser_request(self,url):
        """Keep one consistent mobile browser context across QQ bootstrap, QR polling and callback resolution."""
        headers={'User-Agent':'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'}
        if self.login_page:headers['Referer']=self.login_page
        return self.session.request(url,headers=headers)

    def begin(self):
        """Resolve the official authorization bootstrap and request the QR image for this app only."""
        timestamp = str(int(time.time()))
        # OpenSDK 3.5.17 computes this from the APK's public signing certificate, package, and time.
        sign = hashlib.md5(('com.tencent.tgclub_d97919d8c23c119b23c51330cae2b8f1_' + timestamp).encode()).hexdigest()
        query = urllib.parse.urlencode({'response_type': 'token', 'client_id': QQ_APP_ID,
            'redirect_uri': 'auth://tauth.qq.com/', 'scope': 'all', 'display': 'mobile',
            'style': 'qr', 'sdkp': 'a', 'sdkv': '3.5.17.lite', 'format': 'json',
            'pf': 'openmobile_android', 'time': timestamp, 'sign': sign,
            'cancel_display': '1', 'switch': '1', 'compat_v': '1', 'show_download_ui': 'true'})
        response = self.browser_request('https://openmobile.qq.com/oauth2.0/m_authorize?' + query)
        html = response.body.decode('utf-8', 'replace')
        match = re.search(r'var\s+src\s*=\s*"([^"]+)"', html)
        if response.status != 200 or not match:
            raise ServiceError('QQ官方授权入口返回异常')
        target = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), match.group(1))
        parts = urllib.parse.urlsplit(target)
        if parts.scheme != 'https' or parts.hostname != 'xui.ptlogin2.qq.com':
            raise ServiceError('QQ授权入口发生变化，请先更新登录流程')
        params = {key: values[0] for key, values in urllib.parse.parse_qs(parts.query).items()}
        if params.get('pt_3rd_aid') != QQ_APP_ID or params.get('client_id') != QQ_APP_ID:
            raise ServiceError('QQ授权应用标识不一致')
        login = self.browser_request(target)
        self.login_page = target
        if login.status != 200:
            raise ServiceError('QQ登录页加载失败')
        page = login.body.decode('utf-8', 'replace')
        version = re.search(r'ptui_version\s*=\s*encodeURIComponent\("([0-9]+)"\)', page)
        u1 = params.get('s_url', 'http://connect.qq.com')
        qr_params = {'s': 8, 'e': 0, 'appid': params['appid'], 'type': 0,
            't': random.random(), 'u1': u1, 'daid': params.get('daid', '381'), 'pt_3rd_aid': QQ_APP_ID}
        qr = self.browser_request('https://ssl.ptlogin2.qq.com/ptqrshow?' + urllib.parse.urlencode(qr_params))
        if qr.status != 200 or not qr.body.startswith((b'\x89PNG', b'GIF87a', b'GIF89a', b'\xff\xd8\xff')):
            raise ServiceError('QQ二维码申请失败')
        if not self.session.cookie('qrsig'):
            raise ServiceError('QQ二维码会话未建立')
        return Challenge(qr.body, time.monotonic() + 180,
            {'params': params, 'u1': u1, 'open_data': parts.query + '&pt_flex=1',
                'version': version.group(1) if version else '', 'finished': False})

    @staticmethod
    def callback_values(data):
        """Parse quoted callback arguments as literals without executing provider JavaScript."""
        try:
            text = data.decode('utf-8')
            match = re.fullmatch(r'\s*ptuiCB\s*\((.*?)\);?\s*', text, re.S)
            if not match or len(text) > 32768:
                raise ValueError()
            values = ast.literal_eval('[' + match.group(1) + ']')
            if not 5 <= len(values) <= 12 or not all(isinstance(value, str) for value in values):
                raise ValueError()
            return values
        except (ValueError, SyntaxError, UnicodeDecodeError):
            raise ServiceError('QQ授权状态格式异常') from None

    def poll(self, challenge):
        """Poll only the short-lived QR challenge; consume a successful authorization once."""
        if time.monotonic() >= challenge.expires_at:
            return 'expired', None
        value = 0
        for char in self.session.cookie('qrsig'):
            value = (value * 33 + ord(char)) & 0x7fffffff
        params = challenge.state['params']
        query = {'u1': challenge.state['u1'], 'from_ui': 1, 'type': 1, 'ptlang': 2052,
            'ptqrtoken': value, 'daid': params.get('daid', '381'), 'aid': params['appid'],
            'pt_3rd_aid': QQ_APP_ID, 'pt_openlogin_data': challenge.state['open_data'],
            'device': 2, 'ptopt': 1, 'pt_uistyle': params.get('style', '35'),
            'jsver': challenge.state['version'], 'r': random.random()}
        response = self.browser_request('https://ssl.ptlogin2.qq.com/ptqrlogin?' + urllib.parse.urlencode(query))
        values = self.callback_values(response.body)
        if not values:
            raise ServiceError('QQ授权状态为空')
        status = values[0]
        if status == '66':
            return 'waiting', None
        if status == '67':
            return 'scanned', None
        if status in ('65', '68'):
            return 'expired', None
        if status != '0' or len(values) < 3:
            raise ServiceError('QQ授权被拒绝，状态码：' + str(status))
        if challenge.state['finished']:
            raise ServiceError('QQ授权结果已处理')
        challenge.state['finished'] = True
        nickname = values[5] if len(values) > 5 else ''
        return 'authorized', self.finish(values[2], nickname)

    def finish(self, url, nickname):
        """Follow a bounded official grant chain and consume the native application's token callback."""
        for _ in range(10):
            parts = urllib.parse.urlsplit(url)
            try:
                if parts.username or parts.password or parts.port not in (None, 443):
                    raise ValueError()
            except ValueError:
                raise ServiceError('QQ授权跳转地址格式异常') from None
            if (parts.scheme == 'https' and parts.hostname == 'imgcache.qq.com'
                    and parts.path == '/open/connect/widget/mobile/login/proxy.htm'):
                params = urllib.parse.parse_qs(parts.fragment)
                keys = params.get('redirect_uri_key', [])
                if params.get('appid') != [QQ_APP_ID] or len(keys) != 1 or not keys[0] or len(keys[0]) > 16384:
                    raise ServiceError('QQ官方中转页的应用标识或回调键不正确')
                # The official proxy requests this JSONP endpoint; never execute remote JavaScript.
                response = self.browser_request('https://openmobile.qq.com/oauth2.0/m_get_redirect_url?'
                    + urllib.parse.urlencode({'keystr': keys[0]}))
                match = re.fullmatch(r'\s*_Callback\s*\((.*)\);?\s*',
                    response.body.decode('utf-8', 'replace'), re.S)
                try:
                    result = json.loads(match.group(1)) if match and response.status == 200 else {}
                    if result.get('ret') != 0 or not isinstance(result.get('url'), str):
                        raise ValueError()
                    callback = urllib.parse.urlsplit(result['url'])
                    if callback.scheme != 'auth' or callback.netloc != 'tauth.qq.com':
                        raise ValueError()
                except (ValueError, TypeError, AttributeError):
                    raise ServiceError('QQ官方中转回调未确认，请重新授权') from None
                url = result['url']
                continue
            if parts.scheme == 'auth' and parts.hostname == 'tauth.qq.com':
                params = urllib.parse.parse_qs(parts.fragment or parts.query)
                token = params.get('access_token', [''])[0]
                openid = params.get('openid', [''])[0]
                if not token or not openid:
                    raise ServiceError('QQ授权结果没有完整登录凭据')
                try:
                    expires = int(params.get('expires_in', ['0'])[0])
                except ValueError:
                    expires = 0
                return Credentials('qq', token, openid, time.time() + expires if expires else None, nickname=nickname)
            if parts.scheme not in ('http', 'https') or parts.hostname not in QQ_GRANT_HOSTS:
                raise ServiceError('QQ授权跳转不在已核实的官方地址范围内')
            if parts.scheme == 'http':
                url = urllib.parse.urlunsplit(('https', parts.netloc, parts.path, parts.query, parts.fragment))
            response = self.browser_request(url)
            location = response.headers.get('Location')
            if location and response.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, location)
                continue
            page = response.body.decode('utf-8', 'replace')
            match = re.search(r'''["'](auth://tauth\.qq\.com/[^"']*)["']''', page)
            if match:
                url = match.group(1).replace('&amp;', '&')
                continue
            raise ServiceError('QQ授权尚未返回Token，需检查官方授权回调')
        raise ServiceError('QQ授权跳转次数异常，已停止')
