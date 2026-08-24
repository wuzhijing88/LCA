# Contributing

提交改动前运行：

```powershell
.\venv\Scripts\python.exe tools\verify_runtime_baseline.py
.\venv\Scripts\python.exe tools\lint_task_modules.py
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m pytest --cov
```

运行时、IPC、输入和 OCR 改动还需执行 `docs/testing.md` 中对应的集成场景。新增任务必须遵循 `docs/task_authoring.md`，新增第三方二进制必须更新 manifest、许可证与 SHA256。
