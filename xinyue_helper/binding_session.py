"""Native CheckBind preflight distinguishes a stale OAuth ticket from real binding restrictions."""
import json
from .auth import BGW
from .transport import ServiceError
from . import protocol as p


class LoginExpiredError(ServiceError):
    """A safe account-session failure that must never be presented as a reason to unbind."""


def check_binding_session(account,session,require_allowed=False):
    """Perform one native read-only eligibility check using this account's ticket, without binding or claiming."""
    response=session.request(BGW+'xyapp.GiftSrv/CheckBind',p.varint(8)+p.varint(1187),account['headers'])
    if response.status!=200:raise ServiceError('绑定资格检查HTTP错误：'+str(response.status))
    if 'json' in response.headers.get('Content-Type',''):
        try:code=json.loads(response.body).get('ret')
        except (ValueError,AttributeError):code='未知'
        if code==7001:
            raise LoginExpiredError('登录票据已失效或被较新的登录替换；请点击“添加 / 更新账号”重新扫码。不是需要解绑，本次未修改绑定。')
        raise ServiceError('绑定资格网关检查未通过：'+str(code))
    fields=p.parse(response.body);code=p.get(fields,1,0)
    if code!=0:raise ServiceError('绑定资格检查被拒绝，返回码：'+str(code))
    raw=p.get(fields,3)
    if not isinstance(raw,bytes):raise ServiceError('服务器未返回绑定资格数据，未修改绑定。')
    data=p.parse(raw);result=p.get(data,1,0);num=p.get(data,2,0)
    if require_allowed and result!=0:
        raise ServiceError(f'服务器暂不允许新增礼包绑定（资格状态 {result}，参数 {num}），未继续提交。')
    return result,num
