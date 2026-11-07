# Resource List Implementation Plan

> Execution: use executing-plans in this thread; user has already authorized implementation. Workspace is not a Git repository.

**Goal:** 保存多坐标资源清单，实时按等级余量过滤，优先采集近点。

**Architecture:** collection.py保存不可变坐标范围与资格规则；resource_preferences.py验证并原子保存坐标；清单编辑窗口与现有采集面板交互；原服务和Lua最终检查共用等级余量规则。

**Tech Stack:** Python/Tkinter、JSON、Lua、unittest/Lupa。

- [x] 存储与模型：增加坐标校验/解析/去重/原子存储，CollectionOptions增加list模式与coordinates，candidate_targets按清单及距离过滤且不信任清单缓存余量。
- [x] 调度：清单调用collect_candidates的level0（所有等级），按距离查询实时目标，在选英雄或授权恢复前检查余量，目标等级与候选真实等级一致。显示未加载及低余量等待原因。
- [x] Lua：允许只读候选等级0；collect_dispatch拒绝level>=4且quantity<40000，在发送前执行现有全部检查。
- [x] UI：目标增加资源清单，编辑窗口逐行x,y，保存后更新条数，清单模式禁用等级及单坐标控件，运行中冻结，空清单拒绝启动。独立窗口避免主窗口变高。
- [x] 测试：持久化重载和失败保持旧文件；距离、混合等级、实时跳过低余量及不恢复；Lua阈值39999/40000、低级少量；Tkinter离线布局及交互；原69项与桥接6组回归。
- [x] 更新使用说明、记录验证结果；不启动或开启真实消费开关。

Validation commands: `.analysis-tools/pyenv/Scripts/python.exe -X utf8 -m unittest discover -s auto_infantry -p 'test_*.py' -q`; `.analysis-tools/node-v24.22.1-win-x64/node.exe auto_infantry/test_bridge.cjs`.

完成验证：79项Python/Lua测试、6组桥接测试通过；analysis/verify_resource_list_ui.py验证隐藏实际App窗口、临时清单保存重载、空清单拒绝启动、编辑禁用，窗口需求837×912适配1050×940。编译检查通过。本次未连接游戏或执行实际消费。
