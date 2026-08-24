# LCA 验证基线

LCA 是本地 Windows 桌面自动化工具。每次运行时架构或打包改动至少验证以下场景。

## 自动检查

```powershell
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe tools\verify_runtime_baseline.py
```

## 手工与集成场景

1. 单窗口：启动、暂停、恢复、正常停止、再次启动。
2. 十窗口：并行启动、部分停止、全部停止，状态不得漂移。
3. 多起点：至少两个线程起点同时运行并共享同一目标窗口。
4. OCR 循环：连续运行 30 分钟，记录 P50/P95、吞吐、主进程和 worker 内存。
5. 长回放：执行中暂停与强制停止，停止后不得继续产生键鼠输入。
6. 子工作流：两层嵌套、父流程停止、子流程失败传播。
7. 异常退出：终止 worker、关闭目标窗口、断开 IPC，主界面必须进入明确终态。
8. 打包版：OCR、match、workflow worker smoke test 全部通过。

## 发布门槛

- 正常停止 P95 不超过 2 秒。
- 强制停止后 5 秒内相关进程树消失。
- 8 小时稳定性测试无孤儿 worker，稳定段内存增长不超过 15%。
- OCR 性能相对已批准基线回退不超过 10%。
- 安装包固定命名为 `LCA_离线版_Setup.exe`，不得引入数字版本后缀。
