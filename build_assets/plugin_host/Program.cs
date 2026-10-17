using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using ComTypes = System.Runtime.InteropServices.ComTypes;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class Program
{
    const int FrameMagic = 0x3146504C;
    const int FrameHeaderSize = 16;
    const int FrameMapSize = 64 * 1024 * 1024;
    const string PipePrefix = "lca-plugin-";

    static readonly object FrameLock = new object();
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    const int MaxClients = 8;
    const string ActivationMode = "registration-free";
    static readonly object InitLock = new object();
    static readonly BlockingCollection<RpcWork> ComQueue = new BlockingCollection<RpcWork>();
    static string PipeName;
    static MemoryMappedFile Map;
    static string RegCode = "";
    static string ExtraCode = "";
    static IClassFactory DmClassFactory;
    static IntPtr DmModule;
    static ComTypes.ITypeInfo DmTypeInfo;
    static Guid DmInterfaceId;
    static readonly Guid DmClassId = new Guid("26037A0E-7CBD-4FFF-9C63-56F2D0770214");
    static readonly Guid UnknownId = new Guid("00000000-0000-0000-C000-000000000046");
    static readonly Guid ClassFactoryId = new Guid("00000001-0000-0000-C000-000000000046");
    static bool Inited;
    static volatile bool Stopping;

    // 大漠一个对象只能绑一个窗口：多窗口并发时每个窗口一个 dm 对象，按 hwnd 路由，
    // 避免共用一个对象在窗口之间反复 UnBind/Bind。
    // 每个 dm 对象只 Reg 一次：窗口解绑/关闭后对象回到空闲池，下一个窗口直接复用，
    // 不再重新注册，宿主生命周期内的注册次数 <= 同时绑定过的最大窗口数（上限 MaxSlots）。
    const int MaxSlots = 16;
    static DmSlot Primary;
    static DmSlot LastSlot;
    static readonly Dictionary<int, DmSlot> Slots = new Dictionary<int, DmSlot>();
    static readonly List<DmSlot> FreeSlots = new List<DmSlot>();
    static long SlotClock;
    static int Registrations;

    sealed class DmSlot
    {
        public object Dm;
        public int Hwnd;
        public bool BindOk;
        public BindStateKey Key;
        public bool FakeActive;
        public long LastUsed;

        public void Touch()
        {
            LastUsed = ++SlotClock;
        }

        public void ClearBind()
        {
            BindOk = false;
            FakeActive = false;
            Key = default(BindStateKey);
        }
    }

    struct BindStateKey : IEquatable<BindStateKey>
    {
        public int DisplayHwnd;
        public int InputHwnd;
        public string Display;
        public string Mouse;
        public string Keypad;
        public string Public;
        public int Mode;
        public bool FakeActive;

        public static BindStateKey FromArgs(Dictionary<string, object> args)
        {
            return new BindStateKey
            {
                DisplayHwnd = GetInt(args, "display_hwnd"),
                InputHwnd = GetInt(args, "input_hwnd"),
                Display = GetString(args, "display"),
                Mouse = GetString(args, "mouse"),
                Keypad = GetString(args, "keypad"),
                Public = GetString(args, "public"),
                Mode = GetInt(args, "mode"),
                FakeActive = GetBool(args, "fake_active"),
            };
        }

        public bool Equals(BindStateKey other)
        {
            return DisplayHwnd == other.DisplayHwnd
                && InputHwnd == other.InputHwnd
                && Mode == other.Mode
                && FakeActive == other.FakeActive
                && string.Equals(Display ?? "", other.Display ?? "", StringComparison.Ordinal)
                && string.Equals(Mouse ?? "", other.Mouse ?? "", StringComparison.Ordinal)
                && string.Equals(Keypad ?? "", other.Keypad ?? "", StringComparison.Ordinal)
                && string.Equals(Public ?? "", other.Public ?? "", StringComparison.Ordinal);
        }

        public override bool Equals(object obj)
        {
            return obj is BindStateKey other && Equals(other);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                int hash = DisplayHwnd;
                hash = (hash * 397) ^ InputHwnd;
                hash = (hash * 397) ^ Mode;
                hash = (hash * 397) ^ (FakeActive ? 1 : 0);
                hash = (hash * 397) ^ (Display ?? "").GetHashCode();
                hash = (hash * 397) ^ (Mouse ?? "").GetHashCode();
                hash = (hash * 397) ^ (Keypad ?? "").GetHashCode();
                hash = (hash * 397) ^ (Public ?? "").GetHashCode();
                return hash;
            }
        }
    }

    static DmSlot SlotFor(int hwnd)
    {
        DmSlot slot;
        if (hwnd > 0)
        {
            if (!Slots.TryGetValue(hwnd, out slot))
                throw new InvalidOperationException("窗口 " + hwnd + " 未绑定，请先 bind");
            slot.Touch();
            return slot;
        }
        slot = LastSlot ?? Primary;
        if (slot == null)
            throw new InvalidOperationException("没有可用的插件对象");
        slot.Touch();
        return slot;
    }

    // 动作类命令（键鼠 / 截图 / 发字）指定了 hwnd 就必须已绑定：宁可报错，也不能悄悄拿别的窗口的对象去执行。
    static DmSlot BoundSlotFor(int hwnd)
    {
        if (hwnd <= 0)
            return SlotFor(0);
        DmSlot slot;
        if (!Slots.TryGetValue(hwnd, out slot))
            throw new InvalidOperationException("窗口 " + hwnd + " 未绑定，请先 bind");
        slot.Touch();
        return slot;
    }

    // 为窗口取一个 dm 对象：已有→复用；否则先拿空闲对象；满了直接失败，不淘汰正在绑定的窗口。
    static DmSlot SlotForBind(int hwnd, out bool registered)
    {
        registered = false;
        DmSlot slot;
        if (Slots.TryGetValue(hwnd, out slot))
        {
            slot.Touch();
            return slot;
        }
        slot = TakeFreeSlot();
        if (slot == null)
        {
            if (Slots.Count >= MaxSlots)
                throw new InvalidOperationException("插件对象池已满（最多 " + MaxSlots + " 个窗口），请先解绑其它窗口");
            slot = new DmSlot { Dm = CreateAuthorizedDm() };
            registered = true;
        }
        slot.Hwnd = hwnd;
        slot.Touch();
        Slots[hwnd] = slot;
        return slot;
    }

    static DmSlot TakeFreeSlot()
    {
        if (Primary != null && Primary.Hwnd == 0)
            return Primary;
        if (FreeSlots.Count == 0)
            return null;
        DmSlot slot = FreeSlots[FreeSlots.Count - 1];
        FreeSlots.RemoveAt(FreeSlots.Count - 1);
        return slot;
    }

    // 解绑并把 dm 对象放回空闲池（不释放、不重新 Reg）。
    static void DetachSlot(DmSlot slot)
    {
        if (slot == null)
            return;
        TryUnbind(slot);
        if (slot.Hwnd > 0)
            Slots.Remove(slot.Hwnd);
        slot.Hwnd = 0;
        if (ReferenceEquals(LastSlot, slot))
            LastSlot = null;
        if (!ReferenceEquals(Primary, slot) && slot.Dm != null && !FreeSlots.Contains(slot))
            FreeSlots.Add(slot);
    }

    static void UnbindAll()
    {
        List<DmSlot> all = new List<DmSlot>(Slots.Values);
        foreach (DmSlot slot in all)
            DetachSlot(slot);
        if (Primary != null)
            TryUnbind(Primary);
    }

    static Dictionary<string, object> Stats()
    {
        return new Dictionary<string, object>
        {
            { "slots", Slots.Count },
            { "free", FreeSlots.Count + ((Primary != null && Primary.Hwnd == 0) ? 1 : 0) },
            { "registrations", Registrations },
            { "max_slots", MaxSlots },
        };
    }

    [StructLayout(LayoutKind.Sequential)]
    struct DispatchParams
    {
        public IntPtr Args;
        public IntPtr NamedArgs;
        public int ArgCount;
        public int NamedArgCount;
    }

    [ComImport]
    [Guid("00000001-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IClassFactory
    {
        [PreserveSig]
        int CreateInstance(
            IntPtr outer,
            ref Guid iid,
            [MarshalAs(UnmanagedType.Interface)] out object instance);

        [PreserveSig]
        int LockServer([MarshalAs(UnmanagedType.Bool)] bool lockServer);
    }

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int DllGetClassObjectDelegate(
        ref Guid classId,
        ref Guid interfaceId,
        out IntPtr classFactory);

    static object CreateAuthorizedDm()
    {
        if (DmClassFactory == null)
            throw new InvalidOperationException("插件尚未初始化");
        object dm;
        Guid iid = UnknownId;
        int hr = DmClassFactory.CreateInstance(IntPtr.Zero, ref iid, out dm);
        if (hr < 0 || dm == null)
            throw new InvalidOperationException("无法创建 dm.dmsoft");
        try
        {
            // 无窗口宿主必须关闭厂商弹窗；接口失败时立即停止初始化。
            Invoke(dm, "SetShowErrorMsg", 0);
            int authCode;
            if (!Authorize(dm, RegCode, ExtraCode, out authCode))
                throw new InvalidOperationException(AuthorizeErrorMessage(authCode));
            Registrations++;
            return dm;
        }
        catch
        {
            Marshal.FinalReleaseComObject(dm);
            throw;
        }
    }

    static string _lastVerText = "";
    static string _lastAuthorizeError = "";

    static bool Authorize(object dm, string regCode, string extraCode, out int authCode)
    {
        authCode = 0;
        _lastVerText = "";
        _lastAuthorizeError = "";
        // 免注册仅指不写 COM 注册表；大漠注册码授权仍按官方 Reg 流程执行。
        try
        {
            object verObj = Invoke(dm, "Ver");
            _lastVerText = Convert.ToString(verObj) ?? "";
        }
        catch (Exception ex)
        {
            _lastAuthorizeError = FormatException(ex);
            return false;
        }
        try
        {
            object reg = Invoke(dm, "Reg", regCode, extraCode ?? "");
            authCode = ToInt(reg);
            return authCode == 1;
        }
        catch (Exception ex)
        {
            _lastAuthorizeError = FormatException(ex);
        }
        return false;
    }

    static string FormatException(Exception ex)
    {
        Exception inner = ex == null ? null : (ex.InnerException ?? ex);
        if (inner == null)
            return "";
        string detail = inner.GetType().Name + ": " + (inner.Message ?? "");
        return detail.Length > 240 ? detail.Substring(0, 240) : detail;
    }

    static int ToInt(object value)
    {
        if (value == null || value is string)
            throw new InvalidOperationException("插件授权返回值不是整数");
        return Convert.ToInt32(value);
    }

    static string AuthorizeErrorMessage(int code)
    {
        string detail;
        switch (code)
        {
            case -2: detail = "进程未以管理员方式运行"; break;
            case -1: detail = "无法连接大漠网络（防火墙或断网）"; break;
            case 2: detail = "账户余额不足"; break;
            case 3: detail = "已绑本机但余额不足 50 元"; break;
            case 4: detail = "注册码错误"; break;
            case 5: detail = "机器或 IP 在黑/白名单限制中"; break;
            case 6: detail = "非法使用插件或系统语言非简体中文"; break;
            case 7:
            case 77: detail = "账号/机器码因非法使用被封禁"; break;
            case 8: detail = "附加码不在白名单中"; break;
            case -8: detail = "附加码长度超过 20"; break;
            case -9: detail = "附加码包含非法字符"; break;
            case 777: detail = "同一机器码注册次数超限"; break;
            case 778:
            case 779:
            case 780:
            case 781: detail = "注册失败次数异常，IP/机器被临时限制；请换网络或等一段时间后再试"; break;
            default: detail = "未知原因"; break;
        }
        string verPart = string.IsNullOrEmpty(_lastVerText) ? "ver=空" : ("ver=" + _lastVerText);
        string invokePart = string.IsNullOrEmpty(_lastAuthorizeError) ? "" : ("；调用=" + _lastAuthorizeError);
        return "插件授权失败 code=" + code + "（" + detail + "；" + verPart + invokePart + "）";
    }

    sealed class RpcWork
    {
        public Dictionary<string, object> Message;
        public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        public object Result;
        public Exception Error;
        public bool Running = true;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool SetDllDirectory(string lpPathName);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr LoadLibraryW(string fileName);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    static extern IntPtr GetProcAddress(IntPtr module, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool FreeLibrary(IntPtr module);

    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void LoadTypeLibEx(string file, int kind, out ComTypes.ITypeLib typeLib);

    [DllImport("oleaut32.dll", ExactSpelling = true)]
    static extern int DispInvoke(
        IntPtr instance,
        ComTypes.ITypeInfo typeInfo,
        int dispId,
        ushort flags,
        ref DispatchParams parameters,
        IntPtr result,
        IntPtr exception,
        out int argError);

    [DllImport("oleaut32.dll", ExactSpelling = true)]
    static extern void VariantClear(IntPtr pvarg);

    static void LoadClassFactory(string dmPath)
    {
        if (DmClassFactory != null)
            return;
        try
        {
            LoadEmbeddedTypeInfo(dmPath);
            DmModule = LoadLibraryW(dmPath);
            if (DmModule == IntPtr.Zero)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "无法加载 dm.dll");
            IntPtr entry = GetProcAddress(DmModule, "DllGetClassObject");
            if (entry == IntPtr.Zero)
                throw new InvalidOperationException("dm.dll 缺少 DllGetClassObject");
            DllGetClassObjectDelegate getClassObject =
                (DllGetClassObjectDelegate)Marshal.GetDelegateForFunctionPointer(
                    entry, typeof(DllGetClassObjectDelegate));
            IntPtr factoryPtr;
            Guid classId = DmClassId;
            Guid interfaceId = ClassFactoryId;
            int hr = getClassObject(ref classId, ref interfaceId, out factoryPtr);
            try
            {
                if (hr < 0 || factoryPtr == IntPtr.Zero)
                    throw new InvalidOperationException("无法从 dm.dll 获取 COM 类工厂，HRESULT=0x" + hr.ToString("X8"));
                DmClassFactory = (IClassFactory)Marshal.GetObjectForIUnknown(factoryPtr);
            }
            finally
            {
                if (factoryPtr != IntPtr.Zero) Marshal.Release(factoryPtr);
            }
        }
        catch
        {
            ReleasePluginRuntime();
            throw;
        }
    }

    static void LoadEmbeddedTypeInfo(string dmPath)
    {
        ComTypes.ITypeLib library = null;
        ComTypes.ITypeInfo classInfo = null;
        ComTypes.ITypeInfo interfaceInfo = null;
        try
        {
            // REGKIND_NONE：只读当前 DLL 的内置类型库，不查询或写入 COM 注册表。
            LoadTypeLibEx(dmPath, 2, out library);
            Guid classId = DmClassId;
            library.GetTypeInfoOfGuid(ref classId, out classInfo);
            IntPtr classAttr;
            classInfo.GetTypeAttr(out classAttr);
            int interfaceCount;
            try
            {
                ComTypes.TYPEATTR attr = (ComTypes.TYPEATTR)Marshal.PtrToStructure(classAttr, typeof(ComTypes.TYPEATTR));
                if (attr.typekind != ComTypes.TYPEKIND.TKIND_COCLASS)
                    throw new InvalidOperationException("插件类型库缺少 dmsoft 类定义");
                interfaceCount = attr.cImplTypes;
            }
            finally { classInfo.ReleaseTypeAttr(classAttr); }

            for (int i = 0; i < interfaceCount; i++)
            {
                ComTypes.IMPLTYPEFLAGS flags;
                classInfo.GetImplTypeFlags(i, out flags);
                if ((flags & ComTypes.IMPLTYPEFLAGS.IMPLTYPEFLAG_FDEFAULT) == 0
                    || (flags & ComTypes.IMPLTYPEFLAGS.IMPLTYPEFLAG_FSOURCE) != 0)
                    continue;
                int reference;
                classInfo.GetRefTypeOfImplType(i, out reference);
                classInfo.GetRefTypeInfo(reference, out interfaceInfo);
                ComTypes.ITypeInfo selected = interfaceInfo;
                IntPtr interfaceAttr;
                selected.GetTypeAttr(out interfaceAttr);
                try
                {
                    ComTypes.TYPEATTR attr = (ComTypes.TYPEATTR)Marshal.PtrToStructure(interfaceAttr, typeof(ComTypes.TYPEATTR));
                    if (attr.typekind != ComTypes.TYPEKIND.TKIND_DISPATCH
                        || (attr.wTypeFlags & ComTypes.TYPEFLAGS.TYPEFLAG_FDUAL) == 0)
                        throw new InvalidOperationException("插件类型库默认接口不是双接口");
                    DmInterfaceId = attr.guid;
                    DmTypeInfo = interfaceInfo;
                    interfaceInfo = null;
                    return;
                }
                finally { selected.ReleaseTypeAttr(interfaceAttr); }
            }
            throw new InvalidOperationException("插件类型库缺少默认调用接口");
        }
        finally
        {
            if (interfaceInfo != null) Marshal.FinalReleaseComObject(interfaceInfo);
            if (classInfo != null) Marshal.FinalReleaseComObject(classInfo);
            if (library != null) Marshal.FinalReleaseComObject(library);
        }
    }

    static void ReleasePluginRuntime()
    {
        if (DmTypeInfo != null)
        {
            Marshal.FinalReleaseComObject(DmTypeInfo);
            DmTypeInfo = null;
        }
        DmInterfaceId = Guid.Empty;
        if (DmClassFactory != null)
        {
            Marshal.FinalReleaseComObject(DmClassFactory);
            DmClassFactory = null;
        }
        if (DmModule != IntPtr.Zero)
        {
            FreeLibrary(DmModule);
            DmModule = IntPtr.Zero;
        }
    }

    static void ReleaseDmSlots()
    {
        HashSet<DmSlot> all = new HashSet<DmSlot>(Slots.Values);
        all.UnionWith(FreeSlots);
        if (Primary != null) all.Add(Primary);
        foreach (DmSlot slot in all)
        {
            try { TryUnbind(slot); }
            finally
            {
                if (slot.Dm != null)
                {
                    Marshal.FinalReleaseComObject(slot.Dm);
                    slot.Dm = null;
                }
            }
        }
        Slots.Clear();
        FreeSlots.Clear();
        Primary = null;
        LastSlot = null;
        Inited = false;
    }

    [STAThread]
    static int Main(string[] args)
    {
        PipeName = ParsePipeName(args);
        if (string.IsNullOrEmpty(PipeName))
            return 1;

        Thread accept = new Thread(AcceptLoop);
        accept.IsBackground = true;
        accept.Start();
        try
        {
            foreach (RpcWork work in ComQueue.GetConsumingEnumerable())
                ProcessWork(work);
        }
        finally
        {
            Stopping = true;
            try { ReleaseDmSlots(); }
            finally
            {
                if (Map != null)
                {
                    Map.Dispose();
                    Map = null;
                }
                ReleasePluginRuntime();
            }
        }
        return 0;
    }

    static void AcceptLoop()
    {
        while (!Stopping)
        {
            NamedPipeServerStream pipe = null;
            try
            {
                pipe = new NamedPipeServerStream(PipeName, PipeDirection.InOut, MaxClients, PipeTransmissionMode.Byte);
                pipe.WaitForConnection();
                if (Stopping)
                {
                    pipe.Dispose();
                    break;
                }
                NamedPipeServerStream client = pipe;
                Thread serve = new Thread(() => ServeClient(client));
                serve.IsBackground = true;
                serve.Start();
            }
            catch (Exception)
            {
                if (pipe != null)
                {
                    try { pipe.Dispose(); } catch (Exception) { }
                }
                if (Stopping)
                    break;
                Thread.Sleep(50);
            }
        }
    }

    static void ServeClient(NamedPipeServerStream pipe)
    {
        using (pipe)
        {
            while (!Stopping && pipe.IsConnected)
            {
                Dictionary<string, object> message;
                try
                {
                    message = ReadMessage(pipe);
                }
                catch (EndOfStreamException)
                {
                    break;
                }
                if (message == null)
                    break;
                RpcWork work = new RpcWork { Message = message };
                try
                {
                    ComQueue.Add(work);
                }
                catch (InvalidOperationException)
                {
                    break;
                }
                work.Done.Wait();
                object msgId = GetValue(message, "id");
                if (work.Error != null)
            WriteError(pipe, msgId, SafeError(work.Error, RegCode), RegCode);
                else
                    WriteOk(pipe, msgId, work.Result);
                if (!work.Running)
                    break;
            }
        }
    }

    static void ProcessWork(RpcWork work)
    {
        try
        {
            Dictionary<string, object> message = work.Message;
            string method = GetString(message, "method");
            if (Stopping && !string.Equals(method, "shutdown", StringComparison.Ordinal))
                throw new InvalidOperationException("插件宿主正在停止，拒绝排队命令");
            if (string.Equals(method, "init", StringComparison.Ordinal))
            {
                TryInit(GetArgs(message));
                work.Result = new Dictionary<string, object>();
            }
            else if (string.Equals(method, "shutdown", StringComparison.Ordinal))
            {
                UnbindAll();
                work.Result = new Dictionary<string, object>();
                work.Running = false;
                Stopping = true;
                ComQueue.CompleteAdding();
            }
            else
            {
                if (!Inited)
                    throw new InvalidOperationException("首包必须是 init");
                object result;
                bool running;
                if (!Dispatch(Map, method, GetArgs(message), out result, out running))
                    throw new InvalidOperationException("unknown method: " + method);
                work.Result = result;
                work.Running = running;
                if (!running)
                {
                    Stopping = true;
                    ComQueue.CompleteAdding();
                }
            }
        }
        catch (Exception ex)
        {
            work.Error = ex;
        }
        work.Done.Set();
    }

    static void TryInit(Dictionary<string, object> initArgs)
    {
        lock (InitLock)
        {
            if (Inited)
                return;
            string pluginDir = GetString(initArgs, "plugin_dir");
            RegCode = GetString(initArgs, "reg_code");
            string extraCode = GetString(initArgs, "extra_code");
            ExtraCode = extraCode ?? "";
            if (string.IsNullOrWhiteSpace(RegCode))
                throw new InvalidOperationException("未填写插件注册码");
            if (string.IsNullOrWhiteSpace(pluginDir) || !Directory.Exists(pluginDir))
                throw new InvalidOperationException("插件目录无效");
            if (!SetDllDirectory(pluginDir))
                throw new InvalidOperationException("SetDllDirectory 失败");
            string dmPath = Path.Combine(pluginDir, "dm.dll");
            if (!File.Exists(dmPath))
                throw new InvalidOperationException("缺少 dm.dll: " + dmPath);
            try
            {
                LoadClassFactory(dmPath);
                Primary = new DmSlot { Dm = CreateAuthorizedDm() };
                Primary.Touch();
                Registrations = 1;
                Map = MemoryMappedFile.CreateOrOpen(MapNameFromPipe(PipeName), FrameMapSize);
                Inited = true;
            }
            catch
            {
                try { ReleaseDmSlots(); }
                finally { ReleasePluginRuntime(); }
                throw;
            }
        }
    }

    // 带 hwnd 的命令路由到该窗口的 dm 对象；不带 hwnd 时用最近一次绑定的对象。
    static bool Dispatch(MemoryMappedFile map, string method, Dictionary<string, object> args, out object result, out bool running)
    {
        running = true;
        result = null;
        int hwnd = GetInt(args, "hwnd");
        switch (method)
        {
            case "bind":
                result = DoBind(args);
                return true;
            case "unbind":
                // 解绑后对象回空闲池，下个窗口复用，不重新 Reg
                if (hwnd > 0)
                {
                    DmSlot bound;
                    if (Slots.TryGetValue(hwnd, out bound))
                        DetachSlot(bound);
                }
                else
                {
                    UnbindAll();
                }
                result = Stats();
                return true;
            case "stats":
                result = Stats();
                return true;
            case "force_unbind":
                result = DoForceUnbind(hwnd);
                return true;
            case "is_bind":
                result = DoIsBind(hwnd);
                return true;
            case "fake_active":
                result = DoFakeActive(BoundSlotFor(hwnd), GetBool(args, "enable"));
                return true;
            case "capture":
                result = DoCapture(BoundSlotFor(hwnd).Dm, map, args);
                return true;
            case "move_to":
                result = CallOk(BoundSlotFor(hwnd).Dm, "MoveTo", GetInt(args, "x"), GetInt(args, "y"));
                return true;
            case "mouse_click":
                result = CallOk(BoundSlotFor(hwnd).Dm, MouseMethod(GetString(args, "button"), "click"));
                return true;
            case "mouse_double_click":
                result = DoMouseDoubleClick(BoundSlotFor(hwnd).Dm, GetString(args, "button"), GetInt(args, "interval_ms", 50));
                return true;
            case "mouse_down":
                result = CallOk(BoundSlotFor(hwnd).Dm, MouseMethod(GetString(args, "button"), "down"));
                return true;
            case "mouse_up":
                result = CallOk(BoundSlotFor(hwnd).Dm, MouseMethod(GetString(args, "button"), "up"));
                return true;
            case "wheel":
                result = DoWheel(BoundSlotFor(hwnd).Dm, GetInt(args, "delta"));
                return true;
            case "key_down":
                result = CallOk(BoundSlotFor(hwnd).Dm, "KeyDown", GetInt(args, "vk_code"));
                return true;
            case "key_up":
                result = CallOk(BoundSlotFor(hwnd).Dm, "KeyUp", GetInt(args, "vk_code"));
                return true;
            case "key_press":
                result = CallOk(BoundSlotFor(hwnd).Dm, "KeyPress", GetInt(args, "vk_code"));
                return true;
            case "key_press_str":
                result = CallOk(BoundSlotFor(hwnd).Dm, "KeyPressStr", GetString(args, "text"), GetInt(args, "delay", 30));
                return true;
            case "send_string":
                // hwnd 决定用哪个窗口的 dm 对象；target 是实际收字的（子）窗口，缺省与 hwnd 相同
                result = DoSendString(BoundSlotFor(hwnd).Dm, GetInt(args, "target", hwnd), GetString(args, "text"), GetBool(args, "ime"));
                return true;
            case "version":
                result = CallText(Primary.Dm, "Ver");
                return true;
            case "activation_mode":
                // This is deliberately exposed so the authorization probe can reject
                // a stale host that still activates dmsoft through the COM registry.
                result = ActivationMode;
                return true;
            case "client_size":
                result = DoClientSize(SlotFor(hwnd).Dm, hwnd);
                return true;
            case "memory_call":
                result = DoMemoryCall(BoundSlotFor(hwnd).Dm, hwnd, args);
                return true;
            case "last_error":
                result = LastError(SlotFor(hwnd).Dm);
                return true;
            case "host_pid":
                result = Process.GetCurrentProcess().Id;
                return true;
            case "shutdown":
                UnbindAll();
                result = new Dictionary<string, object>();
                running = false;
                return true;
            default:
                return false;
        }
    }

    static Dictionary<string, object> DoIsBind(int hwnd)
    {
        bool bound = false;
        bool cached = false;
        string error = "";
        object raw = null;
        DmSlot slot;
        if (hwnd > 0 && Slots.TryGetValue(hwnd, out slot))
        {
            cached = slot.BindOk;
            bool asked = TryIsBoundByDm(slot.Dm, hwnd, out bound, out raw, out error);
            if (asked && !bound && slot.BindOk)
                slot.ClearBind();
            else if (!asked)
                bound = slot.BindOk;
        }
        return new Dictionary<string, object>
        {
            { "bound", bound },
            { "cached", cached },
            { "raw", raw == null ? "" : Convert.ToString(raw) },
            { "error", error ?? "" },
        };
    }

    static bool IsBoundByDm(object dm, int hwnd)
    {
        bool bound;
        object raw;
        string error;
        return TryIsBoundByDm(dm, hwnd, out bound, out raw, out error) && bound;
    }

    static bool TryIsBoundByDm(object dm, int hwnd, out bool bound, out object raw, out string error)
    {
        bound = false;
        raw = null;
        error = "";
        // 本机 dm.dll 类型库：IsBind(hwnd)。无参会 TargetParameterCountException。
        if (!TryInvoke(dm, "IsBind", out raw, out error, hwnd))
            return false;
        bound = IsSuccessInt(raw);
        return true;
    }

    static Dictionary<string, object> DoForceUnbind(int hwnd)
    {
        bool ok = false;
        DmSlot slot;
        if (hwnd > 0 && Slots.TryGetValue(hwnd, out slot))
        {
            TryUnbind(slot);
            ok = true;
        }
        if (hwnd > 0)
        {
            object dm = (Primary != null) ? Primary.Dm : null;
            if (dm != null && CallOk(dm, "ForceUnBindWindow", hwnd))
                ok = true;
        }
        return new Dictionary<string, object> { { "ok", ok } };
    }

    static bool DoFakeActive(DmSlot slot, bool enable)
    {
        if (slot == null || slot.Dm == null)
            return false;
        bool ok = CallOk(slot.Dm, "EnableFakeActive", enable ? 1 : 0);
        if (ok)
            slot.FakeActive = enable;
        return ok;
    }

    static Dictionary<string, object> BindResult(bool ok, int lastError, string error, string api, bool registered = false)
    {
        return new Dictionary<string, object>
        {
            { "ok", ok },
            { "last_error", lastError },
            { "error", error ?? "" },
            { "api", api ?? "" },
            // 本次 bind 是否为该窗口新建了 dm 对象，以及宿主累计对象创建数，供调用方记账
            { "registered", registered },
            { "registrations", Registrations },
        };
    }

    static Dictionary<string, object> DoBind(Dictionary<string, object> args)
    {
        BindStateKey bindKey = BindStateKey.FromArgs(args);
        int displayHwnd = bindKey.DisplayHwnd;
        int inputHwnd = bindKey.InputHwnd;
        if (displayHwnd <= 0)
            throw new InvalidOperationException("bind 缺少 display_hwnd");
        if (inputHwnd > 0 && inputHwnd != displayHwnd)
            throw new InvalidOperationException("无法分离绑定: 大漠 BindWindowEx 不支持独立 input_hwnd");

        bool registered;
        DmSlot slot = SlotForBind(displayHwnd, out registered);
        object dm = slot.Dm;
        // 宿主记得已绑定还要问一下大漠：目标窗口重建等情况下绑定会静默失效。
        if (slot.BindOk && bindKey.Equals(slot.Key))
        {
            if (IsBoundByDm(dm, displayHwnd))
            {
                LastSlot = slot;
                return BindResult(true, 0, "", "cached", registered);
            }
            slot.ClearBind();
        }

        string display = bindKey.Display;
        string mouse = bindKey.Mouse;
        string keypad = bindKey.Keypad;
        string publicOptions = bindKey.Public ?? "";
        int mode = bindKey.Mode;
        // 同一窗口换参数前先解绑，避免大漠 -13/-17（上次绑定未解除）。
        if (slot.BindOk)
            TryUnbind(slot);

        string api = (NeedsBindWindowEx(display, mouse, keypad) || publicOptions.Length > 0 || mode == 101 || mode == 103)
            ? "BindWindowEx"
            : "BindWindow";
        object raw;
        string invokeError;
        bool invoked = api == "BindWindowEx"
            ? TryInvoke(dm, api, out raw, out invokeError, displayHwnd, display, mouse, keypad, publicOptions, mode)
            : TryInvoke(dm, api, out raw, out invokeError, displayHwnd, display, mouse, keypad, mode);
        bool ok = invoked && IsSuccessInt(raw);
        if (ok)
        {
            slot.BindOk = true;
            slot.Key = bindKey;
            LastSlot = slot;
            if (bindKey.FakeActive)
                DoFakeActive(slot, true);
            return BindResult(true, 0, "", api, registered);
        }
        slot.ClearBind();
        // 失败时把大漠的 GetLastError 和 COM 异常一并带回，调用方据此给出可读原因。
        int lastError = invoked ? LastError(dm) : 0;
        string error = invoked
            ? (api + " 返回 " + (raw == null ? "null" : Convert.ToString(raw)))
            : (api + " 调用异常: " + invokeError);
        return BindResult(false, lastError, error, api, registered);
    }

    static bool TryInvoke(object dm, string name, out object result, out string error, params object[] invokeArgs)
    {
        try
        {
            result = Invoke(dm, name, invokeArgs);
            error = "";
            return true;
        }
        catch (Exception ex)
        {
            Exception inner = ex.InnerException ?? ex;
            result = null;
            error = inner.GetType().Name + ": " + inner.Message;
            return false;
        }
    }

    static bool NeedsBindWindowEx(string display, string mouse, string keypad)
    {
        return (!string.IsNullOrEmpty(display) && display.IndexOf('.') >= 0)
            || (!string.IsNullOrEmpty(mouse) && mouse.IndexOf('.') >= 0)
            || (!string.IsNullOrEmpty(keypad) && keypad.IndexOf('.') >= 0);
    }

    static Dictionary<string, object> DoCapture(object dm, MemoryMappedFile map, Dictionary<string, object> args)
    {
        int hwnd = GetInt(args, "hwnd");
        int width;
        int height;
        if (!TryGetClientSize(dm, hwnd, out width, out height) || width <= 0 || height <= 0)
            throw new InvalidOperationException("GetClientSize 失败");
        int needed = FrameHeaderSize + width * 3 * height;
        if (needed > FrameMapSize)
            throw new InvalidOperationException("frame exceeds 64MiB map");

        byte[] bmpBytes = GetScreenDataBmp(dm, 0, 0, width, height);
        if (bmpBytes == null || bmpBytes.Length == 0)
            throw new InvalidOperationException("GetScreenDataBmp 截图为空");
        byte[] bgr = BmpToBgr(bmpBytes, out width, out height);
        int stride = width * 3;
        WriteBgrFrame(map, bgr, width, height, stride);
        return new Dictionary<string, object>
        {
            { "width", width },
            { "height", height },
            { "stride", stride },
        };
    }

    static Dictionary<string, object> DoClientSize(object dm, int hwnd)
    {
        int width;
        int height;
        if (!TryGetClientSize(dm, hwnd, out width, out height))
        {
            throw new InvalidOperationException("获取插件窗口客户区大小失败");
        }
        return new Dictionary<string, object>
        {
            { "width", width },
            { "height", height },
        };
    }

    static object DoMemoryCall(object dm, int hwnd, Dictionary<string, object> args)
    {
        string operation = GetString(args, "operation");
        string addr = GetString(args, "addr");
        string type = GetString(args, "type");
        switch (operation)
        {
            case "module_base": return Invoke(dm, "GetModuleBaseAddr", hwnd, GetString(args, "module"));
            case "module_size": return Invoke(dm, "GetModuleSize", hwnd, GetString(args, "module"));
            case "read_int": return Invoke(dm, "ReadInt", hwnd, addr, GetRequiredInt(args, "type"));
            case "read_float": return Invoke(dm, "ReadFloat", hwnd, addr);
            case "read_double": return Invoke(dm, "ReadDouble", hwnd, addr);
            case "read_string": return Invoke(dm, "ReadString", hwnd, addr, GetRequiredInt(args, "type"), GetRequiredInt(args, "length"));
            case "read_data": return Invoke(dm, "ReadData", hwnd, addr, GetRequiredInt(args, "length"));
            case "write_int": return Invoke(dm, "WriteInt", hwnd, addr, GetRequiredInt(args, "type"), GetRequiredInt(args, "value"));
            case "write_float": return Invoke(dm, "WriteFloat", hwnd, addr, GetRequiredDouble(args, "value"));
            case "write_double": return Invoke(dm, "WriteDouble", hwnd, addr, GetRequiredDouble(args, "value"));
            case "write_string": return Invoke(dm, "WriteString", hwnd, addr, GetRequiredInt(args, "type"), GetString(args, "value"));
            case "write_data": return Invoke(dm, "WriteData", hwnd, addr, GetString(args, "value"));
            case "find_int": return Invoke(dm, "FindInt", hwnd, GetString(args, "range"), GetRequiredInt(args, "min"), GetRequiredInt(args, "max"), GetRequiredInt(args, "type"));
            case "find_float": return Invoke(dm, "FindFloat", hwnd, GetString(args, "range"), GetRequiredDouble(args, "min"), GetRequiredDouble(args, "max"));
            case "find_double": return Invoke(dm, "FindDouble", hwnd, GetString(args, "range"), GetRequiredDouble(args, "min"), GetRequiredDouble(args, "max"));
            case "find_string": return Invoke(dm, "FindString", hwnd, GetString(args, "range"), GetString(args, "value"), GetRequiredInt(args, "type"));
            case "find_data": return Invoke(dm, "FindData", hwnd, GetString(args, "range"), GetString(args, "value"));
            case "virtual_alloc": return Invoke(dm, "VirtualAllocEx", hwnd, GetAbsoluteMemoryAddress(args), GetRequiredInt(args, "size"), GetRequiredInt(args, "allocation_type"));
            case "virtual_free": return Invoke(dm, "VirtualFreeEx", hwnd, GetAbsoluteMemoryAddress(args));
            case "free_process_memory": return Invoke(dm, "FreeProcessMemory", hwnd);
            case "asm_add": return Invoke(dm, "AsmAdd", GetString(args, "instruction"));
            case "asm_clear": return Invoke(dm, "AsmClear");
            case "asm_call": return Invoke(dm, "AsmCall", hwnd, GetRequiredInt(args, "mode"));
            case "asm_call_ex": return Invoke(dm, "AsmCallEx", hwnd, GetRequiredInt(args, "mode"), addr);
            case "asm_timeout": return Invoke(dm, "AsmSetTimeout", GetRequiredInt(args, "timeout"), GetRequiredInt(args, "param"));
            default: throw new InvalidOperationException("不支持的大漠内存操作: " + operation);
        }
    }

    // 大漠只有 LeftDoubleClick；右键/中键没有对应接口，用两次单击按双击时序凑出来。
    static bool DoMouseDoubleClick(object dm, string button, int intervalMs)
    {
        string normalized = (button ?? "left").Trim().ToLowerInvariant();
        if (normalized == "left" || normalized == "")
            return CallOk(dm, "LeftDoubleClick");
        string clickMethod = MouseMethod(normalized, "click");
        if (!CallOk(dm, clickMethod))
            return false;
        Thread.Sleep(Math.Max(0, Math.Min(intervalMs, 400)));
        return CallOk(dm, clickMethod);
    }

    // delta 为滚动格数（正上负下）；调用方已把 WHEEL_DELTA 单位换算成格数。
    static bool DoWheel(object dm, int delta)
    {
        if (delta == 0)
            return false;
        int notches = Math.Min(Math.Abs(delta), 60);
        string method = delta > 0 ? "WheelUp" : "WheelDown";
        for (int i = 0; i < notches; i++)
        {
            if (!CallOk(dm, method))
                return false;
        }
        return true;
    }

    // 非 ASCII 文本（中文等）走 SendString，KeyPressStr 只认按键名。
    // ime=true 走 SendStringIme（需绑定时带 dx.public.input.ime）；注意该方法没有 hwnd 参数，目标由该 dm 对象的绑定决定。
    static bool DoSendString(object dm, int hwnd, string text, bool ime)
    {
        if (string.IsNullOrEmpty(text))
            return true;
        if (hwnd <= 0)
            return false;
        if (ime)
            return CallOk(dm, "SendStringIme", text);
        return CallOk(dm, "SendString", hwnd, text);
    }

    static bool TryGetClientSize(object dm, int hwnd, out int width, out int height)
    {
        width = 0;
        height = 0;
        object[] invokeArgs = { hwnd, 0, 0 };
        object ret = InvokeByRef(dm, "GetClientSize", invokeArgs, new[] { false, true, true });
        width = Convert.ToInt32(invokeArgs[1] ?? 0);
        height = Convert.ToInt32(invokeArgs[2] ?? 0);
        if (width > 0 && height > 0)
            return true;
        return IsSuccessInt(ret);
    }

    static byte[] GetScreenDataBmp(object dm, int x1, int y1, int x2, int y2)
    {
        try
        {
            object[] invokeArgs = { x1, y1, x2, y2, null, 0 };
            object ret = InvokeByRef(
                dm,
                "GetScreenDataBmp",
                invokeArgs,
                new[] { false, false, false, false, true, true });
            if (!IsSuccessInt(ret))
                return null;
            return CopyOutBytes(invokeArgs[4], invokeArgs[5]);
        }
        catch (Exception)
        {
            return null;
        }
    }

    static void WriteBgrFrame(MemoryMappedFile map, byte[] bgr, int width, int height, int stride)
    {
        lock (FrameLock)
        {
            using (MemoryMappedViewAccessor accessor = map.CreateViewAccessor(0, FrameMapSize, MemoryMappedFileAccess.ReadWrite))
            {
                accessor.Write(0, FrameMagic);
                accessor.Write(4, width);
                accessor.Write(8, height);
                accessor.Write(12, stride);
                accessor.WriteArray(16, bgr, 0, bgr.Length);
            }
        }
    }

    static byte[] BmpToBgr(byte[] bmpBytes, out int width, out int height)
    {
        width = 0;
        height = 0;
        byte[] file = EnsureBmpFile(bmpBytes);
        using (var ms = new MemoryStream(file, writable: false))
        using (var src = new Bitmap(ms))
        {
            return BitmapToBgr(src, out width, out height);
        }
    }

    static byte[] BitmapToBgr(Bitmap src, out int width, out int height)
    {
        width = src.Width;
        height = src.Height;
        int stride = width * 3;
        byte[] dest = new byte[stride * height];
        Bitmap work = src;
        Bitmap owned = null;
        if (src.PixelFormat != PixelFormat.Format24bppRgb)
        {
            owned = new Bitmap(width, height, PixelFormat.Format24bppRgb);
            using (Graphics g = Graphics.FromImage(owned))
                g.DrawImage(src, 0, 0, width, height);
            work = owned;
        }
        try
        {
            var rect = new Rectangle(0, 0, width, height);
            BitmapData data = work.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
            try
            {
                for (int y = 0; y < height; y++)
                    Marshal.Copy(IntPtr.Add(data.Scan0, y * data.Stride), dest, y * stride, stride);
            }
            finally
            {
                work.UnlockBits(data);
            }
        }
        finally
        {
            if (owned != null)
                owned.Dispose();
        }
        return dest;
    }

    static byte[] EnsureBmpFile(byte[] data)
    {
        if (data == null || data.Length < 2)
            return data;
        if (data[0] == 0x42 && data[1] == 0x4D)
            return data;
        int headerSize = 40;
        if (data.Length >= 4)
        {
            int claimed = BitConverter.ToInt32(data, 0);
            if (claimed >= 12 && claimed < 256)
                headerSize = claimed;
        }
        byte[] file = new byte[14 + data.Length];
        file[0] = 0x42;
        file[1] = 0x4D;
        BitConverter.GetBytes(file.Length).CopyTo(file, 2);
        BitConverter.GetBytes(14 + headerSize).CopyTo(file, 10);
        Buffer.BlockCopy(data, 0, file, 14, data.Length);
        return file;
    }

    static byte[] CopyOutBytes(object data, object sizeObj)
    {
        if (data is byte[] arr)
            return arr;
        int size = 0;
        try
        {
            size = Convert.ToInt32(sizeObj);
        }
        catch (Exception)
        {
        }
        IntPtr ptr = ToIntPtr(data);
        if (ptr == IntPtr.Zero || size <= 0)
            return null;
        byte[] bytes = new byte[size];
        Marshal.Copy(ptr, bytes, 0, size);
        return bytes;
    }

    static IntPtr ToIntPtr(object value)
    {
        if (value == null || value is DBNull)
            return IntPtr.Zero;
        if (value is IntPtr ip)
            return ip;
        try
        {
            return new IntPtr(Convert.ToInt64(value));
        }
        catch (Exception)
        {
            return IntPtr.Zero;
        }
    }

    static void TryUnbind(DmSlot slot)
    {
        if (slot == null || slot.Dm == null)
            return;
        object dm = slot.Dm;
        try
        {
            if (slot.FakeActive)
                CallOk(dm, "EnableFakeActive", 0);
            bool released = false;
            if (slot.BindOk)
                released = CallOk(dm, "UnBindWindow");
            // UnBindWindow 偶尔返回 0（窗口已销毁或钩子残留），强制解绑兜底以释放资源。
            if (slot.BindOk && !released && slot.Hwnd > 0)
                CallOk(dm, "ForceUnBindWindow", slot.Hwnd);
        }
        catch (Exception)
        {
        }
        finally
        {
            slot.ClearBind();
        }
    }

    static int LastError(object dm)
    {
        return Convert.ToInt32(Invoke(dm, "GetLastError"));
    }

    static string MouseMethod(string button, string action)
    {
        string prefix;
        switch (button)
        {
            case "right":
                prefix = "Right";
                break;
            case "middle":
                prefix = "Middle";
                break;
            case "left":
                prefix = "Left";
                break;
            default:
                throw new InvalidOperationException("插件鼠标按钮无效：" + button);
        }
        // 双击不走这里：大漠只有 LeftDoubleClick，由 DoMouseDoubleClick 单独处理
        switch (action)
        {
            case "down":
                return prefix + "Down";
            case "up":
                return prefix + "Up";
            case "click":
                return prefix + "Click";
            default:
                throw new InvalidOperationException("插件鼠标动作无效：" + action);
        }
    }

    static bool IsSuccessInt(object value)
    {
        if (value == null || value is string)
            return false;
        try
        {
            return Convert.ToInt32(value) == 1;
        }
        catch (Exception)
        {
            return false;
        }
    }

    static string CallText(object dm, string name, params object[] invokeArgs)
    {
        object value = Invoke(dm, name, invokeArgs);
        return value == null ? "" : Convert.ToString(value);
    }

    static object Invoke(object target, string name, params object[] invokeArgs)
    {
        object[] args = invokeArgs ?? new object[0];
        return InvokeByRef(target, name, args, new bool[args.Length]);
    }

    const int VariantSize = 16;
    const ushort VtVariant = 12;
    const ushort VtByRef = 0x4000;
    const ushort DispatchMethod = 1;

    static void ZeroMemory(IntPtr pointer, int size)
    {
        for (int i = 0; i < size; i++)
            Marshal.WriteByte(pointer, i, 0);
    }

    static int GetDispId(string name)
    {
        int[] ids = new int[1];
        try
        {
            DmTypeInfo.GetIDsOfNames(new[] { name }, 1, ids);
            return ids[0];
        }
        catch (COMException ex)
        {
            throw new InvalidOperationException("找不到插件方法 " + name + " HRESULT=0x" + ex.HResult.ToString("X8"), ex);
        }
    }

    // 用 DLL 内置双接口类型信息直接调用 vtable，避开 IDispatch 对注册类型库的依赖。
    // GetClientSize / GetScreenDataBmp 的出参使用 VT_BYREF | VT_VARIANT 写回。
    static object InvokeByRef(object target, string name, object[] args, bool[] byref)
    {
        if (target == null)
            throw new InvalidOperationException("插件对象为空");
        if (args == null)
            args = new object[0];
        if (byref == null || byref.Length != args.Length)
            throw new InvalidOperationException("变参标记长度与参数不一致");
        if (DmTypeInfo == null)
            throw new InvalidOperationException("插件调用类型信息尚未加载");

        int dispId = GetDispId(name);
        int count = args.Length;
        IntPtr argVars = IntPtr.Zero;
        IntPtr resultVar = IntPtr.Zero;
        IntPtr unknown = IntPtr.Zero;
        IntPtr instance = IntPtr.Zero;
        IntPtr exception = IntPtr.Zero;
        IntPtr[] varStores = count > 0 ? new IntPtr[count] : null;
        try
        {
            resultVar = Marshal.AllocHGlobal(VariantSize);
            ZeroMemory(resultVar, VariantSize);
            exception = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(ComTypes.EXCEPINFO)));
            ZeroMemory(exception, Marshal.SizeOf(typeof(ComTypes.EXCEPINFO)));
            unknown = Marshal.GetIUnknownForObject(target);
            Guid interfaceId = DmInterfaceId;
            Marshal.ThrowExceptionForHR(Marshal.QueryInterface(unknown, ref interfaceId, out instance));
            if (count > 0)
            {
                argVars = Marshal.AllocHGlobal(VariantSize * count);
                ZeroMemory(argVars, VariantSize * count);
                for (int i = 0; i < count; i++)
                {
                    int src = count - 1 - i;
                    IntPtr slot = IntPtr.Add(argVars, i * VariantSize);
                    if (!byref[src])
                    {
                        Marshal.GetNativeVariantForObject(args[src], slot);
                        continue;
                    }
                    // IDispatch 晚绑定的变参一律是 VARIANT*，不能直接传 LONG*。
                    IntPtr inner = Marshal.AllocHGlobal(VariantSize);
                    varStores[src] = inner;
                    ZeroMemory(inner, VariantSize);
                    if (args[src] != null)
                        Marshal.GetNativeVariantForObject(args[src], inner);
                    Marshal.WriteInt16(slot, 0, unchecked((short)(VtVariant | VtByRef)));
                    Marshal.WriteIntPtr(slot, 8, inner);
                }
            }

            DispatchParams dispParams = new DispatchParams();
            dispParams.Args = argVars;
            dispParams.NamedArgs = IntPtr.Zero;
            dispParams.ArgCount = count;
            dispParams.NamedArgCount = 0;
            int argError;
            int hr = DispInvoke(
                instance,
                DmTypeInfo,
                dispId,
                DispatchMethod,
                ref dispParams,
                resultVar,
                exception,
                out argError);
            if (hr < 0)
            {
                ComTypes.EXCEPINFO info = (ComTypes.EXCEPINFO)Marshal.PtrToStructure(exception, typeof(ComTypes.EXCEPINFO));
                throw new COMException(name + " 调用失败 HRESULT=0x" + hr.ToString("X8")
                    + (string.IsNullOrEmpty(info.bstrDescription) ? "" : "；" + info.bstrDescription), hr);
            }

            for (int src = 0; src < count; src++)
            {
                if (byref[src] && varStores[src] != IntPtr.Zero)
                    args[src] = Marshal.GetObjectForNativeVariant(varStores[src]);
            }
            return Marshal.GetObjectForNativeVariant(resultVar);
        }
        finally
        {
            if (argVars != IntPtr.Zero)
            {
                for (int i = 0; i < count; i++)
                    VariantClear(IntPtr.Add(argVars, i * VariantSize));
                Marshal.FreeHGlobal(argVars);
            }
            if (varStores != null)
            {
                for (int i = 0; i < varStores.Length; i++)
                {
                    if (varStores[i] != IntPtr.Zero)
                    {
                        VariantClear(varStores[i]);
                        Marshal.FreeHGlobal(varStores[i]);
                    }
                }
            }
            if (resultVar != IntPtr.Zero)
            {
                VariantClear(resultVar);
                Marshal.FreeHGlobal(resultVar);
            }
            if (exception != IntPtr.Zero)
            {
                Marshal.DestroyStructure(exception, typeof(ComTypes.EXCEPINFO));
                Marshal.FreeHGlobal(exception);
            }
            if (instance != IntPtr.Zero) Marshal.Release(instance);
            if (unknown != IntPtr.Zero) Marshal.Release(unknown);
        }
    }

    static bool CallOk(object dm, string name, params object[] invokeArgs)
    {
        try
        {
            return IsSuccessInt(Invoke(dm, name, invokeArgs));
        }
        catch (Exception)
        {
            return false;
        }
    }

    static string ParsePipeName(string[] args)
    {
        if (args == null)
            return null;
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], "--pipe", StringComparison.Ordinal))
                return args[i + 1];
        }
        return null;
    }

    static string MapNameFromPipe(string pipeName)
    {
        string pid = pipeName ?? "";
        if (pid.StartsWith(PipePrefix, StringComparison.Ordinal))
            pid = pid.Substring(PipePrefix.Length);
        return @"Local\lca-plugin-frame-" + pid;
    }

    static Dictionary<string, object> ReadMessage(Stream stream)
    {
        byte[] header = ReadExact(stream, 4);
        int size = BitConverter.ToInt32(header, 0);
        if (size < 0 || size > 8 * 1024 * 1024)
            throw new InvalidOperationException("invalid plugin message size");
        byte[] raw = ReadExact(stream, size);
        string json = Encoding.UTF8.GetString(raw);
        object parsed = Json.DeserializeObject(json);
        Dictionary<string, object> message = AsDict(parsed);
        if (message == null)
            throw new InvalidOperationException("plugin message must be an object");
        return message;
    }

    static byte[] ReadExact(Stream stream, int count)
    {
        byte[] buf = new byte[count];
        int off = 0;
        while (off < count)
        {
            int n = stream.Read(buf, off, count - off);
            if (n <= 0)
                throw new EndOfStreamException();
            off += n;
        }
        return buf;
    }

    static void WriteOk(Stream stream, object id, object result)
    {
        var reply = new Dictionary<string, object>
        {
            { "id", id },
            { "ok", true },
            { "result", result },
        };
        WriteRaw(stream, reply);
    }

    static void WriteError(Stream stream, object id, string error, string regCode)
    {
        var reply = new Dictionary<string, object>
        {
            { "id", id },
            { "ok", false },
            { "error", StripSecret(error ?? "plugin host error", regCode) },
        };
        WriteRaw(stream, reply);
    }

    static void WriteRaw(Stream stream, Dictionary<string, object> reply)
    {
        string json = Json.Serialize(reply);
        byte[] raw = Encoding.UTF8.GetBytes(json);
        byte[] header = BitConverter.GetBytes(raw.Length);
        stream.Write(header, 0, 4);
        stream.Write(raw, 0, raw.Length);
        stream.Flush();
    }

    static string SafeError(Exception ex, string regCode)
    {
        string message = ex == null ? "plugin host error" : (ex.Message ?? ex.GetType().Name);
        return StripSecret(message, regCode);
    }

    static string StripSecret(string message, string regCode)
    {
        if (string.IsNullOrEmpty(message))
            return "plugin host error";
        if (!string.IsNullOrEmpty(regCode))
            message = message.Replace(regCode, "***");
        return message;
    }

    static Dictionary<string, object> GetArgs(Dictionary<string, object> message)
    {
        return AsDict(GetValue(message, "args")) ?? new Dictionary<string, object>();
    }

    static Dictionary<string, object> AsDict(object value)
    {
        if (value is Dictionary<string, object> dict)
            return dict;
        if (value is IDictionary raw)
        {
            var copy = new Dictionary<string, object>();
            foreach (DictionaryEntry entry in raw)
            {
                if (entry.Key != null)
                    copy[Convert.ToString(entry.Key)] = entry.Value;
            }
            return copy;
        }
        return null;
    }

    static object GetValue(Dictionary<string, object> map, string key)
    {
        if (map == null)
            return null;
        object value;
        return map.TryGetValue(key, out value) ? value : null;
    }

    static string GetString(Dictionary<string, object> map, string key)
    {
        object value = GetValue(map, key);
        return value == null || value is DBNull ? "" : Convert.ToString(value);
    }

    static int GetInt(Dictionary<string, object> map, string key, int fallback = 0)
    {
        object value = GetValue(map, key);
        if (value == null || value is DBNull)
            return fallback;
        return GetRequiredInt(map, key);
    }

    static long GetAbsoluteMemoryAddress(Dictionary<string, object> map)
    {
        object value = GetValue(map, "addr");
        long address;
        if (value is string text)
        {
            if (!long.TryParse(text, System.Globalization.NumberStyles.AllowHexSpecifier,
                System.Globalization.CultureInfo.InvariantCulture, out address) || address < 0)
                throw new InvalidOperationException("内存申请和释放地址必须是非负 64 位十六进制绝对地址");
            return address;
        }
        if (value is int || value is long)
        {
            address = Convert.ToInt64(value);
            if (address >= 0) return address;
        }
        throw new InvalidOperationException("内存申请和释放地址必须是地址文本或非负 64 位整数");
    }

    static int GetRequiredInt(Dictionary<string, object> map, string key)
    {
        object value = GetValue(map, key);
        if (value == null || value is DBNull)
            throw new InvalidOperationException("缺少整数参数: " + key);
        if (!(value is int) && !(value is long))
            throw new InvalidOperationException("整数参数无效: " + key);
        try { return Convert.ToInt32(value); }
        catch (Exception ex) { throw new InvalidOperationException("整数参数无效: " + key, ex); }
    }

    static double GetRequiredDouble(Dictionary<string, object> map, string key)
    {
        object value = GetValue(map, key);
        if (value == null || value is DBNull)
            throw new InvalidOperationException("缺少小数参数: " + key);
        try { return Convert.ToDouble(value); }
        catch (Exception ex) { throw new InvalidOperationException("小数参数无效: " + key, ex); }
    }

    static bool GetBool(Dictionary<string, object> map, string key, bool fallback = false)
    {
        object value = GetValue(map, key);
        if (value == null || value is DBNull)
            return fallback;
        if (value is bool flag)
            return flag;
        throw new InvalidOperationException("布尔参数无效: " + key);
    }

}
