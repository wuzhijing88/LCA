dotnet build build_assets/plugin_host/PluginHost.csproj -c Release
copy build_assets\plugin_host\bin\Release\PluginHost.exe tools\plugin\PluginHost.exe
把 7.2607 的 dm.dll 与 RegDll.dll 放到 tools/plugin/
