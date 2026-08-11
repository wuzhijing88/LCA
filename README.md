# LCA

交流QQ群：15740321

LCA 是一个 Windows 桌面工作流自动化程序，界面使用 PySide6 开发。

本仓库保存当前本地版本的应用源码，不是完整的安装包。模型、输入驱动、运行配置、虚拟环境和用户数据不在仓库中，单独克隆源码不能直接运行。

## 当前范围

程序包含以下主要部分：

- 工作流卡片的创建、连线、保存和执行
- 单窗口及多窗口任务调度
- 鼠标、键盘和滚轮输入
- 截图、图像匹配、OCR 和 YOLO 检测
- 变量、条件、随机跳转、线程控制和子工作流
- 操作录制与回放

当前注册的任务类型：

- 线程起点
- 模拟鼠标操作
- 模拟键盘操作
- 延迟
- 条件控制
- 随机跳转
- 线程控制
- 线程窗口限制
- OCR文字识别
- YOLO目标检测
- 变量提取
- 变量比较
- 录制回放
- 附加条件
- 子工作流

## 源码目录

| 路径 | 内容 |
| --- | --- |
| `app_core/` | 应用配置和启动流程 |
| `services/` | OCR、图像匹配、截图及子进程服务 |
| `task_workflow/` | 工作流执行器、运行上下文和进程代理 |
| `tasks/` | 任务节点实现 |
| `ui/` | 主窗口、设置窗口、参数面板和工作流界面 |
| `utils/` | 输入、截图、窗口和运行时工具 |
| `themes/` | Qt 样式和主题管理 |
| `resources/` | 程序图标和声明文本 |
| `tools/` | 构建检查脚本和 IbInputSimulator 运行文件 |
| `build_assets/packaging/` | Nuitka 和 Inno Setup 打包脚本 |
| `main.py` | 程序入口 |
| `start_lca.bat` | 本地启动脚本 |
| `requirements.txt` | Python 依赖版本 |

## 本地运行

当前开发环境使用 Windows 和 Python 3.10。

运行前需要在项目目录准备好本地虚拟环境及程序所需的模型、驱动和配置文件。依赖版本见 `requirements.txt`。

```powershell
.\start_lca.bat
```

也可以直接使用项目虚拟环境运行：

```powershell
.\venv\Scripts\python.exe .\main.py
```

## 打包

本地运行资源完整后，可执行：

```powershell
.\build_assets\packaging\build_release.bat
```

脚本使用 Nuitka 生成程序目录；本机安装 Inno Setup 6 时会继续生成安装包。打包所需的模型、Interception、AutoHotkey、IbInputSimulator 和其他运行文件需要由本地环境提供。

## 仓库边界

以下内容只保留在开发或运行机器上，不纳入本仓库：

- 运行配置和私有配置
- 测试代码及内部文档
- Python 虚拟环境
- OCR、YOLO 等模型文件
- Interception、AutoHotkey 等第三方运行文件
- 工作流、截图、日志、缓存和打包输出

## 许可证

本项目使用 GNU Affero General Public License v3.0，详见 `LICENSE`。
