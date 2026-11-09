# 微信英雄杀角色绑定：只读调研

## 本次边界

用户授权只读分析区服和角色查询，不实际绑定，不签到、不领奖。使用本地已加密保存、昵称为“旅行”的微信票据。模拟器原账号仍为QQ“秋风”，仅查看其原生选择界面与请求格式，没有切换账号或点击绑定确认。

## 已确认接口

- `amp2.RoleSrv/PullGameInfo`：获取游戏配置；已用微信票据请求gid=1187，返回英雄杀名称和选择策略（area_channel_select、is_wxqq_select等）。
- `amp2.RoleSrv/GetRecentRoleList`：原生打开角色弹窗时调用的最近角色查询；本次仅观察原生请求，没有用微信另行调用。
- `amp2.RoleSrv/GetPartitionList`：区服列表查询。APK原生DEX中有路径和请求类，已用微信票据请求，得到400000授权告知，未返回区服列表。
- `amp2.RoleSrv/GetSpecifyRoleList`：按区服查询角色；原生请求为JSON（不是此前礼包的protobuf请求格式）。实测微信票据同样得到400000授权告知，roles为空。
- `amp2.RoleSrv/BindRole`、`xyapp.GiftSrv/PassCardBindGameRoleV2`：不同调用链中的写入路径。本次均未调用，尚未完整验证两者是否需要组合。

原生GetSpecifyRoleList样本参数：partition_id、gid、device、page_no、is_auth、area_channel_id。原生QQ样本为gid=1187、device=android、partition_id=1、page_no=1、is_auth=true、area_channel_id为空。用微信票据对iOS请求的探索尚被授权告知拦截，不能据此认为所有区服参数已经验证；不得写死“微信=2”代替服务器列表。

## 微信实测结果

配置查询成功。区服和角色查询均返回ret=400000及原文：

> 心悦俱乐部将获取你在《英雄杀》的大区信息、角色昵称，以发放游戏权益内容。

这是进一步读取角色资料之前的授权告知，不能当成“没有角色”，也不能当成Token无效。本次保持is_auth检查，不改变参数以跳过告知，不修改任何授权或绑定。因此尚未取得“旅行”的游戏角色名单。

## 可实现的选择流程

显示授权说明并由本人确认 → 获取服务器区服列表 → 选区服 → 分页获取本微信角色 → 展示昵称、区服及平台 → 本人选择 → 单独确认后提交绑定 → 只读复查绑定和礼包状态。

“获取角色资料”与“实际绑定/领取”必须是分开的动作。若后续只授权前者，也不得自动执行绑定或领取。需要先进一步核对原生授权告知确认后的调用链，完成区服和角色列表实测，再实现绑定按钮。

## 证据与限制

静态APK/DEX字符串、运行时字段元数据及被动HTTP请求元数据保留于analysis/evidence/xinyue-static。未保存明文Token、Cookie、游戏OpenID或角色唯一标识；公开结果仅保存配置、参数结构、返回码和告知文字。采样脚本已自动卸载、断开。原生只读界面中的QQ角色不代表微信账号的角色。
