# 打包脚本

本目录为 LCA 离线版的打包脚本，不包含安装包、模型或第三方运行文件。

## 入口

在项目根目录准备好虚拟环境、模型、输入驱动和其他运行文件后执行：

```text
build_assets\packaging\build_release.bat
```

脚本使用 Nuitka 生成程序目录。本机已安装 Inno Setup 6 时，继续生成安装包：

```text
build_assets\packaging\release_output\LCA_离线版_Setup.exe
```

无交互环境可设置 `LCA_NONINTERACTIVE=1`。

## 目录说明

| 文件 | 说明 |
| --- | --- |
| `build_release.bat` | 打包入口 |
| `run_nuitka_main_build.py` | 主程序 Nuitka 编译 |
| `setup.iss` | Inno Setup 安装包脚本 |
| `lca_main.manifest` | Windows 清单 |
| `stage_packaged_runtime_assets.py` | 整理运行文件 |
| `write_build_metadata.py` | 写入构建元数据 |
| `generate_sbom.py` | 生成软件物料清单 |
| `../third_party/manifest.json` | 第三方文件清单 |

`build_output/` 与 `release_output/` 为本地构建产物，不纳入仓库。
