using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
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
    static readonly object InitLock = new object();
    static readonly BlockingCollection<RpcWork> ComQueue = new BlockingCollection<RpcWork>();
    static string PipeName;
    static MemoryMappedFile Map;
    static string RegCode = "";
    static string ExtraCode = "";
    static Type DmProgType;
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

    // 查询类命令（client_size / last_error）允许回退到最近绑定或主对象。
    static DmSlot SlotFor(int hwnd)
    {
        DmSlot slot;
        if (hwnd > 0 && Slots.TryGetValue(hwnd, out slot))
        {
            slot.Touch();
            return slot;
        }
        slot = LastSlot ?? Primary;
        if (slot != null)
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

    // 为窗口取一个 dm 对象：已有→复用；否则先拿空闲对象；满了淘汰最久未用的窗口；都没有才新建并 Reg。
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
        if (slot == null && Slots.Count >= MaxSlots)
        {
            DetachSlot(LeastRecentlyUsedSlot());
            slot = TakeFreeSlot();
        }
        if (slot == null)
        {
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

    static DmSlot LeastRecentlyUsedSlot()
    {
        DmSlot victim = null;
        foreach (DmSlot candidate in Slots.Values)
        {
            if (victim == null || candidate.LastUsed < victim.LastUsed)
                victim = candidate;
        }
        return victim;
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

    static object CreateAuthorizedDm()
    {
        if (DmProgType == null)
            throw new InvalidOperationException("插件尚未初始化");
        object dm = Activator.CreateInstance(DmProgType);
        if (dm == null)
            throw new InvalidOperationException("无法创建 dm.dmsoft");
        try { Invoke(dm, "SetShowErrorMsg", 0); } catch (Exception) { }
        int authCode;
        if (!Authorize(dm, RegCode, ExtraCode, out authCode))
        {
            try { Marshal.FinalReleaseComObject(dm); } catch (Exception) { }
            throw new InvalidOperationException(AuthorizeErrorMessage(authCode));
        }
        Registrations++;
        return dm;
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

    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int LoadTypeLibEx(string szFile, int regkind, out ITypeLib pptlib);

    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int RegisterTypeLibForUser(ITypeLib ptlib, string szFullPath, string szHelpDir);

    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int RegisterTypeLib(ITypeLib ptlib, string szFullPath, string szHelpDir);

    [DllImport("RegDll.dll", CharSet = CharSet.Unicode, EntryPoint = "SetDllPathW")]
    static extern int SetDllPathW(string path, int mode);

    [DllImport("user32.dll")]
    static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

    [StructLayout(LayoutKind.Sequential)]
    struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    static void EnsureTypeLibRegistered(string dmPath)
    {
        // dm.dll 自带类型库，但 DllRegisterServer 往往只写 InprocServer32。
        // 未注册 TypeLib 时，.NET InvokeMember / IDispatch 会报 TYPE_E_LIBNOTREGISTERED，
        // Ver/Reg 看起来像“空版本 + code=0”。
        // ForUser 只写当前令牌的 HKCU；提权后是管理员配置单元，必须再写 HKLM。
        const int regkindNone = 2;
        ITypeLib tlb;
        if (LoadTypeLibEx(dmPath, regkindNone, out tlb) != 0 || tlb == null)
            return;
        try
        {
            RegisterTypeLibForUser(tlb, dmPath, null);
            RegisterTypeLib(tlb, dmPath, null);
        }
        finally
        {
            Marshal.ReleaseComObject(tlb);
        }
    }

    static bool TrySetDllPathW(string pluginDir)
    {
        try
        {
            return SetDllPathW(pluginDir, 0) != 0;
        }
        catch (DllNotFoundException)
        {
            return false;
        }
        catch (EntryPointNotFoundException)
        {
            return false;
        }
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
            UnbindAll();
            if (Map != null)
                Map.Dispose();
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
            TrySetDllPathW(pluginDir);
            string dmPath = Path.Combine(pluginDir, "dm.dll");
            if (!File.Exists(dmPath))
                throw new InvalidOperationException("缺少 dm.dll: " + dmPath);
            EnsureTypeLibRegistered(dmPath);
            Type prog = Type.GetTypeFromProgID("dm.dmsoft");
            if (prog == null)
                throw new InvalidOperationException("找不到 dm.dmsoft");
            object dm = Activator.CreateInstance(prog);
            if (dm == null)
                throw new InvalidOperationException("无法创建 dm.dmsoft");
            DmProgType = prog;
            // 宿主没有窗口：大漠自带的错误弹窗不可见，只会让 RPC 卡到超时，必须关掉。
            try { Invoke(dm, "SetShowErrorMsg", 0); } catch (Exception) { }
            string verNow = "";
            string verErr = "";
            try
            {
                verNow = Convert.ToString(Invoke(dm, "Ver")) ?? "";
            }
            catch (Exception verEx)
            {
                verErr = verEx.GetType().Name + ":" + verEx.Message;
            }
            try
            {
                File.WriteAllText(
                    Path.Combine(pluginDir, "plugin_host_auth.log"),
                    "plugin_dir=" + pluginDir + Environment.NewLine
                    + "prog=" + prog.FullName + Environment.NewLine
                    + "dm_exists=" + (File.Exists(dmPath) ? "1" : "0") + Environment.NewLine
                    + "ver_before=" + verNow + Environment.NewLine
                    + "ver_len=" + verNow.Length + Environment.NewLine
                    + "ver_err=" + verErr + Environment.NewLine);
            }
            catch (Exception)
            {
            }
            int authCode;
            if (!Authorize(dm, RegCode, extraCode, out authCode))
                throw new InvalidOperationException(AuthorizeErrorMessage(authCode));
            Primary = new DmSlot { Dm = dm };
            Primary.Touch();
            Registrations = 1;
            Map = MemoryMappedFile.CreateOrOpen(MapNameFromPipe(PipeName), FrameMapSize);
            Inited = true;
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
            case "client_size":
                result = DoClientSize(SlotFor(hwnd).Dm, hwnd);
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
        DmSlot slot;
        if (hwnd > 0 && Slots.TryGetValue(hwnd, out slot))
        {
            cached = slot.BindOk;
            bound = IsBoundByDm(slot.Dm, hwnd);
            if (!bound && slot.BindOk)
                slot.ClearBind();
        }
        return new Dictionary<string, object>
        {
            { "bound", bound },
            { "cached", cached },
        };
    }

    static bool IsBoundByDm(object dm, int hwnd)
    {
        object raw;
        string error;
        if (!TryInvoke(dm, "IsBind", out raw, out error, hwnd))
            return false;
        return IsSuccessInt(raw);
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
            // 本次 bind 是否为该窗口新建了 dm 对象并 Reg，以及宿主累计注册次数，供调用方记账
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

        byte[] bgr = null;
        byte[] bmpBytes = GetScreenDataBmp(dm, 0, 0, width, height);
        if (bmpBytes != null && bmpBytes.Length > 0)
            bgr = BmpToBgr(bmpBytes, out width, out height);
        if (bgr == null)
        {
            byte[] raw = GetScreenData(dm, 0, 0, width, height, width, height);
            if (raw == null || raw.Length == 0)
                throw new InvalidOperationException("截图为空");
            bgr = BgraToBgr(raw, width, height);
        }
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
            width = 0;
            height = 0;
        }
        return new Dictionary<string, object>
        {
            { "width", width },
            { "height", height },
        };
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
    // ime=true 时优先 SendStringIme（需绑定时带 dx.public.input.ime），游戏类窗口通常只认这条路。
    // 注意 SendStringIme 只有一个参数：目标窗口由该 dm 对象的绑定决定。
    static bool DoSendString(object dm, int hwnd, string text, bool ime)
    {
        if (string.IsNullOrEmpty(text))
            return true;
        if (hwnd <= 0)
            return false;
        if (ime && CallOk(dm, "SendStringIme", text))
            return true;
        if (CallOk(dm, "SendString", hwnd, text))
            return true;
        return CallOk(dm, "SendString2", hwnd, text);
    }

    static string _lastVerText = "";

    static bool Authorize(object dm, string regCode, string extraCode, out int authCode)
    {
        authCode = 0;
        _lastVerText = "";
        // 官方顺序：先 Ver() 确认对象可用，再 Reg(注册码, 附加码)。
        try
        {
            object verObj = Invoke(dm, "Ver");
            _lastVerText = Convert.ToString(verObj) ?? "";
        }
        catch (Exception)
        {
        }
        string verInfo = extraCode ?? "";
        try
        {
            object reg = Invoke(dm, "Reg", regCode, verInfo);
            authCode = ToInt(reg);
            return authCode == 1;
        }
        catch (Exception)
        {
        }
        return false;
    }

    static int ToInt(object value)
    {
        if (value == null || value is string)
            return 0;
        try
        {
            return Convert.ToInt32(value);
        }
        catch (Exception)
        {
            return 0;
        }
    }

    static string AuthorizeErrorMessage(int code)
    {
        string detail;
        switch (code)
        {
            case -2:
                detail = "进程未以管理员方式运行";
                break;
            case -1:
                detail = "无法连接大漠网络（防火墙或断网）";
                break;
            case 2:
                detail = "账户余额不足";
                break;
            case 3:
                detail = "已绑本机但余额不足 50 元";
                break;
            case 4:
                detail = "注册码错误";
                break;
            case 5:
                detail = "机器或 IP 在黑/白名单限制中";
                break;
            case 6:
                detail = "非法使用插件或系统语言非简体中文";
                break;
            case 7:
            case 77:
                detail = "账号/机器码因非法使用被封禁";
                break;
            case 8:
                detail = "附加码不在白名单中";
                break;
            case -8:
                detail = "附加码长度超过 20";
                break;
            case -9:
                detail = "附加码包含非法字符";
                break;
            case 777:
                detail = "同一机器码注册次数超限";
                break;
            case 778:
            case 779:
            case 780:
            case 781:
                detail = "注册失败次数异常，IP/机器被临时限制；请换网络或等一段时间后再试";
                break;
            default:
                detail = "未知原因";
                break;
        }
        string verPart = string.IsNullOrEmpty(_lastVerText) ? "ver=空" : ("ver=" + _lastVerText);
        return "插件授权失败 code=" + code + "（" + detail + "；" + verPart + "）";
    }

    static bool TryGetClientSize(object dm, int hwnd, out int width, out int height)
    {
        width = 0;
        height = 0;
        try
        {
            object[] invokeArgs = { hwnd, 0, 0 };
            ParameterModifier mods = new ParameterModifier(3);
            mods[1] = true;
            mods[2] = true;
            object ret = dm.GetType().InvokeMember(
                "GetClientSize",
                BindingFlags.InvokeMethod,
                null,
                dm,
                invokeArgs,
                new[] { mods },
                null,
                null);
            width = Convert.ToInt32(invokeArgs[1]);
            height = Convert.ToInt32(invokeArgs[2]);
            if (width > 0 && height > 0)
                return true;
            if (TryGetClientSizeWin32(hwnd, out width, out height))
                return true;
            return IsSuccessInt(ret);
        }
        catch (Exception)
        {
            return TryGetClientSizeWin32(hwnd, out width, out height);
        }
    }

    static bool TryGetClientSizeWin32(int hwnd, out int width, out int height)
    {
        width = 0;
        height = 0;
        RECT rect;
        if (hwnd <= 0 || !GetClientRect(new IntPtr(hwnd), out rect))
            return false;
        width = rect.Right - rect.Left;
        height = rect.Bottom - rect.Top;
        return width > 0 && height > 0;
    }

    static byte[] GetScreenDataBmp(object dm, int x1, int y1, int x2, int y2)
    {
        try
        {
            object[] invokeArgs = { x1, y1, x2, y2, null, 0 };
            ParameterModifier mods = new ParameterModifier(6);
            mods[4] = true;
            mods[5] = true;
            object ret = dm.GetType().InvokeMember(
                "GetScreenDataBmp",
                BindingFlags.InvokeMethod,
                null,
                dm,
                invokeArgs,
                new[] { mods },
                null,
                null);
            if (!IsSuccessInt(ret))
                return null;
            return CopyOutBytes(invokeArgs[4], invokeArgs[5]);
        }
        catch (Exception)
        {
            return null;
        }
    }

    static byte[] GetScreenData(object dm, int x1, int y1, int x2, int y2, int width, int height)
    {
        try
        {
            object ret = Invoke(dm, "GetScreenData", x1, y1, x2, y2);
            int nbytes = width * height * 4;
            if (nbytes <= 0)
                return null;
            if (ret is byte[] arr)
                return arr;
            IntPtr ptr = ToIntPtr(ret);
            if (ptr == IntPtr.Zero)
                return null;
            byte[] data = new byte[nbytes];
            Marshal.Copy(ptr, data, 0, nbytes);
            return data;
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

    static byte[] BgraToBgr(byte[] bgra, int width, int height)
    {
        int stride = width * 3;
        int srcStride = width * 4;
        if (bgra.Length < srcStride * height)
            throw new InvalidOperationException("GetScreenData 长度不足");
        byte[] dest = new byte[stride * height];
        for (int y = 0; y < height; y++)
        {
            int srcRow = y * srcStride;
            int dstRow = y * stride;
            for (int x = 0; x < width; x++)
            {
                dest[dstRow + x * 3] = bgra[srcRow + x * 4];
                dest[dstRow + x * 3 + 1] = bgra[srcRow + x * 4 + 1];
                dest[dstRow + x * 3 + 2] = bgra[srcRow + x * 4 + 2];
            }
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
        try
        {
            return Convert.ToInt32(Invoke(dm, "GetLastError"));
        }
        catch (Exception)
        {
            return 0;
        }
    }

    static string MouseMethod(string button, string action)
    {
        string prefix;
        switch ((button ?? "left").Trim().ToLowerInvariant())
        {
            case "right":
                prefix = "Right";
                break;
            case "middle":
                prefix = "Middle";
                break;
            default:
                prefix = "Left";
                break;
        }
        // 双击不走这里：大漠只有 LeftDoubleClick，由 DoMouseDoubleClick 单独处理
        switch (action)
        {
            case "down":
                return prefix + "Down";
            case "up":
                return prefix + "Up";
            default:
                return prefix + "Click";
        }
    }

    static bool IsVersionString(object value)
    {
        string text = value as string;
        if (string.IsNullOrEmpty(text))
            return false;
        return text.IndexOf('.') >= 0 || char.IsDigit(text[0]);
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

    static bool CallFlag(object dm, string name, params object[] invokeArgs)
    {
        return IsSuccessInt(Invoke(dm, name, invokeArgs));
    }

    static object Invoke(object target, string name, params object[] invokeArgs)
    {
        return target.GetType().InvokeMember(
            name,
            BindingFlags.InvokeMethod,
            null,
            target,
            invokeArgs ?? new object[0]);
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
        if (value == null || value is DBNull || value is string && string.IsNullOrWhiteSpace((string)value))
            return fallback;
        try
        {
            return Convert.ToInt32(value);
        }
        catch (Exception)
        {
            return fallback;
        }
    }

    static bool GetBool(Dictionary<string, object> map, string key, bool fallback = false)
    {
        object value = GetValue(map, key);
        if (value == null || value is DBNull)
            return fallback;
        if (value is bool flag)
            return flag;
        string text = Convert.ToString(value);
        if (string.IsNullOrWhiteSpace(text))
            return fallback;
        text = text.Trim().ToLowerInvariant();
        if (text == "true" || text == "1" || text == "yes" || text == "on")
            return true;
        if (text == "false" || text == "0" || text == "no" || text == "off")
            return false;
        return fallback;
    }

    static double GetDouble(Dictionary<string, object> map, string key, double fallback)
    {
        object value = GetValue(map, key);
        if (value == null || value is DBNull || value is string && string.IsNullOrWhiteSpace((string)value))
            return fallback;
        try
        {
            return Convert.ToDouble(value);
        }
        catch (Exception)
        {
            return fallback;
        }
    }

}
