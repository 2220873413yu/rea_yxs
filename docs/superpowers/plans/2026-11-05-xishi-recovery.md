# 西施自动恢复 Implementation Plan

**Goal:** 在已有助手加入默认关闭的西施自动恢复，跳过忙碌和未知状态。

**Architecture:** 现有Worker串行调度造兵和恢复，独立桥接开关即时撤销排队请求。新增hero_runtime.lua负责固定英雄读取和最终状态核验，hero_recovery.py负责恢复决策与响应校验。只消费70291，每次一个。

**Tech Stack:** Python/Tkinter、Frida、Unity LuaJIT。

- [x] 核验英雄查询、状态0和活动部队缓存；只读刷新真实数据，记录字段证据。
- [x] 新增恢复决策测试：忙碌、未知、空闲无冷却、库存耗尽、进度异常、少于五分钟和关闭后停止。
- [x] 实现固定英雄Lua API，三秒内的新英雄和部队响应才允许发送；任何活动部队匹配或非0状态均跳过。发送前重新检查缓存和库存。
- [x] 扩展bridge.js/connection.py的独立恢复门控、响应归属验证和刷新等待；不影响既有造兵门控。
- [x] Worker串行调度，每三秒检查一次，恢复错误只关闭恢复；连接失效同时关闭全部。更新app.pyw固定开关和状态。
- [x] 运行unittest、Python编译、JS语法检查、模拟Lua业务测试；只读加载新API核对实时状态，不消耗恢复道具。
- [x] 更新使用说明和设计文档；保留原入口，告知用户关闭旧窗口并重启加载新代码。

命令：`.analysis-tools/pyenv/Scripts/python.exe -m unittest discover -s auto_infantry -p 'test_*.py' -v`；预期全部通过。

本目录没有Git仓库，修改直接保存在工作区；不创建提交，不自动重启运行中的旧助手。

完成验证：31项Python/Lua测试、4组桥接门控场景全部通过，Python编译与JS语法检查通过。Tk界面请求高度605，窗口高度620，可完整容纳内容。真实只读查询确认西施空闲且无需恢复，70291库存前后均为1574；未发送真实英雄恢复消耗请求。
