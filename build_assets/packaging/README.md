# 打包脚本

本目录为 LCA 测试版的打包脚本，不包含安装包、模型或第三方运行文件。

## 入口

在项目根目录准备好虚拟环境、模型、输入驱动和其他运行文件后执行：

```text
build_assets\packaging\build_release.bat
```

插件运行库放在 `tools/plugin/`（`PluginHost.exe`、`dm.dll`、`RegDll.dll`，以及大漠附属 `xx.dat`）。打包时只按文件白名单纳入：Nuitka 用 `--include-data-files`，`stage_packaged_runtime_assets.py` 再拷到发行目录并清掉其它残留；目录不存在或白名单文件都缺则跳过，插件截图引擎在发行包中会不可用。

离线双身份（行业常见、无授权）：

1. Nuitka **只编一轮** `main.dist/main.exe`（共享引擎）
2. 打包结束给 `main.exe` 盖 **编辑器** PE 入口印记 → 官方 LCA 安装包
3. 「制作独立程序」复制同一引擎，改名/图标后盖 **播放器** 印记 + `package.lcap` 数据包

运行时只读本进程 exe 内嵌印记决定入口；不靠旁路文件、快捷方式或改名。

播放器 exe 印记与 `package.lcap` 共享随机 `bind_id`：换包/混用不同导出批次会无法启动（防挪包；不防本地补丁）。

本机已安装 Inno Setup 6 时，继续生成编辑器安装包：

```text
build_assets\packaging\release_output\LCA_测试版_Setup.exe
```

无交互环境可设置 `LCA_NONINTERACTIVE=1`。

Windows Defender 常把 `tools/plugin/dm.dll` 误报为 `Trojan:Win32/Bearfoos.B!ml`（`!ml` 是机器学习启发式）。打包脚本会先把 `tools/plugin`、`build_output`、`release_output` 加入排除项；权限不足时请用管理员运行，或在「Windows 安全中心 > 病毒和威胁防护 > 排除项」中手动添加上述目录。

已有 `main.dist`、只需重打安装包时：

```text
set LCA_INSTALLER_ONLY=1
build_assets\packaging\build_release.bat
```

## 目录说明

| 文件 | 说明 |
| --- | --- |
| `build_release.bat` | 打包入口；`LCA_INSTALLER_ONLY=1` 时跳过 Nuitka，只重打安装包 |
| `ensure_packaging_av_exclusions.py` | 为插件目录和打包输出加入 Defender 排除项 |
| `run_nuitka_main_build.py` | Nuitka 编译 `main.dist/main.exe` |
| `setup.iss` | 编辑器 Inno Setup 安装包脚本 |
| `lca_main.manifest` | Windows 清单 |
| `stage_packaged_runtime_assets.py` | 整理运行文件 |
| `write_build_metadata.py` | 写入构建元数据 |
| `generate_sbom.py` | 生成软件物料清单（CycloneDX），组件来自 `manifest.json` |
| `generate_third_party_manifest.py` | 重新生成 `manifest.json`：原生组件哈希 + Python 依赖传递闭包 |
| `verify_third_party_manifest.py` | 打包前校验：原生组件哈希、Python 依赖闭包与 venv 是否一致 |
| `../third_party/manifest.json` | 第三方文件清单 |

`build_output/` 与 `release_output/` 为本地构建产物，不纳入仓库。

## 依赖足迹

`requirements-runtime.txt` 只写直接依赖。Nuitka 会把它们的整个传递闭包（例如 rapidocr 拉进来的
`requests`/`shapely`/`pyclipper`/`omegaconf`）都编进 dist，所以 `manifest.json` 的 `python_dependencies`
必须是闭包而不是直接依赖：每条带 `direct`、`bundled`、`required_by`，SBOM 原样透出。

- 改过 `requirements-runtime.txt` 或升级 venv 后，运行 `generate_third_party_manifest.py` 重新生成清单；
  `build_release.bat` 的 `VERIFY_THIRD_PARTY_MANIFEST` 步骤会在闭包漂移时直接失败。
- 不需要的传递依赖通过 `run_nuitka_main_build.py` 的 `NOFOLLOW_IMPORTS` 排除，当前排除：
  rapidocr 的 paddle/pytorch/openvino/tensorrt/mnn 后端、`onnxruntime.tools/transformers/quantization`、
  `sympy`/`mpmath`/`protobuf`/`flatbuffers`。构建后 `_remove_unused_rapidocr_backends` 会把后端目录残留删掉。
- `rapidocr` 走 `THIRD_PARTY_EXPAND_PACKAGES`：展开成显式 `--include-module` 列表并跳过被 nofollow 的子树。
  若改回 `--include-package=rapidocr`，Nuitka 会对每个被否决的模块打一条
  `Not allowed to include module ... instructed by user to not follow to` 警告，构建仍能成功但噪音很大。
- 往 `NOFOLLOW_IMPORTS` 加 rapidocr 子模块前先确认它没被顶层硬 import：`rapidocr.utils.vis_res`、
  `rapidocr.utils.download_*` 都是 `rapidocr.main` 的硬依赖，排掉就是运行时 ImportError。
  `tests/build_assets/packaging/test_dependency_footprint.py` 里有对应的守护测试。
- `requests` 及其网络栈无法排除：`rapidocr/main.py` 顶层硬 import 了 `download_models`。
- `setup.iss` 的 `GetProgramRuntimeDirNames` 是升级/卸载时要清掉的程序目录名，新增会落到 dist
  顶层的目录时要同步补上，否则升级后残留。
