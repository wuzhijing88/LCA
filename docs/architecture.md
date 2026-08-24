# LCA 运行时架构

LCA 是本地 Windows 可视化自动化引擎，不是企业 RPA 平台。

## 分层

- `ui/`：Qt 展示、参数收集和用户确认。
- `app_core/runtime/`：执行来源互斥、生命周期、取消和进程终止策略。
- `app_core/control_plane/`：多窗口作业状态与快照。
- `app_core/scheduling/`：纯调度策略与时钟计算。
- `task_workflow/`：图遍历、任务结果契约、运行上下文和进程 backend。
- `tasks/`：自动化任务节点。
- `services/`：OCR、匹配、截图和安全 IPC。

## 执行流

1. 主窗口、中控或测试入口向 `ExecutionCoordinator` 请求创建运行时。
2. Coordinator 保证不同执行来源互斥，并通过统一 factory 创建进程代理。
3. 主进程使用带认证握手的版本化 JSON IPC 启动 workflow worker。
4. worker 使用 `GraphEngine` 选择连接，通过任务注册表执行节点。
5. 任务结果统一转换为 `TaskResult/Transition`。
6. `CancelToken` 负责协作停止；超时后 process backend 统一终止进程树。
7. worker 事件回传 UI，同时释放 Coordinator 中的 Session。

## 扩展边界

- 新任务遵循 `docs/task_authoring.md`。
- 新目标应用差异通过 `WindowAdapter` 提供，禁止在通用执行器中判断应用名称。
- 新 IPC 消息必须兼容 `services/ipc_codec.py` 的版本化协议，禁止 pickle。
- 新持久配置必须归属 `app_core/config_sections.py` 的逻辑 section。
