# 任务节点接入规范

LCA 的任务节点属于本地自动化执行内核，不应依赖 Qt 界面。

## 必须满足

1. 在 `tasks/__init__.py` 的注册表中声明任务名称和模块。
2. 模块提供顶层 `execute_task(params, ...)`。
3. 新任务返回 `task_workflow.task_result.TaskResult`。
4. 迁移期旧任务可以返回 `(success, action, next_card_id[, detail])`，执行器会统一适配。
5. 任务必须响应 `stop_checker`；涉及等待或输入时还要响应暂停。
6. 不得 import `ui` 或 `PySide6`，不得写模块级运行态。
7. 目标应用差异通过 `WindowAdapter` 或配置实现，不得在执行器中判断应用名称。

`tools/lint_task_modules.py` 暂时记录了四个历史 UI 依赖模块的显式 allowlist；allowlist 只能缩小，新增任务不得加入。

## Transition

- `NEXT`：按连接继续。
- `JUMP`：跳转到指定卡片。
- `RETRY`：重新执行本卡片。
- `STOP`：结束当前工作流。

提交新任务前运行：

```powershell
.\venv\Scripts\python.exe tools\lint_task_modules.py
.\venv\Scripts\python.exe -m pytest tests\test_task_registry_contract.py tests\test_task_result.py
```
