# Changelog

## Unreleased

- 建立依赖锁、Windows CI、核心测试和性能基线。
- 引入统一执行 Coordinator、CancelToken、RuntimeLifecycle 和进程树终止策略。
- 抽取 GraphEngine、TaskResult/Transition、RunContext 与 WindowAdapter。
- 将跨进程 pickle 替换为版本化安全 IPC，并增加 workflow worker 认证握手。
- 用户数据迁移至 `%LOCALAPPDATA%\LCA`，保留便携模式兼容。
- 增加第三方哈希清单、SBOM、结构化日志和脱敏诊断包。
- 发布构建支持无交互模式、第三方资源校验和离线版固定命名。
