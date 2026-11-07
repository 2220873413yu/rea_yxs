# 自动补满步兵 Implementation Plan

> **For agentic workers:** Execute inline in the current session using the executing-plans workflow. No subagents are needed.

**Goal:** 在雷电模拟器的当前游戏会话中，通过一个电脑开关自动补满步兵，并使用指定训练加速。

**Architecture:** 电脑控制窗口驱动串行控制器。进程桥在游戏主线程读取模型并复用业务函数；所有动作有状态核对和消耗上限。进程桥失败时停止，不能用界面自动点击替代后台调用。

**Tech Stack:** Python 3.12、Tkinter、ADB、Frida、Lua、当前 Unity/IL2CPP 游戏。

## 阶段一：验证接入能力

- [x] 用户已批准设计，包括道具余时浪费规则和电脑窗口形态。
- [x] 在项目隔离 Python 环境安装 Frida，固定实际版本，下载相同版本官方 Android x86_64 server。
- [x] 以模拟器既有 root 启动本地监听服务，不修改游戏 APK 或系统配置。
- [x] 创建 `auto_infantry/probe.py`：仅附加 `com.qqgame.mic` 当前 PID，检查 emulated realm、ARM64 模块及 Lua 更新入口，保存诊断 JSON，退出时卸载并分离。
- [x] 运行探针：`.analysis-tools/pyenv/Scripts/python.exe auto_infantry/probe.py`。成功必须输出目标进程、ARM64 架构及 `libtolua.so`；失败必须保留准确错误并核对游戏仍在运行。

## 阶段二：主线程只读模型与函数核对

- [x] 创建 `auto_infantry/bridge.js`，挂接 `tolua_update`，用有界任务队列执行 Lua 查询，并在每次查询后恢复 Lua 栈。
- [x] 仅列举 `SLGBuildingsController`、`SLGBuildingsModel` 和加速相关模块的业务函数，避免输出登录凭据。
- [x] 查明并核对步兵数量、训练数量、当前上限、资源、指定道具库存和剩余训练时间。读取失败不允许开启。
- [x] 使用已有日志交叉检查，不能用历史值或假定上限代替实时模型。

## 阶段三：单次后台业务验证

- [x] 在保持地图界面时发起一次训练，核对响应与数量/队列变化。
- [x] 使用一个道具 70251，核对响应、库存变化和倒计时变化。
- [x] 接入期间不启动自主训练循环。服务器拒绝或结果不明时停止，不连续试发。

## 阶段四：开关与有界循环

- [x] 创建 `auto_infantry/controller.py`，实现关闭、读取、训练、等待响应、加速、核对、完成或失败的串行状态机。
- [x] 为关闭后不再发送、满额停止、库存不足停止、超时不重发、差额限制和重复响应编写有意义的离线测试。
- [x] 创建 `auto_infantry/app.pyw`，显示单个开关、实时数量/上限、道具数量、动作和停止原因。程序启动默认关闭。
- [x] 通过后再做一次用户可见的有界运行验证；核对未切换兵营且只消耗预期资源。
- [x] 交付启动方式、实际验证结果和已知限制；不宣称未通过的能力。

当前目录不是 Git 仓库，不为提交设计文档而擅自初始化仓库。按阶段记录结果，技术验证失败则交付准确诊断。
