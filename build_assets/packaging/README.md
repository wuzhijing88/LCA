# 打包脚本

本目录为 LCA 测试版的打包脚本，不包含安装包、模型或第三方运行文件。

## 入口

在项目根目录准备好虚拟环境、模型、输入驱动和其他运行文件后执行：

```text
build_assets\packaging\build_release.bat
```

插件运行库放在 `tools/plugin/`（至少含 `PluginHost.exe`、`dm.dll`、`RegDll.dll`）。打包时若该目录存在，Nuitka 会 `--include-data-dir`，`stage_packaged_runtime_assets.py` 再拷到发行目录；目录不存在则跳过，插件截图引擎在发行包中会不可用。

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

## 目录说明

| 文件 | 说明 |
| --- | --- |
| `build_release.bat` | 打包入口 |
| `run_nuitka_main_build.py` | Nuitka 编译 `main.dist/main.exe` |
| `setup.iss` | 编辑器 Inno Setup 安装包脚本 |
| `lca_main.manifest` | Windows 清单 |
| `stage_packaged_runtime_assets.py` | 整理运行文件 |
| `write_build_metadata.py` | 写入构建元数据 |
| `generate_sbom.py` | 生成软件物料清单 |
| `../third_party/manifest.json` | 第三方文件清单 |

`build_output/` 与 `release_output/` 为本地构建产物，不纳入仓库。
