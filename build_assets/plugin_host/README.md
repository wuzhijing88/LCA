# PluginHost（大漠插件 x86 宿主）

dm.dll 只有 32 位 COM 实现，所以由这个独立的 x86 进程加载它，主程序通过命名管道 RPC 调用；
帧数据走 64MiB 共享内存。运行时文件固定放在安装目录 `tools/plugin/`：
`PluginHost.exe`、`dm.dll`、`RegDll.dll`（免注册加载）以及厂商附带的 `xx.dat`。

## 构建

有 .NET SDK 时（推荐，产物带完整的目标框架信息）：

```
dotnet build build_assets/plugin_host/PluginHost.csproj -c Release
copy build_assets\plugin_host\bin\Release\PluginHost.exe tools\plugin\PluginHost.exe
```

只有 VS Build Tools（无 SDK）时，用 Roslyn csc 直接编译，效果等价：

```
set CSC="C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe"
set FW=C:\Windows\Microsoft.NET\Framework\v4.0.30319
%CSC% -nologo -target:winexe -platform:x86 -langversion:latest -optimize+ -out:tools\plugin\PluginHost.exe ^
  -lib:%FW% -r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Web.Extensions.dll ^
  -r:System.Runtime.Serialization.dll build_assets\plugin_host\Program.cs
```

构建后可用 `python -m pytest tests/utils/plugin/test_host_command.py` 做源码契约检查；
`tools/plugin/PluginHost.prev.exe` 是上一版宿主，出问题时改名回退即可。

## RPC 方法

`init`（plugin_dir / reg_code / extra_code，首包必须是它）、`bind`（display_hwnd / input_hwnd / display / mouse /
keypad / mode，可选 `public`（BindWindowEx 的 public 串，如 `dx.public.input.ime`）与 `fake_active`；返回
`{ok,last_error,error,api}`）、`unbind`（带 hwnd 只解该窗口，不带解全部）、`force_unbind`（ForceUnBindWindow）、
`is_bind`（向大漠核实窗口是否仍绑定）、`fake_active`（EnableFakeActive 开关）、
`capture`、`client_size`、`move_to`、`mouse_click|mouse_double_click|mouse_down|mouse_up`、`wheel`（格数）、
`key_down|key_up|key_press`、`key_press_str`（按键名/ASCII）、`send_string`（`hwnd` 选对象、`target` 为收字窗口；
`ime=true` 时先 SendStringIme，再 SendString→SendString2）、`version`（dm.Ver）、`last_error`、`host_pid`、
`stats`（`{slots,free,registrations,max_slots}`）、`shutdown`。

## 多窗口与注册次数

大漠一个 dm 对象只能绑一个窗口。宿主按 `display_hwnd` 给每个窗口一个 dm 对象，所有带 `hwnd` 的命令路由到对应对象；
动作类命令（键鼠 / 截图 / 发字 / 假激活）带了未绑定的 `hwnd` 直接报错"窗口 X 未绑定"，不会落到别的窗口的对象上，
只有 `client_size` / `last_error` 和不带 `hwnd` 的调用才回退到最近绑定的对象。同一窗口重复 bind 且参数一致时直接复用，
但会先用 `IsBind` 核实（目标窗口重建后绑定会静默失效）。`UnBindWindow` 返回 0 时用 `ForceUnBindWindow` 兜底释放资源。

同一窗口的截图与键鼠共用一次绑定：Python 侧键鼠绑定沿用截图的 display（不再把 dx / opengl 降成 normal），
否则每次截图↔键鼠交替都会解绑重绑。

每个 dm 对象只 `Reg` 一次：窗口解绑/关闭后对象回到空闲池，下一个窗口直接复用，不重新注册；对象总数上限 16，
满了淘汰最久未用的窗口（解绑后回池）。所以宿主生命周期内的注册次数 <= 同时绑定过的最大窗口数。`bind` 结果里的
`registered` 表示本次为该窗口新建了对象并注册，`registrations` 是累计次数，Python 侧会记一条 INFO 日志；
`stats` 随时可查。

## 真机自检

```
python build_assets/plugin_host/plugin_selfcheck.py --no-auth              # 文件/架构/宿主协议，不联网不注册
python build_assets/plugin_host/plugin_selfcheck.py --title "窗口标题" --title "第二个窗口"
```

完整模式用配置里的注册码起共享宿主（1 次 Reg），对每个窗口做试绑 → IsBind → 客户区尺寸 → MoveTo(0,0)（不点击）→ 解绑，
最后打印对象池统计；期望累计注册次数 == 窗口数，解绑后绑定中为 0、空闲对象等于窗口数。
