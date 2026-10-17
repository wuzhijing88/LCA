using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace LcaRdpChildHost
{
    internal static class NativeMethods
    {
        public const int GwlStyle = -16;
        public const int WsChild = 0x40000000;
        public const int WsVisible = 0x10000000;
        public const int WsPopup = unchecked((int)0x80000000);
        public const int WsClipSiblings = 0x04000000;
        public const int WsClipChildren = 0x02000000;
        public const int GwlExStyle = -20;
        public const int GwlpHwndParent = -8;
        public const int WsExLayered = 0x00080000;
        public const int WsExTransparent = 0x00000020;
        public const int WsExToolWindow = 0x00000080;
        public const int WsExNoActivate = 0x08000000;
        public const int SwHide = 0;
        public const int SwShow = 5;
        public const int SwShowNoActivate = 4;
        public const uint LwaAlpha = 0x2;
        public const int SwpNoActivate = 0x0010;

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr SetParent(IntPtr child, IntPtr parent);

        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtr", SetLastError = true)]
        public static extern IntPtr SetWindowLongPtr(IntPtr window, int index, IntPtr value);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern int GetWindowLong(IntPtr window, int index);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern int SetWindowLong(IntPtr window, int index, int value);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool MoveWindow(IntPtr window, int x, int y, int width, int height, bool repaint);

        public static readonly IntPtr HwndTop = IntPtr.Zero;
        public static readonly IntPtr HwndTopmost = new IntPtr(-1);
        public const int SwpNoMove = 0x0002;
        public const int SwpNoSize = 0x0001;
        public const int SwpShowWindow = 0x0040;

        public delegate bool EnumWindowsProc(IntPtr window, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetWindowPos(
            IntPtr window,
            IntPtr insertAfter,
            int x,
            int y,
            int width,
            int height,
            int flags);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetWindowText(IntPtr window, StringBuilder text, int maxCount);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetClassName(IntPtr window, StringBuilder text, int maxCount);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWindowVisible(IntPtr window);

        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

        [DllImport("user32.dll")]
        public static extern uint MapVirtualKey(uint code, uint mapType);

        [DllImport("user32.dll")]
        public static extern IntPtr SetFocus(IntPtr window);

        [DllImport("user32.dll")]
        public static extern IntPtr GetFocus();

        [DllImport("user32.dll")]
        public static extern IntPtr GetActiveWindow();

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool AttachThreadInput(
            uint attach,
            uint attachTo,
            [MarshalAs(UnmanagedType.Bool)] bool attachState);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool AllowSetForegroundWindow(uint processId);

        [DllImport("user32.dll")]
        public static extern IntPtr SetActiveWindow(IntPtr window);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool BringWindowToTop(IntPtr window);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetForegroundWindow(IntPtr window);

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern IntPtr CreateWindowEx(
            int exStyle,
            string className,
            string windowName,
            int style,
            int x,
            int y,
            int width,
            int height,
            IntPtr parent,
            IntPtr menu,
            IntPtr instance,
            IntPtr param);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool DestroyWindow(IntPtr window);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool ShowWindow(IntPtr window, int command);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetLayeredWindowAttributes(
            IntPtr window,
            uint colorKey,
            byte alpha,
            uint flags);

        public const uint WmQuit = 0x0012;

        [StructLayout(LayoutKind.Sequential)]
        public struct Msg
        {
            public IntPtr hwnd;
            public uint message;
            public IntPtr wParam;
            public IntPtr lParam;
            public uint time;
            public int x;
            public int y;
        }

        [DllImport("user32.dll")]
        public static extern int GetMessage(out Msg message, IntPtr window, uint min, uint max);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool PeekMessage(
            out Msg message,
            IntPtr window,
            uint min,
            uint max,
            uint remove);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool TranslateMessage(ref Msg message);

        [DllImport("user32.dll")]
        public static extern IntPtr DispatchMessage(ref Msg message);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool PostThreadMessage(
            uint threadId,
            uint message,
            IntPtr wParam,
            IntPtr lParam);

        [DllImport("kernel32.dll")]
        public static extern uint GetCurrentThreadId();

        [DllImport("kernel32.dll")]
        public static extern uint GetCurrentProcessId();

        public const uint ImdtUnavailable = 0;

        [StructLayout(LayoutKind.Sequential)]
        public struct InputMessageSource
        {
            public uint deviceType;
            public uint originId;
        }

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool GetCurrentInputMessageSource(out InputMessageSource source);

        public delegate IntPtr InputHookProc(int code, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)]
        public struct MouseHookData
        {
            public int x;
            public int y;
            public IntPtr hwnd;
            public uint hitTest;
            public UIntPtr extraInfo;
        }

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr SetWindowsHookEx(
            int hookId, InputHookProc callback, IntPtr module, uint threadId);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool UnhookWindowsHookEx(IntPtr hook);

        [DllImport("user32.dll")]
        public static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsChild(IntPtr parent, IntPtr child);

        public const uint GwChild = 5;
        public const uint GwHwndNext = 2;

        [DllImport("user32.dll")]
        public static extern IntPtr GetWindow(IntPtr window, uint command);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWindow(IntPtr window);

        public const uint GaRoot = 2;

        [DllImport("user32.dll")]
        public static extern IntPtr GetAncestor(IntPtr window, uint flags);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool WTSEnableChildSessions(
            [MarshalAs(UnmanagedType.Bool)] bool enable);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool WTSIsChildSessionsEnabled(
            [MarshalAs(UnmanagedType.Bool)] out bool enabled);

    }

    internal sealed class RdpAx : AxHost
    {
        public RdpAx(string clsid)
            : base(clsid)
        {
            Dock = DockStyle.Fill;
        }

        public object RawOcx()
        {
            object unused = Handle;
            object ocx = GetOcx();
            if (ocx == null)
            {
                throw new InvalidOperationException("RDP ActiveX 尚未初始化。");
            }

            return ocx;
        }
    }

    [ComImport]
    [Guid("302D8188-0052-4807-806A-362B628F9AC5")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMsRdpExtendedSettings
    {
        void set_Property(
            [In, MarshalAs(UnmanagedType.BStr)] string propertyName,
            [In, MarshalAs(UnmanagedType.Struct)] ref object value);

        [return: MarshalAs(UnmanagedType.Struct)]
        object get_Property([In, MarshalAs(UnmanagedType.BStr)] string propertyName);
    }

    [ComImport]
    [Guid("336D5562-EFA8-482E-8CB3-C5C0FC7A7DB6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    internal interface IMsTscAxEvents
    {
        [DispId(1)]
        void OnConnecting();

        [DispId(2)]
        void OnConnected();

        [DispId(3)]
        void OnLoginComplete();

        [DispId(4)]
        void OnDisconnected([In] int disconnectReason);

        [DispId(5)]
        void OnEnterFullScreenMode();

        [DispId(6)]
        void OnLeaveFullScreenMode();

        [DispId(7)]
        void OnChannelReceivedData([In] string channelName, [In] string data);

        [DispId(8)]
        void OnRequestGoFullScreen();

        [DispId(9)]
        void OnRequestLeaveFullScreen();

        [DispId(10)]
        void OnFatalError([In] int errorCode);

        [DispId(11)]
        void OnWarning([In] int warningCode);

        [DispId(12)]
        void OnRemoteDesktopSizeChange([In] int width, [In] int height);

        [DispId(13)]
        void OnIdleTimeoutNotification();

        [DispId(14)]
        void OnRequestContainerMinimize();

        [DispId(15)]
        void OnConfirmClose(out bool allowClose);

        [DispId(16)]
        void OnReceivedTSPublicKey([In] string publicKey, out bool continueLogon);

        [DispId(17)]
        void OnAutoReconnecting([In] int disconnectReason, [In] int attemptCount, out int continueStatus);

        [DispId(18)]
        void OnAuthenticationWarningDisplayed();

        [DispId(19)]
        void OnAuthenticationWarningDismissed();

        [DispId(20)]
        void OnRemoteProgramResult([In] string remoteProgram, [In] int error, [In] bool isExecutable);

        [DispId(21)]
        void OnRemoteProgramDisplayed([In] bool displayed, [In] uint displayInformation);

        [DispId(22)]
        void OnLogonError([In] int errorCode);

        [DispId(23)]
        void OnFocusReleased([In] int direction);

        [DispId(24)]
        void OnUserNameAcquired([In] string userName);

        [DispId(28)]
        void OnServiceMessageReceived([In] string serviceMessage);

        [DispId(29)]
        void OnRemoteWindowDisplayed([In] bool displayed, [In] int windowHandle, [In] int windowAttribute);

        [DispId(30)]
        void OnConnectionBarPullDown();

        [DispId(32)]
        void OnNetworkStatusChanged([In] uint qualityLevel, [In] int bandwidth, [In] int roundTripTime);

        [DispId(33)]
        void OnAutoReconnected();

        [DispId(34)]
        void OnAutoReconnecting2([In] int disconnectReason, [In] bool networkAvailable, [In] int attemptCount, [In] int maxAttemptCount);

        [DispId(35)]
        void OnDevicesButtonPressed();
    }

    [ComVisible(true)]
    [ClassInterface(ClassInterfaceType.None)]
    internal sealed class RdpEventSink : IMsTscAxEvents
    {
        private readonly Action<string> _emit;

        public RdpEventSink(Action<string> emit)
        {
            _emit = emit;
        }

        public void OnConnecting()
        {
            _emit("CONNECTING");
        }

        public void OnConnected()
        {
            // 传输层建立时，Child Session 仍可能停在 Winlogon 初始化阶段。
            // 此时把宿主窗口嵌入 Qt 会改变 RDP 控件的窗口层级，部分系统会以
            // 267 断开。等 OnLoginComplete 后再通知 Python 端显示桌面。
        }

        public void OnLoginComplete()
        {
            Program.MarkSessionReady();
            Program.StopPasswordWindowTopmostWatch();
            _emit("LOGIN");
            _emit("CONNECTED");
        }

        public void OnDisconnected(int disconnectReason)
        {
            Program.MarkSessionClosed();
            Program.StopPasswordWindowTopmostWatch();
            _emit(Program.FormatDisconnect(disconnectReason));
            Program.HideOverlay();
        }

        public void OnEnterFullScreenMode()
        {
        }

        public void OnLeaveFullScreenMode()
        {
        }

        public void OnChannelReceivedData(string channelName, string data)
        {
        }

        public void OnRequestGoFullScreen()
        {
        }

        public void OnRequestLeaveFullScreen()
        {
        }

        public void OnFatalError(int errorCode)
        {
            _emit("FATAL " + errorCode.ToString(CultureInfo.InvariantCulture));
        }

        public void OnWarning(int warningCode)
        {
            _emit("WARNING " + warningCode.ToString(CultureInfo.InvariantCulture));
        }

        public void OnRemoteDesktopSizeChange(int width, int height)
        {
            Program.ScheduleRefitSmartSizing();
        }

        public void OnIdleTimeoutNotification()
        {
        }

        public void OnRequestContainerMinimize()
        {
        }

        public void OnConfirmClose(out bool allowClose)
        {
            allowClose = true;
        }

        public void OnReceivedTSPublicKey(string publicKey, out bool continueLogon)
        {
            _emit("PUBLIC_KEY");
            continueLogon = true;
        }

        public void OnAutoReconnecting(int disconnectReason, int attemptCount, out int continueStatus)
        {
            continueStatus = 0;
        }

        public void OnAuthenticationWarningDisplayed()
        {
        }

        public void OnAuthenticationWarningDismissed()
        {
        }

        public void OnRemoteProgramResult(string remoteProgram, int error, bool isExecutable)
        {
        }

        public void OnRemoteProgramDisplayed(bool displayed, uint displayInformation)
        {
        }

        public void OnLogonError(int errorCode)
        {
            _emit("LOGON " + errorCode.ToString(CultureInfo.InvariantCulture));
        }

        public void OnFocusReleased(int direction)
        {
        }

        public void OnUserNameAcquired(string userName)
        {
        }

        public void OnServiceMessageReceived(string serviceMessage)
        {
        }

        public void OnRemoteWindowDisplayed(bool displayed, int windowHandle, int windowAttribute)
        {
        }

        public void OnConnectionBarPullDown()
        {
        }

        public void OnNetworkStatusChanged(uint qualityLevel, int bandwidth, int roundTripTime)
        {
        }

        public void OnAutoReconnected()
        {
        }

        public void OnAutoReconnecting2(int disconnectReason, bool networkAvailable, int attemptCount, int maxAttemptCount)
        {
        }

        public void OnDevicesButtonPressed()
        {
        }
    }

    internal static class Program
    {
        private static StreamWriter _output;
        private static Form _form;
        private static Control _invokeTarget;
        private static RdpAx _rdp;
        private static AxHost.ConnectionPointCookie _cookie;
        private static RdpEventSink _sink;
        private static int _parentHwnd;
        private static int _width = 1920;
        private static int _height = 1080;
        private static int _desktopWidth = 1920;
        private static int _desktopHeight = 1080;
        private static bool _sessionReady;
        private static int _port = 3389;
        private static bool _mute;
        private static System.Windows.Forms.Timer _muteTimer;
        private static bool _shortcuts = true;
        private static bool _smartSizing = true;
        private static bool _credssp = true;
        private static volatile bool _blockPhysicalMouse;
        private static readonly Dictionary<IntPtr, MouseBlockWindow> _mouseBlockWindows =
            new Dictionary<IntPtr, MouseBlockWindow>();
        private static System.Windows.Forms.Timer _mouseBlockTimer;
        private sealed class PhysicalInputHooks
        {
            public IntPtr Mouse;
            public IntPtr Keyboard;
        }
        private static readonly Dictionary<uint, PhysicalInputHooks> _physicalInputHooks =
            new Dictionary<uint, PhysicalInputHooks>();
        private static readonly NativeMethods.InputHookProc _physicalMouseCallback = BlockPhysicalMouse;
        private static readonly NativeMethods.InputHookProc _physicalKeyboardCallback = BlockPhysicalKeyboard;
        private static bool _shuttingDown;
        private static bool _clientDisconnect;
        private static readonly object _outputLock = new object();
        private static volatile bool _watchPasswordWindows;
        private static Thread _passwordWindowThread;
        private static NativeMethods.EnumWindowsProc _enumPasswordWindows;
        private static readonly Dictionary<long, bool> _raisedPasswordWindows = new Dictionary<long, bool>();
        private static string _clsid = "A0C63C30-F08D-4AB4-907C-34905D770C7D";
        private static bool _autoConnect;
        private static bool _qtEmbedded;
        private static bool _refitting;
        private static System.Windows.Forms.Timer _refitTimer;
        private static bool _desktopUpdateRetried;
        private static bool _smartSizingBeforeDesktopUpdate = true;
        private static int _appliedDesktopWidth;
        private static int _appliedDesktopHeight;
        private static System.Windows.Forms.Timer _desktopRetryTimer;

        [STAThread]
        private static void Main(string[] args)
        {
            ParseArgs(args);

            _output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false))
            {
                AutoFlush = true
            };
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            var standalone = _parentHwnd == 0;
            _form = new Form
            {
                FormBorderStyle = standalone ? FormBorderStyle.Sizable : FormBorderStyle.None,
                ShowInTaskbar = standalone,
                StartPosition = standalone ? FormStartPosition.CenterScreen : FormStartPosition.Manual,
                Location = standalone ? new Point(200, 120) : new Point(-32000, -32000),
                ClientSize = new Size(_width, _height),
                Text = "LCA 桌面分身",
                TopMost = standalone
            };
            _rdp = new RdpAx("{" + _clsid + "}");
            _rdp.Dock = DockStyle.Fill;
            _form.Controls.Add(_rdp);
            _form.Resize += OnFormResize;
            _form.Shown += OnShown;
            _form.FormClosing += OnFormClosing;
            _form.VisibleChanged += OnFormVisibilityChanged;
            Application.Run(_form);
        }

        private static void OnFormResize(object sender, EventArgs e)
        {
            if (_refitting || _rdp == null || _form == null || _form.IsDisposed)
            {
                return;
            }

            _rdp.Bounds = _form.ClientRectangle;
        }

        private static void OnShown(object sender, EventArgs e)
        {
            try
            {
                object unusedHandle = _rdp.Handle;
                object ocx = _rdp.RawOcx();
                _sink = new RdpEventSink(Emit);
                _cookie = new AxHost.ConnectionPointCookie(ocx, _sink, typeof(IMsTscAxEvents));
                _invokeTarget = new Control();
                _invokeTarget.CreateControl();
                ClearLayeredStyle();
                Emit("HWND " + unchecked((ulong)_form.Handle.ToInt64()).ToString(CultureInfo.InvariantCulture));
                Emit("HOST_READY");
                ApplyMouseBlock();
                Emit("PROPERTY Clsid=" + _clsid);
                var stdinThread = new Thread(ReadCommands)
                {
                    IsBackground = true
                };
                stdinThread.Start();
                if (_autoConnect)
                {
                    Connect();
                }
            }
            catch (Exception exception)
            {
                Emit("ERROR " + exception.Message);
                Application.Exit();
            }
        }

        internal static void MarkSessionReady()
        {
            _sessionReady = true;

            if (_desktopWidth != _appliedDesktopWidth || _desktopHeight != _appliedDesktopHeight)
            {
                StopDesktopRetryTimer();
                _desktopUpdateRetried = false;
                ApplyDesktopSize();
            }
        }

        private static void TrustLocalhostCertificate()
        {
            try
            {
                using (var tcp = Registry.LocalMachine.OpenSubKey(
                    @"SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp",
                    false))
                {
                    if (tcp == null)
                    {
                        return;
                    }

                    byte[] hash = tcp.GetValue("SSLCertificateSHA1Hash") as byte[];
                    if (hash == null || hash.Length == 0)
                    {
                        return;
                    }

                    using (var server = Registry.CurrentUser.CreateSubKey(
                        @"Software\Microsoft\Terminal Server Client\Servers\localhost"))
                    {
                        if (server == null)
                        {
                            return;
                        }

                        server.SetValue("CertHash", hash, RegistryValueKind.Binary);
                    }
                }

                Emit("PROPERTY CertHash=localhost");
            }
            catch (Exception exception)
            {
                Emit("PROPERTY CertHash失败 " + exception.Message);
            }
        }

        internal static void MarkSessionClosed()
        {
            _sessionReady = false;
        }

        private static void ApplySmartSizing(bool enabled)
        {
            _smartSizing = enabled;
            if (!enabled)
            {
                StopRefitTimer();
            }

            try
            {
                if (enabled)
                {
                    RefitSmartSizing();
                }
                else
                {
                    object advanced = GetProp(_rdp.RawOcx(), "AdvancedSettings7");
                    SetProp(advanced, "SmartSizing", false);
                }

                Emit("SMART_SIZING_OK " + (enabled ? "1" : "0"));
            }
            catch (Exception exception)
            {
                Emit(
                    "SMART_SIZING_FAILED "
                    + FormatException(exception).Replace('\r', ' ').Replace('\n', ' '));
            }
        }

        private static void SendWinChord(int secondVk)
        {
            if (!_sessionReady || _rdp == null)
            {
                Emit("KEYS_FAILED 桌面尚未就绪");
                return;
            }

            // 控件要的是低位扫描码，扩展键用 0x100。按 WM_KEYDOWN 的 lParam 去组会返回 E_FAIL。
            int secondScan = secondVk == 0x09 ? 0x0F : 0x20;
            int winData = 0x5B | 0x0100;
            int secondData = secondScan;
            short[] keyUp = new short[] { 0, 0, -1, -1 };
            int[] keyData = new int[] { winData, secondData, secondData, winData };
            FocusInputCaptureWindow();
            SendKeyArray(keyUp, keyData);
        }

        private static void FocusInputCaptureWindow()
        {
            if (_form == null || _form.IsDisposed || !_form.IsHandleCreated)
            {
                return;
            }

            // 覆盖层点击后必须把宿主和 RDP 的输入捕获窗口重新设为活动窗口。
            // 只 SetFocus(Input Capture Window) 在宿主失焦时会静默失败。
            IntPtr root = NativeMethods.GetAncestor(_form.Handle, NativeMethods.GaRoot);
            if (root == IntPtr.Zero)
            {
                root = _form.Handle;
            }

            IntPtr input = FindInputCaptureWindow(_form.Handle, 0);
            uint currentThread = NativeMethods.GetCurrentThreadId();
            uint foregroundThread = 0;
            IntPtr foreground = NativeMethods.GetForegroundWindow();
            if (foreground != IntPtr.Zero)
            {
                foregroundThread = NativeMethods.GetWindowThreadProcessId(foreground, out _);
            }
            uint inputThread = 0;
            if (input != IntPtr.Zero)
            {
                inputThread = NativeMethods.GetWindowThreadProcessId(input, out _);
            }

            // SetFocus 只能作用于当前输入队列。点击 LCA 菜单或短暂切换前台窗口后，
            // 宿主线程与前台线程通常已经分离；此时
            // SetForegroundWindow/SetFocus 会静默失败，后续输入消息虽然成功，
            // 但输入消息不会再进入 RDP 的 Input Capture Window。临时合并输入队列，
            // 在同一输入队列内恢复前台和焦点，再立即解除合并，避免永久改变线程状态。
            bool foregroundAttached = false;
            bool inputAttached = false;
            if (foregroundThread != 0 && foregroundThread != currentThread)
            {
                foregroundAttached = NativeMethods.AttachThreadInput(
                    currentThread,
                    foregroundThread,
                    true);
            }
            if (inputThread != 0
                && inputThread != currentThread
                && inputThread != foregroundThread)
            {
                inputAttached = NativeMethods.AttachThreadInput(
                    currentThread,
                    inputThread,
                    true);
            }

            IntPtr focused = IntPtr.Zero;
            bool foregroundAllowed = false;
            bool foregroundSet = false;
            try
            {
                foregroundAllowed = NativeMethods.AllowSetForegroundWindow(0xFFFFFFFF);
                NativeMethods.BringWindowToTop(root);
                foregroundSet = NativeMethods.SetForegroundWindow(root);
                NativeMethods.SetActiveWindow(root);
                if (_rdp != null && !_rdp.IsDisposed && _rdp.IsHandleCreated)
                {
                    _rdp.Focus();
                }

                if (input != IntPtr.Zero)
                {
                    NativeMethods.BringWindowToTop(input);
                    NativeMethods.SetFocus(input);
                    focused = NativeMethods.GetFocus();
                }
            }
            finally
            {
                if (inputAttached)
                {
                    NativeMethods.AttachThreadInput(currentThread, inputThread, false);
                }
                if (foregroundAttached)
                {
                    NativeMethods.AttachThreadInput(currentThread, foregroundThread, false);
                }
            }

            Emit(
                "PROPERTY 输入焦点 root="
                + root.ToInt64().ToString(CultureInfo.InvariantCulture)
                + " foreground="
                + (foregroundSet ? "1" : "0")
                + " allowed="
                + (foregroundAllowed ? "1" : "0")
                + " attached="
                + ((foregroundAttached || inputAttached) ? "1" : "0")
                + " foregroundThread="
                + foregroundThread.ToString(CultureInfo.InvariantCulture)
                + " inputThread="
                + inputThread.ToString(CultureInfo.InvariantCulture)
                + " capture="
                + input.ToInt64().ToString(CultureInfo.InvariantCulture)
                + " focused="
                + focused.ToInt64().ToString(CultureInfo.InvariantCulture));
        }

        private static IntPtr FindInputCaptureWindow(IntPtr root, int depth)
        {
            if (root == IntPtr.Zero || depth > 32 || !NativeMethods.IsWindow(root))
            {
                return IntPtr.Zero;
            }

            var text = new StringBuilder(256);
            NativeMethods.GetWindowText(root, text, text.Capacity);
            if (string.Equals(text.ToString(), "Input Capture Window", StringComparison.Ordinal))
            {
                return root;
            }

            IntPtr child = NativeMethods.GetWindow(root, NativeMethods.GwChild);
            int guard = 0;
            while (child != IntPtr.Zero && guard < 256)
            {
                IntPtr found = FindInputCaptureWindow(child, depth + 1);
                if (found != IntPtr.Zero)
                {
                    return found;
                }

                child = NativeMethods.GetWindow(child, NativeMethods.GwHwndNext);
                guard++;
            }

            return IntPtr.Zero;
        }

        private static void SendKeyArray(short[] keyUp, int[] keyData)
        {
            object ocx = _rdp.RawOcx();
            IntPtr unknown = Marshal.GetIUnknownForObject(ocx);
            IntPtr iface = IntPtr.Zero;
            GCHandle upHandle = GCHandle.Alloc(keyUp, GCHandleType.Pinned);
            GCHandle dataHandle = GCHandle.Alloc(keyData, GCHandleType.Pinned);
            try
            {
                Guid iid = new Guid("2F079C4C-87B2-4AFD-97AB-20CDB43038AE");
                int query = Marshal.QueryInterface(unknown, ref iid, out iface);
                if (query < 0 || iface == IntPtr.Zero)
                {
                    Marshal.ThrowExceptionForHR(query);
                }

                IntPtr vtable = Marshal.ReadIntPtr(iface);
                IntPtr method = Marshal.ReadIntPtr(vtable, 14 * IntPtr.Size);
                SendKeysDelegate call = (SendKeysDelegate)Marshal.GetDelegateForFunctionPointer(
                    method,
                    typeof(SendKeysDelegate));
                int result = call(
                    iface,
                    keyUp.Length,
                    upHandle.AddrOfPinnedObject(),
                    dataHandle.AddrOfPinnedObject());
                if (result < 0)
                {
                    Marshal.ThrowExceptionForHR(result);
                }

                Emit("KEYS_OK");
            }
            catch (Exception exception)
            {
                Emit(
                    "KEYS_FAILED "
                    + FormatException(exception).Replace('\r', ' ').Replace('\n', ' '));
            }
            finally
            {
                if (upHandle.IsAllocated)
                {
                    upHandle.Free();
                }

                if (dataHandle.IsAllocated)
                {
                    dataHandle.Free();
                }

                if (iface != IntPtr.Zero)
                {
                    Marshal.Release(iface);
                }

                Marshal.Release(unknown);
            }
        }

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int SendKeysDelegate(IntPtr self, int numKeys, IntPtr keyUp, IntPtr keyData);

        private static void ApplyDesktopSize()
        {
            if (!_desktopUpdateRetried)
            {
                _smartSizingBeforeDesktopUpdate = _smartSizing;
            }

            try
            {
                // 已连接时不能写 DesktopWidth/DesktopHeight，那两个属性只在 Connect 前生效。
                // 写进去会让 UpdateSessionDisplaySettings 返回 E_FAIL，随后重连就会再要一次密码。
                object ocx = _rdp.RawOcx();
                object advanced = GetProp(ocx, "AdvancedSettings7");
                SetProp(advanced, "SmartSizing", false);
                ocx.GetType().InvokeMember(
                    "UpdateSessionDisplaySettings",
                    BindingFlags.InvokeMethod,
                    null,
                    ocx,
                    new object[]
                    {
                        (uint)_desktopWidth,
                        (uint)_desktopHeight,
                        (uint)_desktopWidth,
                        (uint)_desktopHeight,
                        (uint)0,
                        (uint)100,
                        (uint)100
                    },
                    CultureInfo.InvariantCulture);
                _desktopUpdateRetried = false;
                StopDesktopRetryTimer();
                _appliedDesktopWidth = _desktopWidth;
                _appliedDesktopHeight = _desktopHeight;
                _smartSizing = true;
                if (_rdp != null && _form != null && !_form.IsDisposed)
                {
                    _rdp.Dock = DockStyle.Fill;
                }
                Emit(
                    "DESKTOP_OK "
                    + _desktopWidth.ToString(CultureInfo.InvariantCulture)
                    + " "
                    + _desktopHeight.ToString(CultureInfo.InvariantCulture)
                    + " SMART_SIZING=1");
                // 新分辨率要等 OnRemoteDesktopSizeChange 才落到控件上。
                // SmartSizing 只在控件尺寸变化时重算，所以这里再排一次铺满。
                ScheduleRefitSmartSizing();
            }
            catch (Exception exception)
            {
                int hr = HResultOf(exception);
                bool retryable = hr == unchecked((int)0x80004005) || hr == unchecked((int)0x8000FFFF);
                if (retryable && !_desktopUpdateRetried)
                {
                    ScheduleDesktopRetry();
                    return;
                }

                _desktopUpdateRetried = false;
                StopDesktopRetryTimer();
                RestoreSmartSizing(_smartSizingBeforeDesktopUpdate);
                Emit("DESKTOP_FAILED " + FormatException(exception).Replace('\r', ' ').Replace('\n', ' '));
            }
        }

        private static int HResultOf(Exception exception)
        {
            COMException com = exception as COMException;
            if (com != null)
            {
                return com.ErrorCode;
            }

            if (exception.InnerException != null)
            {
                return HResultOf(exception.InnerException);
            }

            return 0;
        }

        private static void RestoreSmartSizing(bool enabled)
        {
            _smartSizing = enabled;
            try
            {
                if (_rdp == null)
                {
                    return;
                }

                object advanced = GetProp(_rdp.RawOcx(), "AdvancedSettings7");
                SetProp(advanced, "SmartSizing", enabled);
            }
            catch (Exception)
            {
            }
        }

        private static void ScheduleDesktopRetry()
        {
            if (_shuttingDown || _form == null || _form.IsDisposed || !_form.IsHandleCreated)
            {
                _desktopUpdateRetried = false;
                RestoreSmartSizing(_smartSizingBeforeDesktopUpdate);
                Emit("DESKTOP_FAILED 桌面分身窗口已经关闭");
                return;
            }

            if (_desktopRetryTimer == null)
            {
                _desktopRetryTimer = new System.Windows.Forms.Timer();
                _desktopRetryTimer.Tick += OnDesktopRetryTick;
            }

            _desktopRetryTimer.Interval = 400;
            _desktopRetryTimer.Stop();
            _desktopRetryTimer.Start();
        }

        private static void OnDesktopRetryTick(object sender, EventArgs e)
        {
            if (_desktopRetryTimer != null)
            {
                _desktopRetryTimer.Stop();
            }

            _desktopUpdateRetried = true;
            ApplyDesktopSize();
        }

        private static void StopDesktopRetryTimer()
        {
            if (_desktopRetryTimer == null)
            {
                return;
            }

            _desktopRetryTimer.Stop();
            _desktopRetryTimer.Tick -= OnDesktopRetryTick;
            _desktopRetryTimer.Dispose();
            _desktopRetryTimer = null;
        }

        internal static void ScheduleRefitSmartSizing()
        {
            // 登录完成前远程桌面会先报一次尺寸。这时去改控件大小会拆掉图形通道，随后以 267 断开。
            if (!_sessionReady || _shuttingDown || _form == null || _form.IsDisposed || !_form.IsHandleCreated)
            {
                return;
            }

            if (_refitTimer == null)
            {
                _refitTimer = new System.Windows.Forms.Timer();
                _refitTimer.Tick += OnRefitTimerTick;
            }

            _refitTimer.Interval = 150;
            _refitTimer.Stop();
            _refitTimer.Start();
        }

        private static void OnRefitTimerTick(object sender, EventArgs e)
        {
            if (_refitTimer != null)
            {
                _refitTimer.Stop();
            }

            try
            {
                RefitSmartSizing();
            }
            catch (Exception exception)
            {
                Emit(
                    "SMART_SIZING_FAILED "
                    + FormatException(exception).Replace('\r', ' ').Replace('\n', ' '));
            }
        }

        private static void StopRefitTimer()
        {
            if (_refitTimer == null)
            {
                return;
            }

            _refitTimer.Stop();
            _refitTimer.Tick -= OnRefitTimerTick;
            _refitTimer.Dispose();
            _refitTimer = null;
        }

        private static void RefitSmartSizing()
        {
            if (_refitting || _shuttingDown || _rdp == null || _form == null || _form.IsDisposed)
            {
                return;
            }

            _refitting = true;
            try
            {
                object advanced = GetProp(_rdp.RawOcx(), "AdvancedSettings7");
                if (!_smartSizing)
                {
                    _rdp.Dock = DockStyle.Fill;
                    SetProp(advanced, "SmartSizing", false);
                    return;
                }

                int width = _form.ClientSize.Width;
                int height = _form.ClientSize.Height;
                if (width < 2 || height < 2)
                {
                    _rdp.Dock = DockStyle.Fill;
                    SetProp(advanced, "SmartSizing", true);
                    return;
                }

                _rdp.Dock = DockStyle.None;
                SetProp(advanced, "SmartSizing", false);
                _rdp.Bounds = new Rectangle(0, 0, width - 1, height - 1);
                SetProp(advanced, "SmartSizing", true);
                _rdp.Bounds = new Rectangle(0, 0, width, height);
                _rdp.Dock = DockStyle.Fill;
            }
            finally
            {
                _refitting = false;
            }
        }

        private static void PrepareWindowForConnect()
        {
            if (_form == null || _form.IsDisposed)
            {
                return;
            }

            ClearLayeredStyle();
            if (_form.Left < -16000 || _form.Top < -16000)
            {
                var area = Screen.PrimaryScreen.WorkingArea;
                int width = Math.Max(800, Math.Min(_form.Width, area.Width));
                int height = Math.Max(600, Math.Min(_form.Height, area.Height));
                int x = area.Left + Math.Max(0, (area.Width - width) / 2);
                int y = area.Top + Math.Max(0, (area.Height - height) / 2);
                _form.Bounds = new Rectangle(x, y, width, height);
            }

            if (_rdp != null)
            {
                _rdp.Bounds = _form.ClientRectangle;
            }

            _form.Show();
            Emit(
                "PROPERTY HostWindow="
                + _form.Left.ToString(CultureInfo.InvariantCulture)
                + ","
                + _form.Top.ToString(CultureInfo.InvariantCulture)
                + " "
                + _form.ClientSize.Width.ToString(CultureInfo.InvariantCulture)
                + "x"
                + _form.ClientSize.Height.ToString(CultureInfo.InvariantCulture));
        }

        private static void ClearLayeredStyle()
        {
            int exStyle = NativeMethods.GetWindowLong(_form.Handle, NativeMethods.GwlExStyle);
            if ((exStyle & NativeMethods.WsExLayered) != 0)
            {
                NativeMethods.SetWindowLong(
                    _form.Handle,
                    NativeMethods.GwlExStyle,
                    exStyle & ~NativeMethods.WsExLayered);
            }
        }

        private static void ReadCommands()
        {
            using (var input = new StreamReader(Console.OpenStandardInput(), Encoding.UTF8))
            {
            string line;
            while ((line = input.ReadLine()) != null)
            {
                var command = line.Trim();
                if (command.Length == 0)
                {
                    continue;
                }

                try
                {
                    _invokeTarget.BeginInvoke(new Action(() => HandleCommand(command)));
                }
                catch (Exception exception)
                {
                    Emit("ERROR " + exception.Message);
                }
            }
            }

            RequestExit();
            Thread.Sleep(2000);
            Environment.Exit(0);
        }

        private static void HandleCommand(string command)
        {
            try
            {
                if (command == "CONNECT")
                {
                    Connect();
                    return;
                }

                if (command == "DISCONNECT")
                {
                    DisconnectClient();
                    return;
                }

                if (command == "HIDE")
                {
                    HideOverlay();
                    return;
                }

                if (command == "SHOW")
                {
                    if (_form != null && !_form.IsDisposed)
                    {
                        _form.Show();
                                }
                    return;
                }

                if (command == "EMBEDDED")
                {
                    _qtEmbedded = true;
                    return;
                }

                if (command == "FOCUS_INPUT")
                {
                    FocusInputCaptureWindow();
                    return;
                }

                if (command.StartsWith("DESKTOP ", StringComparison.Ordinal))
                {
                    var parts = command.Split(' ');
                    _desktopWidth = int.Parse(parts[1], CultureInfo.InvariantCulture);
                    _desktopHeight = int.Parse(parts[2], CultureInfo.InvariantCulture);
                    if (_sessionReady)
                    {
                        StopDesktopRetryTimer();
                        _desktopUpdateRetried = false;
                        ApplyDesktopSize();
                    }
                    return;
                }

                if (command.StartsWith("PLACE ", StringComparison.Ordinal))
                {
                    if (_qtEmbedded)
                    {
                        return;
                    }

                    var parts = command.Split(' ');
                    var x = int.Parse(parts[1], CultureInfo.InvariantCulture);
                    var y = int.Parse(parts[2], CultureInfo.InvariantCulture);
                    _width = int.Parse(parts[3], CultureInfo.InvariantCulture);
                    _height = int.Parse(parts[4], CultureInfo.InvariantCulture);
                    NativeMethods.MoveWindow(_form.Handle, x, y, _width, _height, true);
                    NativeMethods.SetWindowPos(
                        _form.Handle,
                        NativeMethods.HwndTop,
                        0,
                        0,
                        0,
                        0,
                        NativeMethods.SwpNoMove | NativeMethods.SwpNoSize | NativeMethods.SwpShowWindow);
                    return;
                }

                if (command.StartsWith("RESIZE ", StringComparison.Ordinal))
                {
                    if (_qtEmbedded)
                    {
                        return;
                    }

                    var parts = command.Split(' ');
                    _width = int.Parse(parts[1], CultureInfo.InvariantCulture);
                    _height = int.Parse(parts[2], CultureInfo.InvariantCulture);
                    NativeMethods.MoveWindow(_form.Handle, _form.Left, _form.Top, _width, _height, true);
                    return;
                }

                if (command.StartsWith("SMART_SIZING ", StringComparison.Ordinal))
                {
                    ApplySmartSizing(command.Substring("SMART_SIZING ".Length) == "1");
                    return;
                }

                if (command.StartsWith("MOUSE_BLOCK ", StringComparison.Ordinal))
                {
                    _blockPhysicalMouse = command.Substring("MOUSE_BLOCK ".Length) == "1";
                    ApplyMouseBlock();
                    Emit("MOUSE_BLOCK_OK " + (_blockPhysicalMouse ? "1" : "0"));
                    return;
                }

                if (command.StartsWith("MUTE ", StringComparison.Ordinal))
                {
                    _mute = command.Substring("MUTE ".Length) == "1";
                    ApplyMuteState(true);
                    return;
                }

                if (command == "KEYS WIN_D")
                {
                    SendWinChord(0x44);
                    return;
                }

                if (command == "KEYS WIN_TAB")
                {
                    SendWinChord(0x09);
                    return;
                }

                if (command == "QUIT")
                {
                    Shutdown();
                }
            }
            catch (Exception exception)
            {
                HideOverlay();
                Emit("ERROR " + FormatException(exception));
            }
        }

        private static void ApplyMuteState(bool report)
        {
            try
            {
                MuteProcessAudio(_mute);
            }
            catch (Exception exception)
            {
                if (report)
                {
                    Emit(
                        "MUTE_FAILED "
                        + FormatException(exception).Replace('\r', ' ').Replace('\n', ' '));
                }

                return;
            }

            if (_mute)
            {
                EnsureMuteTimer();
            }
            else
            {
                StopMuteTimer();
            }

            if (report)
            {
                Emit("MUTE_OK " + (_mute ? "1" : "0"));
            }
        }

        private static void EnsureMuteTimer()
        {
            if (_shuttingDown)
            {
                return;
            }

            if (_muteTimer == null)
            {
                _muteTimer = new System.Windows.Forms.Timer();
                _muteTimer.Interval = 500;
                _muteTimer.Tick += OnMuteTimerTick;
            }

            if (!_muteTimer.Enabled)
            {
                _muteTimer.Start();
            }
        }

        private static void OnMuteTimerTick(object sender, EventArgs e)
        {
            if (!_mute || _shuttingDown)
            {
                StopMuteTimer();
                return;
            }

            try
            {
                MuteProcessAudio(true);
            }
            catch (Exception)
            {
            }
        }

        private static void StopMuteTimer()
        {
            if (_muteTimer == null)
            {
                return;
            }

            _muteTimer.Stop();
            _muteTimer.Tick -= OnMuteTimerTick;
            _muteTimer.Dispose();
            _muteTimer = null;
        }

        private static void MuteProcessAudio(bool mute)
        {
            IMMDeviceEnumerator enumerator = null;
            IMMDevice device = null;
            object managerObject = null;
            IAudioSessionManager2 manager = null;
            IAudioSessionEnumerator sessions = null;
            try
            {
                enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                int hr = enumerator.GetDefaultAudioEndpoint(0, 1, out device);
                if (hr < 0 || device == null)
                {
                    hr = enumerator.GetDefaultAudioEndpoint(0, 0, out device);
                }

                if (hr < 0 || device == null)
                {
                    Marshal.ThrowExceptionForHR(hr);
                }

                Guid managerId = new Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F");
                hr = device.Activate(ref managerId, 23, IntPtr.Zero, out managerObject);
                if (hr < 0 || managerObject == null)
                {
                    Marshal.ThrowExceptionForHR(hr);
                }

                manager = (IAudioSessionManager2)managerObject;
                Guid empty = Guid.Empty;
                ISimpleAudioVolume processVolume;
                hr = manager.GetSimpleAudioVolume(ref empty, 0, out processVolume);
                if (hr >= 0 && processVolume != null)
                {
                    try
                    {
                        processVolume.SetMute(mute, ref empty);
                    }
                    finally
                    {
                        Marshal.ReleaseComObject(processVolume);
                    }
                }

                hr = manager.GetSessionEnumerator(out sessions);
                if (hr < 0 || sessions == null)
                {
                    return;
                }

                int count;
                if (sessions.GetCount(out count) < 0 || count <= 0)
                {
                    return;
                }

                int processId = Process.GetCurrentProcess().Id;
                Guid volumeId = new Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8");
                for (int index = 0; index < count; index++)
                {
                    IAudioSessionControl2 session;
                    if (sessions.GetSession(index, out session) < 0 || session == null)
                    {
                        continue;
                    }

                    try
                    {
                        int sessionProcessId;
                        if (session.GetProcessId(out sessionProcessId) < 0 || sessionProcessId != processId)
                        {
                            continue;
                        }

                        IntPtr unknown = Marshal.GetIUnknownForObject(session);
                        IntPtr volumePointer;
                        int query = Marshal.QueryInterface(unknown, ref volumeId, out volumePointer);
                        Marshal.Release(unknown);
                        if (query < 0 || volumePointer == IntPtr.Zero)
                        {
                            continue;
                        }

                        try
                        {
                            ISimpleAudioVolume volume =
                                (ISimpleAudioVolume)Marshal.GetObjectForIUnknown(volumePointer);
                            try
                            {
                                volume.SetMute(mute, ref empty);
                            }
                            finally
                            {
                                Marshal.ReleaseComObject(volume);
                            }
                        }
                        finally
                        {
                            Marshal.Release(volumePointer);
                        }
                    }
                    finally
                    {
                        Marshal.ReleaseComObject(session);
                    }
                }
            }
            finally
            {
                if (sessions != null)
                {
                    Marshal.ReleaseComObject(sessions);
                }

                if (manager != null)
                {
                    Marshal.ReleaseComObject(manager);
                }
                else if (managerObject != null)
                {
                    Marshal.ReleaseComObject(managerObject);
                }

                if (device != null)
                {
                    Marshal.ReleaseComObject(device);
                }

                if (enumerator != null)
                {
                    Marshal.ReleaseComObject(enumerator);
                }
            }
        }

        private static void Connect()
        {
            PrepareWindowForConnect();
            if (!NativeMethods.WTSEnableChildSessions(true))
            {
                throw new InvalidOperationException(
                    "无法在 RDP 宿主进程中启用 Child Session（Win32 错误 "
                    + Marshal.GetLastWin32Error().ToString(CultureInfo.InvariantCulture)
                    + "）。");
            }

            bool childEnabled;
            if (!NativeMethods.WTSIsChildSessionsEnabled(out childEnabled) || !childEnabled)
            {
                throw new InvalidOperationException("RDP 宿主进程中 Child Session 仍未启用。");
            }

            Emit("PROPERTY HostChildSessionsEnabled=" + childEnabled.ToString());
            object ocx = _rdp.RawOcx();

            SetProp(ocx, "Server", "localhost");
            SetProp(ocx, "DesktopWidth", _desktopWidth);
            SetProp(ocx, "DesktopHeight", _desktopHeight);
            _appliedDesktopWidth = _desktopWidth;
            _appliedDesktopHeight = _desktopHeight;
            SetProp(ocx, "ColorDepth", 32);
            SetProp(ocx, "ConnectingText", "正在创建 LCA 桌面分身...");
            SetProp(ocx, "DisconnectedText", "LCA 桌面分身已断开");

            object secured = GetProp(ocx, "SecuredSettings2");
            SetProp(secured, "KeyboardHookMode", _shortcuts ? 1 : 0);
            // 静音只关本机播放。改 AudioRedirectionMode 必须先断开，子会话会被注销并再次要密码。
            SetProp(secured, "AudioRedirectionMode", 0);

            object advanced = GetProp(ocx, "AdvancedSettings7");
            SetProp(advanced, "RDPPort", _port);
            SetProp(advanced, "AuthenticationLevel", 0);
            SetProp(advanced, "EnableCredSspSupport", _credssp);
            SetProp(advanced, "EnableWindowsKey", 1);
            SetProp(advanced, "SmartSizing", _smartSizing);
            SetProp(ocx, "UserName", Environment.UserName);
            // 子会话自动登录没有带上当前账户密码时，Winlogon 会立刻返回 1326。
            // 这些槽位是 mstscax 单继承虚表，从 IUnknown 起算。
            PutInterfaceBool(ocx, "B3378D90-0728-45C7-8ED7-B6159FB92219", 17, false);
            PutInterfaceBool(ocx, "B3378D90-0728-45C7-8ED7-B6159FB92219", 19, true);
            PutInterfaceBool(ocx, "F50FA8AA-1C7D-4F59-B15C-A90CACAE1FCB", 47, true);
            PutInterfaceBool(ocx, "4F6996D5-D7B1-412C-B0FF-063718566907", 63, true);
            Emit("PROPERTY PromptForCredentials=是 用户=" + Environment.UserName);

            var extended = (IMsRdpExtendedSettings)ocx;
            try
            {
                object enableZoom = true;
                extended.set_Property("EnableZoom", ref enableZoom);
            }
            catch (COMException)
            {
            }


            object connectToChildSession = true;
            extended.set_Property("ConnectToChildSession", ref connectToChildSession);
            object actual = extended.get_Property("ConnectToChildSession");
            Emit("PROPERTY ConnectToChildSession=" + (actual == null ? "null" : actual.ToString()));
            if (!IsTrue(actual))
            {
                throw new InvalidOperationException("ConnectToChildSession 写入后未生效。");
            }

            Emit(
                "CONNECT localhost:"
                + _port.ToString(CultureInfo.InvariantCulture)
                + " credssp="
                + (_credssp ? "1" : "0"));
            TrustLocalhostCertificate();
            ApplyMuteState(true);

            StartPasswordWindowTopmostWatch();
            try
            {
                InvokeOcx("Connect");
            }
            catch (COMException com)
            {
                StopPasswordWindowTopmostWatch();
                if (com.ErrorCode == unchecked((int)0x800704C7))
                {
                    throw new InvalidOperationException("已取消输入 Windows 账户密码。");
                }

                throw;
            }
            catch (Exception)
            {
                StopPasswordWindowTopmostWatch();
                throw;
            }
        }

        internal static void StartPasswordWindowTopmostWatch()
        {
            lock (_raisedPasswordWindows)
            {
                _raisedPasswordWindows.Clear();
            }
            _watchPasswordWindows = true;
            if (_passwordWindowThread != null && _passwordWindowThread.IsAlive)
            {
                return;
            }
            _passwordWindowThread = new Thread(PasswordWindowTopmostLoop);
            _passwordWindowThread.IsBackground = true;
            _passwordWindowThread.Start();
        }

        internal static void StopPasswordWindowTopmostWatch()
        {
            _watchPasswordWindows = false;
        }

        private static void PasswordWindowTopmostLoop()
        {
            while (!_shuttingDown)
            {
                if (_watchPasswordWindows)
                {
                    try
                    {
                        RaisePasswordWindows();
                    }
                    catch (Exception)
                    {
                    }
                }
                Thread.Sleep(200);
            }
        }

        private static void RaisePasswordWindows()
        {
            if (_enumPasswordWindows == null)
            {
                _enumPasswordWindows = RaisePasswordWindowIfNeeded;
            }
            NativeMethods.EnumWindows(_enumPasswordWindows, IntPtr.Zero);
        }

        private static bool RaisePasswordWindowIfNeeded(IntPtr window, IntPtr lParam)
        {
            if (!IsPasswordWindow(window))
            {
                return true;
            }

            long key = window.ToInt64();
            lock (_raisedPasswordWindows)
            {
                if (_raisedPasswordWindows.ContainsKey(key))
                {
                    return true;
                }

                _raisedPasswordWindows[key] = true;
            }

            NativeMethods.SetWindowPos(
                window,
                NativeMethods.HwndTopmost,
                0,
                0,
                0,
                0,
                NativeMethods.SwpNoMove | NativeMethods.SwpNoSize | NativeMethods.SwpShowWindow);
            NativeMethods.BringWindowToTop(window);
            NativeMethods.SetForegroundWindow(window);
            Emit("PROPERTY PasswordWindow=置顶");
            return true;
        }

        private static bool IsPasswordWindow(IntPtr window)
        {
            if (!NativeMethods.IsWindowVisible(window))
            {
                return false;
            }

            var className = new StringBuilder(256);
            NativeMethods.GetClassName(window, className, className.Capacity);
            var classText = className.ToString();

            var title = new StringBuilder(256);
            NativeMethods.GetWindowText(window, title, title.Capacity);
            var text = title.ToString();
            if (text.IndexOf("远程桌面连接", StringComparison.Ordinal) >= 0)
            {
                return false;
            }

            if (string.Equals(classText, "Credential Dialog Xaml Host", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (ContainsPasswordText(text))
            {
                return true;
            }

            uint processId;
            NativeMethods.GetWindowThreadProcessId(window, out processId);
            if (string.Equals(classText, "#32770", StringComparison.Ordinal)
                && processId == (uint)Process.GetCurrentProcess().Id)
            {
                return true;
            }

            try
            {
                var process = Process.GetProcessById((int)processId);
                if (string.Equals(process.ProcessName, "CredentialUIBroker", StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            catch (Exception)
            {
            }

            return false;
        }

        private static bool ContainsPasswordText(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return false;
            }
            return text.IndexOf("密码", StringComparison.Ordinal) >= 0
                || text.IndexOf("凭据", StringComparison.Ordinal) >= 0
                || text.IndexOf("Windows 安全", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("Windows Security", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("Password", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("Credential", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static void PutInterfaceBool(object ocx, string iidText, int slot, bool value)
        {
            IntPtr unknown = Marshal.GetIUnknownForObject(ocx);
            IntPtr iface = IntPtr.Zero;
            try
            {
                Guid iid = new Guid(iidText);
                int query = Marshal.QueryInterface(unknown, ref iid, out iface);
                if (query < 0 || iface == IntPtr.Zero)
                {
                    Marshal.ThrowExceptionForHR(query);
                }

                IntPtr vtable = Marshal.ReadIntPtr(iface);
                IntPtr method = Marshal.ReadIntPtr(vtable, slot * IntPtr.Size);
                PutVariantBoolDelegate call = (PutVariantBoolDelegate)Marshal.GetDelegateForFunctionPointer(
                    method,
                    typeof(PutVariantBoolDelegate));
                int result = call(iface, value ? (short)-1 : (short)0);
                if (result < 0)
                {
                    Marshal.ThrowExceptionForHR(result);
                }
            }
            finally
            {
                if (iface != IntPtr.Zero)
                {
                    Marshal.Release(iface);
                }

                Marshal.Release(unknown);
            }
        }

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int PutVariantBoolDelegate(IntPtr self, short value);

        internal static void HideOverlay()
        {
            StopMouseBlockTimer();
            StopPhysicalInputHooks();
            ReleaseMouseBlockTargets();
            if (_form == null || _form.IsDisposed)
            {
                return;
            }

            _form.Hide();
        }

        private static void OnFormVisibilityChanged(object sender, EventArgs e)
        {
            if (_form.Visible)
            {
                ApplyMouseBlock();
                return;
            }
            StopMouseBlockTimer();
            StopPhysicalInputHooks();
            ReleaseMouseBlockTargets();
        }

        private static void RequestExit()
        {
            try
            {
                if (_invokeTarget != null && _invokeTarget.IsHandleCreated)
                {
                    _invokeTarget.BeginInvoke(new Action(Shutdown));
                    return;
                }
            }
            catch (Exception)
            {
            }

            Environment.Exit(0);
        }

        private static void Shutdown()
        {
            if (_shuttingDown)
            {
                return;
            }

            _shuttingDown = true;
            StopPasswordWindowTopmostWatch();
            HideOverlay();
            if (_form != null && !_form.IsDisposed)
            {
                _form.Close();
                return;
            }

            Application.Exit();
        }

        private static void OnFormClosing(object sender, FormClosingEventArgs e)
        {
            _shuttingDown = true;
            StopMouseBlockTimer();
            StopPhysicalInputHooks();
            StopMuteTimer();
            ReleaseMouseBlockTargets();
            StopRefitTimer();
            StopDesktopRetryTimer();
            try
            {
                if (_cookie != null)
                {
                    _cookie.Disconnect();
                    _cookie = null;
                }
            }
            catch (Exception)
            {
            }

            _clientDisconnect = true;
            try
            {
                InvokeOcx("Disconnect");
            }
            catch (Exception)
            {
            }
        }

        private static void DisconnectClient()
        {
            _clientDisconnect = true;
            try
            {
                InvokeOcx("Disconnect");
            }
            catch (Exception exception)
            {
                // 会话已经注销时，Disconnect 返回 E_FAIL，断开事件仍会随后到来。
                if (IsClosedSessionFailure(exception))
                {
                    return;
                }

                _clientDisconnect = false;
                throw;
            }
        }

        private static bool IsClosedSessionFailure(Exception exception)
        {
            int hr = HResultOf(exception);
            return hr == unchecked((int)0x80004005) || hr == unchecked((int)0x8000FFFF);
        }

        private static string FormatException(Exception exception)
        {
            Exception inner = exception;
            while (inner.InnerException != null)
            {
                inner = inner.InnerException;
            }

            COMException com = inner as COMException;
            if (com != null)
            {
                return inner.Message
                    + " HRESULT=0x"
                    + com.ErrorCode.ToString("X8", CultureInfo.InvariantCulture);
            }

            return inner.Message;
        }

        internal static string FormatDisconnect(int disconnectReason)
        {
            var extended = 0;
            var description = "";
            bool clientDisconnect = _clientDisconnect;
            _clientDisconnect = false;
            try
            {
                object ocx = _rdp.RawOcx();
                object rawExtended = GetProp(ocx, "ExtendedDisconnectReason");
                if (rawExtended != null)
                {
                    extended = Convert.ToInt32(rawExtended, CultureInfo.InvariantCulture);
                }

                // 本机主动断开时，原因 1 的说明固定是「出现了内部错误」，并不表示失败。
                if (clientDisconnect && disconnectReason == 1 && extended == 0)
                {
                    description = "已断开";
                }
                else
                {
                    object rawDescription = ocx.GetType().InvokeMember(
                        "GetErrorDescription",
                        BindingFlags.InvokeMethod,
                        null,
                        ocx,
                        new object[] { disconnectReason, extended },
                        CultureInfo.InvariantCulture);
                    if (rawDescription != null)
                    {
                        description = rawDescription.ToString();
                    }
                }
            }
            catch (Exception)
            {
            }

            var line = "DISCONNECT "
                + disconnectReason.ToString(CultureInfo.InvariantCulture)
                + " "
                + extended.ToString(CultureInfo.InvariantCulture);
            if (!string.IsNullOrEmpty(description))
            {
                line = line + " " + description.Replace('\r', ' ').Replace('\n', ' ');
            }

            return line;
        }

        private static bool IsTrue(object actual)
        {
            if (actual is bool)
            {
                return (bool)actual;
            }

            try
            {
                return Convert.ToInt32(actual, CultureInfo.InvariantCulture) != 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static object GetProp(object target, string name)
        {
            return target.GetType().InvokeMember(
                name,
                BindingFlags.GetProperty,
                null,
                target,
                null,
                CultureInfo.InvariantCulture);
        }

        private static void SetProp(object target, string name, object value)
        {
            target.GetType().InvokeMember(
                name,
                BindingFlags.SetProperty,
                null,
                target,
                new object[] { value },
                CultureInfo.InvariantCulture);
        }

        private static void InvokeOcx(string method)
        {
            _rdp.RawOcx().GetType().InvokeMember(
                method,
                BindingFlags.InvokeMethod,
                null,
                _rdp.RawOcx(),
                null,
                CultureInfo.InvariantCulture);
        }

        private static void Emit(string line)
        {
            lock (_outputLock)
            {
                _output.WriteLine(line);
                _output.Flush();
            }
        }

        private static void ParseArgs(string[] args)
        {
            for (var index = 0; index < args.Length; index += 1)
            {
                var key = args[index];
                if (index + 1 >= args.Length)
                {
                    break;
                }

                var value = args[index + 1];
                if (key == "--parent")
                {
                    _parentHwnd = int.Parse(value, CultureInfo.InvariantCulture);
                }
                else if (key == "--width")
                {
                    _width = int.Parse(value, CultureInfo.InvariantCulture);
                    _desktopWidth = _width;
                }
                else if (key == "--height")
                {
                    _height = int.Parse(value, CultureInfo.InvariantCulture);
                    _desktopHeight = _height;
                }
                else if (key == "--port")
                {
                    _port = int.Parse(value, CultureInfo.InvariantCulture);
                }
                else if (key == "--mute")
                {
                    _mute = value == "1";
                }
                else if (key == "--shortcuts")
                {
                    _shortcuts = value != "0";
                }
                else if (key == "--smart-sizing")
                {
                    _smartSizing = value != "0";
                }
                else if (key == "--credssp")
                {
                    _credssp = value != "0";
                }
                else if (key == "--mouse-block")
                {
                    _blockPhysicalMouse = value == "1";
                }
                else if (key == "--clsid")
                {
                    _clsid = value.Trim().Trim('{', '}');
                }
                else if (key == "--autoconnect")
                {
                    _autoConnect = value != "0";
                }

                index += 1;
            }
        }

        private static void ApplyMouseBlock()
        {
            if (_blockPhysicalMouse)
            {
                RefreshMouseBlockTargets();
                return;
            }

            StopMouseBlockTimer();
            StopPhysicalInputHooks();
            ReleaseMouseBlockTargets();
        }

        private static void EnsurePhysicalInputHooks(List<IntPtr> windows)
        {
            var threads = new HashSet<uint>();
            try
            {
                foreach (IntPtr window in windows)
                {
                    uint processId;
                    uint threadId = NativeMethods.GetWindowThreadProcessId(window, out processId);
                    if (threadId == 0 || processId != NativeMethods.GetCurrentProcessId())
                    {
                        throw new InvalidOperationException("桌面分身输入窗口线程无效。");
                    }
                    threads.Add(threadId);
                    if (_physicalInputHooks.ContainsKey(threadId))
                    {
                        continue;
                    }
                    var hooks = new PhysicalInputHooks();
                    _physicalInputHooks.Add(threadId, hooks);
                    hooks.Mouse = NativeMethods.SetWindowsHookEx(
                        7, _physicalMouseCallback, IntPtr.Zero, threadId);
                    if (hooks.Mouse == IntPtr.Zero)
                    {
                        throw new System.ComponentModel.Win32Exception(
                            Marshal.GetLastWin32Error(), "安装桌面分身物理鼠标拦截失败。");
                    }
                    hooks.Keyboard = NativeMethods.SetWindowsHookEx(
                        2, _physicalKeyboardCallback, IntPtr.Zero, threadId);
                    if (hooks.Keyboard == IntPtr.Zero)
                    {
                        throw new System.ComponentModel.Win32Exception(
                            Marshal.GetLastWin32Error(), "安装桌面分身物理键盘拦截失败。");
                    }
                }
                foreach (uint threadId in new List<uint>(_physicalInputHooks.Keys))
                {
                    if (!threads.Contains(threadId))
                    {
                        ReleasePhysicalInputHooks(threadId);
                    }
                }
            }
            catch
            {
                StopPhysicalInputHooks();
                throw;
            }
        }

        private static void StopPhysicalInputHooks()
        {
            Exception failure = null;
            foreach (uint threadId in new List<uint>(_physicalInputHooks.Keys))
            {
                try
                {
                    ReleasePhysicalInputHooks(threadId);
                }
                catch (Exception exception)
                {
                    if (failure == null)
                    {
                        failure = exception;
                    }
                }
            }
            if (failure != null)
            {
                throw failure;
            }
        }

        private static void ReleasePhysicalInputHooks(uint threadId)
        {
            PhysicalInputHooks hooks = _physicalInputHooks[threadId];
            try
            {
                ReleasePhysicalInputHook(ref hooks.Keyboard);
            }
            finally
            {
                ReleasePhysicalInputHook(ref hooks.Mouse);
                if (hooks.Keyboard == IntPtr.Zero && hooks.Mouse == IntPtr.Zero)
                {
                    _physicalInputHooks.Remove(threadId);
                }
            }
        }

        private static void ReleasePhysicalInputHook(ref IntPtr hook)
        {
            if (hook == IntPtr.Zero)
            {
                return;
            }
            if (!NativeMethods.UnhookWindowsHookEx(hook))
            {
                throw new System.ComponentModel.Win32Exception(
                    Marshal.GetLastWin32Error(), "卸载桌面分身物理输入拦截失败。");
            }
            hook = IntPtr.Zero;
        }

        private static bool IsPhysicalInputTarget(IntPtr hwnd)
        {
            return _blockPhysicalMouse && !_shuttingDown && _form != null
                && !_form.IsDisposed && _form.IsHandleCreated
                && (hwnd == _form.Handle || NativeMethods.IsChild(_form.Handle, hwnd));
        }

        private static IntPtr BlockPhysicalMouse(int code, IntPtr wParam, IntPtr lParam)
        {
            // WH_MOUSE 只接收前台输入队列，不接收后台 SendMessage/PostMessage。
            if (code >= 0 && lParam != IntPtr.Zero)
            {
                var input = (NativeMethods.MouseHookData)Marshal.PtrToStructure(
                    lParam, typeof(NativeMethods.MouseHookData));
                if (IsPhysicalInputTarget(input.hwnd))
                {
                    return new IntPtr(1);
                }
            }
            return NativeMethods.CallNextHookEx(IntPtr.Zero, code, wParam, lParam);
        }

        private static IntPtr BlockPhysicalKeyboard(int code, IntPtr wParam, IntPtr lParam)
        {
            if (code >= 0 && IsPhysicalInputTarget(NativeMethods.GetFocus()))
            {
                return new IntPtr(1);
            }
            return NativeMethods.CallNextHookEx(IntPtr.Zero, code, wParam, lParam);
        }

        private static void EnsureMouseBlockTimer()
        {
            if (_mouseBlockTimer == null)
            {
                _mouseBlockTimer = new System.Windows.Forms.Timer();
                _mouseBlockTimer.Interval = 300;
                _mouseBlockTimer.Tick += delegate
                {
                    RefreshMouseBlockTargets();
                };
            }

            if (!_mouseBlockTimer.Enabled)
            {
                _mouseBlockTimer.Start();
            }
        }

        private static void StopMouseBlockTimer()
        {
            if (_mouseBlockTimer != null)
            {
                _mouseBlockTimer.Stop();
                _mouseBlockTimer.Dispose();
                _mouseBlockTimer = null;
            }
        }

        private static void RefreshMouseBlockTargets()
        {
            if (!_blockPhysicalMouse
                || _shuttingDown
                || _form == null
                || _form.IsDisposed
                || !_form.IsHandleCreated)
            {
                StopMouseBlockTimer();
                StopPhysicalInputHooks();
                ReleaseMouseBlockTargets();
                return;
            }

            var live = new List<IntPtr>();
            var seen = new Dictionary<IntPtr, bool>();
            CollectWindowTree(_form.Handle, live, seen, 0);
            try
            {
                EnsurePhysicalInputHooks(live);
            }
            catch
            {
                StopMouseBlockTimer();
                ReleaseMouseBlockTargets();
                throw;
            }
            for (int index = 0; index < live.Count; index++)
            {
                IntPtr hwnd = live[index];
                MouseBlockWindow existing;
                if (_mouseBlockWindows.TryGetValue(hwnd, out existing))
                {
                    if (existing.Handle == hwnd)
                    {
                        continue;
                    }
                    ReleaseMouseBlockTarget(hwnd);
                }

                var blocker = new MouseBlockWindow();
                try
                {
                    blocker.AssignHandle(hwnd);
                    _mouseBlockWindows[hwnd] = blocker;
                }
                catch (Exception)
                {
                    blocker.Detach();
                    StopMouseBlockTimer();
                    StopPhysicalInputHooks();
                    ReleaseMouseBlockTargets();
                    throw;
                }
            }

            var stale = new List<IntPtr>();
            foreach (KeyValuePair<IntPtr, MouseBlockWindow> pair in _mouseBlockWindows)
            {
                if (!seen.ContainsKey(pair.Key) || !NativeMethods.IsWindow(pair.Key))
                {
                    stale.Add(pair.Key);
                }
            }

            for (int index = 0; index < stale.Count; index++)
            {
                ReleaseMouseBlockTarget(stale[index]);
            }
            EnsureMouseBlockTimer();
        }

        private static void CollectWindowTree(
            IntPtr root,
            List<IntPtr> live,
            Dictionary<IntPtr, bool> seen,
            int depth)
        {
            if (root == IntPtr.Zero || depth > 32 || seen.ContainsKey(root) || !NativeMethods.IsWindow(root))
            {
                return;
            }

            seen[root] = true;
            live.Add(root);
            IntPtr child = NativeMethods.GetWindow(root, NativeMethods.GwChild);
            int guard = 0;
            while (child != IntPtr.Zero && guard < 256)
            {
                CollectWindowTree(child, live, seen, depth + 1);
                child = NativeMethods.GetWindow(child, NativeMethods.GwHwndNext);
                guard++;
            }
        }

        private static void ReleaseMouseBlockTargets()
        {
            var keys = new List<IntPtr>(_mouseBlockWindows.Keys);
            for (int index = 0; index < keys.Count; index++)
            {
                ReleaseMouseBlockTarget(keys[index]);
            }
        }

        private static void ReleaseMouseBlockTarget(IntPtr hwnd)
        {
            MouseBlockWindow blocker;
            if (!_mouseBlockWindows.TryGetValue(hwnd, out blocker))
            {
                return;
            }

            blocker.Detach();
            _mouseBlockWindows.Remove(hwnd);
        }

        private sealed class MouseBlockWindow : NativeWindow
        {
            public void Detach()
            {
                ReleaseHandle();
            }

            protected override void WndProc(ref Message message)
            {
                // 后台输入也会先查询命中窗口、设置光标，所有输入消息统一按来源判断。
                if (_blockPhysicalMouse && BlocksLocalInput(message.Msg))
                {
                    if (message.Msg == 0x0021)
                    {
                        message.Result = new IntPtr(3);
                        return;
                    }

                    if (message.Msg == 0x0084)
                    {
                        message.Result = new IntPtr(-1);
                        return;
                    }

                    if (message.Msg == 0x0020)
                    {
                        message.Result = new IntPtr(1);
                        return;
                    }

                    message.Result = IntPtr.Zero;
                    return;
                }

                base.WndProc(ref message);
            }

            private static bool BlocksLocalInput(int message)
            {
                if (!AlwaysBlocks(message) && !IsPointerOrKey(message))
                {
                    return false;
                }

                return !IsBackgroundMessage();
            }

            private static bool AlwaysBlocks(int message)
            {
                if (message == 0x0020 || message == 0x0084 || message == 0x00FF)
                {
                    return true;
                }

                if (message >= 0x02A0 && message <= 0x02A3)
                {
                    return true;
                }

                return message >= 0x0240 && message <= 0x0257;
            }

            private static bool IsPointerOrKey(int message)
            {
                if (message == 0x0021 || message == 0x0319)
                {
                    return true;
                }

                if (message >= 0x0100 && message <= 0x0109)
                {
                    return true;
                }

                if (message >= 0x0200 && message <= 0x020E)
                {
                    return true;
                }

                return message >= 0x00A0 && message <= 0x00AD;
            }

            private static bool IsBackgroundMessage()
            {
                NativeMethods.InputMessageSource source;
                if (!NativeMethods.GetCurrentInputMessageSource(out source))
                {
                    throw new InvalidOperationException("读取输入消息来源失败。");
                }

                return source.deviceType == NativeMethods.ImdtUnavailable;
            }

        }
    }

    [ComImport]
    [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    internal class MMDeviceEnumeratorComObject
    {
    }

    [ComImport]
    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceEnumerator
    {
        [PreserveSig]
        int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);

        [PreserveSig]
        int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
    }

    [ComImport]
    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDevice
    {
        [PreserveSig]
        int Activate(
            ref Guid interfaceId,
            int classContext,
            IntPtr activationParams,
            [MarshalAs(UnmanagedType.IUnknown)] out object instance);
    }

    [ComImport]
    [Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionManager2
    {
        [PreserveSig]
        int GetAudioSessionControl(ref Guid sessionId, int streamFlags, out IntPtr session);

        [PreserveSig]
        int GetSimpleAudioVolume(ref Guid sessionId, int streamFlags, out ISimpleAudioVolume volume);

        [PreserveSig]
        int GetSessionEnumerator(out IAudioSessionEnumerator enumerator);
    }

    [ComImport]
    [Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionEnumerator
    {
        [PreserveSig]
        int GetCount(out int count);

        [PreserveSig]
        int GetSession(int index, out IAudioSessionControl2 session);
    }

    [ComImport]
    [Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionControl2
    {
        [PreserveSig]
        int GetState(out int state);

        [PreserveSig]
        int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);

        [PreserveSig]
        int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string name, ref Guid context);

        [PreserveSig]
        int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);

        [PreserveSig]
        int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string path, ref Guid context);

        [PreserveSig]
        int GetGroupingParam(out Guid grouping);

        [PreserveSig]
        int SetGroupingParam(ref Guid grouping, ref Guid context);

        [PreserveSig]
        int RegisterAudioSessionNotification(IntPtr notification);

        [PreserveSig]
        int UnregisterAudioSessionNotification(IntPtr notification);

        [PreserveSig]
        int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string identifier);

        [PreserveSig]
        int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string identifier);

        [PreserveSig]
        int GetProcessId(out int processId);

        [PreserveSig]
        int IsSystemSoundsSession();

        [PreserveSig]
        int SetDuckingPreference([MarshalAs(UnmanagedType.Bool)] bool optOut);
    }

    [ComImport]
    [Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface ISimpleAudioVolume
    {
        [PreserveSig]
        int SetMasterVolume(float level, ref Guid context);

        [PreserveSig]
        int GetMasterVolume(out float level);

        [PreserveSig]
        int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context);

        [PreserveSig]
        int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    }
}

