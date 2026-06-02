# LCA

LCA 是一个面向 Windows 桌面自动化场景的本地工作流工具，提供可视化任务编排、图像识别、OCR、鼠标键盘输入、窗口控制、多窗口执行、插件适配和运行时管理等能力。

当前版本面向开源仓库整理：普通启动不再依赖在线验证、服务端授权、硬件 ID 注册、脚本市场、反调试检测和主进程内存诊断。插件模式相关入口仍保留，便于继续使用 OLA 等本地插件适配能力。

## 功能概览

- 可视化工作流：创建、编辑和执行由多个任务节点组成的自动化流程。
- 图像与 OCR：支持截图、图像匹配、区域识别、OCR 子进程处理和模板预加载。
- 输入自动化：支持鼠标、键盘、滚轮、录制回放、前台窗口输入和插件输入模式。
- 窗口管理：支持窗口选择、绑定、激活、多窗口任务分配和执行控制。
- 多进程运行：OCR、图像匹配、工作流等能力可通过独立子进程隔离运行。
- 插件适配：保留插件接口、插件管理和 OLA Python 适配源码。
- 本地运行数据：日志、配置、截图模板和工作流默认落在安装后的 LCA 根目录。

## 目录结构

```text
.
├── app_core/          # 应用核心配置、日志、插件桥接和运行时入口
├── OLA/               # OLA Python 适配源码
├── plugins/           # 插件接口、管理器和适配器
├── resources/         # 文本资源
├── services/          # OCR、截图、AI、MCP 等服务模块
├── task_workflow/     # 工作流执行、变量、进程代理和上下文
├── tasks/             # 自动化任务实现
├── themes/            # QSS 样式和主题管理逻辑
├── ui/                # PySide6 用户界面
├── utils/             # 输入、截图、窗口、路径、运行时等通用工具
├── main.py            # 应用入口
└── requirements.txt   # Python 依赖清单
```

## 环境要求

- Windows 10 或更高版本。
- Python 3.10，建议使用虚拟环境。
- 依赖安装工具：`pip`。

## 安装与运行

```powershell
python -m venv venv
.\venv\Scripts\python -m pip install --upgrade pip
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python main.py
```

## 许可证

本项目使用 GNU Affero General Public License v3.0。详情见 `LICENSE`。

## 免责声明

本项目包含桌面自动化、输入模拟、窗口控制和图像识别相关能力。使用者应自行确认使用场景符合目标软件、平台和所在地规则与法律要求。
