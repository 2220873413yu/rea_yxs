# 英雄杀世界模式助手

本项目保存当前 Windows／雷电模拟器上的助手代码与研究记录，作为后续功能开发及切换账号问题的版本基线。使用 Python/Tkinter 提供界面，通过 Frida 桥接已登录游戏进程，在游戏主线程调用原生 Lua 业务函数；请求使用客户端已有连接与登录上下文。没有修改原 APK。

## 当前功能

- 自动训练弓兵、骑兵、步兵、斥候；训练加速默认不启用，兵营升级时不训练。
- 动态英雄名单、状态展示、指定英雄恢复，以及采集共用恢复调度。
- 资源清单采集、粮木铁存量与预期收入分配、联盟采集。
- 按服务器额度补充打野队伍、区域查询、原生默认编队和胜券在握检查。
- 烽火台救援、怪物、资源、宝藏分别勾选；宝藏只消耗现有斥候，不购买。
- 烽火台占用包含返城队伍；满额或明确6395拒绝时保持开启，按服务器阶段时间和推送等待空位。结果未知仍停止，不自动重发。
- iOS 微信原生扫码登录；账号变化后清空旧显示、重建连接，读取当前角色与地图数据，不保存或替换 Token。

各自动总开关启动及重新读取账号后默认关闭；本次会话手动开启打野后，才恢复地图刷新时刻自动开启规则。当前功能详情优先参考代码及 `docs/superpowers/specs/` 中较新的设计；`auto_infantry/使用说明.txt` 和早期研究记录包含历史行为。

## 本机运行环境

- Windows，Python 3.12（Tkinter 随官方 Windows Python 安装提供）。
- 雷电模拟器 `emulator-5554`，ADB 当前路径为 `E:\leidian\LDPlayer9\adb.exe`。
- 游戏包名 `com.qqgame.mic`，当前只接受4.31.0／versionCode 431000017。
- 已有的模拟器 root 环境及匹配的 Frida 服务17.25.2；服务文件位置见 `auto_infantry/bootstrap.py`。
- 当前入口使用 `.analysis-tools/pyenv/Scripts/pythonw.exe`。换电脑后需核对 ADB、设备及服务二进制位置，这些设置尚未做成通用配置。

在项目根目录准备 Python 环境：

```powershell
py -3.12 -m venv .analysis-tools/pyenv
.analysis-tools/pyenv/Scripts/python.exe -m pip install -r requirements.txt
```

匹配的 Android x86_64 Frida 服务文件需自行放入 `.analysis-tools/frida-server-17.25.2-android-x86_64`，或已部署到模拟器的对应路径。仓库不包含这些二进制。

保持模拟器及已登录游戏运行，进入西游幻境并等地图加载完成，再双击 `Start-AutoInfantry.vbs`。重启时先关闭旧助手窗口，再打开此入口，不要同时启动两个助手。

## 测试

```powershell
.analysis-tools/pyenv/Scripts/python.exe -m pip install -r requirements-dev.txt
.analysis-tools/pyenv/Scripts/python.exe -X utf8 -m unittest discover -s auto_infantry -p "test_*.py" -q
node auto_infantry/test_bridge.cjs
```

Python测试使用隔离模型和协议样本，UI测试会构造并隐藏Tk窗口；桥接测试使用Node.js。不要对 `analysis/` 执行测试发现：其中部分脚本是历史上经授权使用的单次真实游戏操作工具，并非隔离测试。

## 文件与本地数据

| 路径 | 内容 |
| --- | --- |
| `auto_infantry/` | 助手、原生桥接、协议解析与隔离测试 |
| `docs/` | 设计、实现计划与未来开发需求 |
| `analysis/` | 研究脚本及历史结论；不由助手入口自动执行 |
| `Start-AutoInfantry.vbs` | 本机无控制台启动入口 |

以下内容由 `.gitignore` 排除，继续留在本机：原APK、`.analysis-tools/`、`analysis/evidence/`、提取的游戏资产、运行日志、诊断输出、英雄勾选、资源坐标及烽火台类型偏好。研究文档引用的原始证据因此可能只在原开发机存在。首次克隆不会携带任何自动功能开关或本机选择配置。

## 后续切换账号讨论

助手顶部的「iOS 微信扫码登录」会先停止自动操作并关闭旧连接；如果仍登录，会先原生退出。请本人勾选登录页协议，再点该按钮，用苹果角色对应的微信扫码授权。二维码只请求一次，等待超时不自动重发。授权后进入西游幻境，助手主动拉取兵营数据，成功后初始化当前账号其他数据。

「重新读取当前账号」停止当前自动功能、清空旧数据并重建连接，也可取消扫码等待。检测到账号／地图会话变化时会自动重建，等待地图加载；每次重建的总开关与训练加速勾选均关闭。旧计时与界面消息不会应用到新会话；只检查本地上下文，不增加固定网络轮询。

保存的资源清单、英雄与烽火台类型选择继续共用，不按账号分文件；不会因为保留选择而自动开启功能。原生扫码使用游戏自身登录上下文，助手不保存 Token 或二维码授权凭据。

## 日常提交

```powershell
git status
git diff
git add <本次修改的文件或目录>
git commit -m "说明本次改动"
git push origin master
```

运行日志和本机偏好不会进入提交。新增诊断文件或大文件时，先检查暂存列表，避免使用强制添加把本地数据带进仓库。

