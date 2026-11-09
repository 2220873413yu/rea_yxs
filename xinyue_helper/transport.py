"""Isolated HTTPS sessions with bounded responses and credential-free failures."""
from dataclasses import dataclass, field
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = frozenset(('bgw.xinyue.qq.com', 'open.weixin.qq.com', 'long.open.weixin.qq.com',
    'openmobile.qq.com', 'xui.ptlogin2.qq.com', 'ssl.ptlogin2.qq.com', 'ptlogin2.qq.com',
    'graph.qq.com', 'connect.qq.com', 'openmobile.qq.com'))


class ServiceError(RuntimeError):
    """Expose an actionable message without echoing URLs, cookies or response bodies."""


@dataclass(repr=False)
class Response:
    """Keep raw response material inside service code, away from repr-based logging."""
    status: int
    headers: object = field(repr=False)
    body: bytes = field(repr=False)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Require each OAuth redirect to be examined before it is followed."""
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        """Refuse automatic redirects, including ones that might leak authorization headers."""
        return None


class Session:
    """Own one provider/account cookie jar; different accounts never share this object."""
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, url, body=None, headers=None, timeout=20):
        """Perform a single allowlisted HTTPS request with no automatic retry or redirect."""
        target = urllib.parse.urlsplit(url)
        if target.scheme != 'https' or target.hostname not in ALLOWED_HOSTS or target.username or target.password:
            raise ServiceError('授权地址不在支持范围内')
        request = urllib.request.Request(url, data=body, headers=headers or {}, method='POST' if body is not None else 'GET')
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ServiceError('网络请求失败或超时，请检查网络后手动重试') from None
        with response:
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ServiceError('服务器响应过大')
            return Response(response.code, response.headers, data)

    def json(self, url, data=None, headers=None, timeout=20):
        """Send/parse JSON without allowing raw parsing exceptions to expose server credentials."""
        all_headers = {'Accept': 'application/json', **(headers or {})}
        body = None
        if data is not None:
            all_headers['Content-Type'] = 'application/json'
            body = json.dumps(data, separators=(',', ':')).encode()
        response = self.request(url, body, all_headers, timeout)
        if response.status != 200:
            raise ServiceError('服务器HTTP错误：' + str(response.status))
        try:
            value = json.loads(response.body)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError):
            raise ServiceError('服务器返回了无法识别的数据') from None

    def cookie(self, name):
        """Read a cookie inside its provider session without copying it to logs or public state."""
        return next((cookie.value for cookie in self.cookies if cookie.name == name), '')
