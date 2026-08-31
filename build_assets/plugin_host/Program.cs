using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

internal static class Program
{
    const int FrameMagic = 0x3146504C;
    const int FrameHeaderSize = 16;
    const int FrameMapSize = 64 * 1024 * 1024;
    const string PipePrefix = "lca-plugin-";

    static readonly object FrameLock = new object();
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool SetDllDirectory(string lpPathName);

    [DllImport("RegDll.dll", CharSet = CharSet.Unicode, EntryPoint = "SetDllPathW")]
    static extern int SetDllPathW(string path, int mode);

    [STAThread]
    static int Main(string[] args)
    {
        string pipeName = ParsePipeName(args);
        if (string.IsNullOrEmpty(pipeName))
            return 1;

        object dm = null;
        MemoryMappedFile map = null;
        string regCode = "";
        try
        {
            using (var pipe = new NamedPipeServerStream(pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte))
            {
                pipe.WaitForConnection();
                Dictionary<string, object> first = ReadMessage(pipe);
                if (first == null)
                    return 1;
                object id = GetValue(first, "id");
                if (!string.Equals(GetString(first, "method"), "init", StringComparison.Ordinal))
                {
                    WriteError(pipe, id, "首包必须是 init", regCode);
                    return 1;
                }

                Dictionary<string, object> initArgs = GetArgs(first);
                string pluginDir = GetString(initArgs, "plugin_dir");
                regCode = GetString(initArgs, "reg_code");
                if (string.IsNullOrWhiteSpace(regCode))
                {
                    WriteError(pipe, id, "未填写插件注册码", "");
                    return 1;
                }

                try
                {
                    if (string.IsNullOrWhiteSpace(pluginDir) || !Directory.Exists(pluginDir))
                        throw new InvalidOperationException("插件目录无效");
                    if (!SetDllDirectory(pluginDir))
                        throw new InvalidOperationException("SetDllDirectory 失败");
                    if (SetDllPathW(pluginDir, 0) == 0)
                        throw new InvalidOperationException("SetDllPathW 失败");
                    Type prog = Type.GetTypeFromProgID("dm.dmsoft");
                    if (prog == null)
                        throw new InvalidOperationException("找不到 dm.dmsoft");
                    dm = Activator.CreateInstance(prog);
                    if (dm == null)
                        throw new InvalidOperationException("无法创建 dm.dmsoft");
                    if (!Authorize(dm, regCode))
                        throw new InvalidOperationException("插件授权失败");
                    map = MemoryMappedFile.CreateOrOpen(MapNameFromPipe(pipeName), FrameMapSize);
                    WriteOk(pipe, id, new Dictionary<string, object>());
                }
                catch (Exception ex)
                {
                    WriteError(pipe, id, SafeError(ex, regCode), regCode);
                    return 1;
                }

                bool running = true;
                while (running && pipe.IsConnected)
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
                    object msgId = GetValue(message, "id");
                    string method = GetString(message, "method");
                    Dictionary<string, object> callArgs = GetArgs(message);
                    try
                    {
                        object result;
                        if (!Dispatch(dm, map, method, callArgs, out result, out running))
                            WriteError(pipe, msgId, "unknown method: " + method, regCode);
                        else
                            WriteOk(pipe, msgId, result);
                    }
                    catch (Exception ex)
                    {
                        WriteError(pipe, msgId, SafeError(ex, regCode), regCode);
                    }
                }
            }
        }
        finally
        {
            TryUnbind(dm);
            if (map != null)
                map.Dispose();
        }
        return 0;
    }

    static bool Dispatch(object dm, MemoryMappedFile map, string method, Dictionary<string, object> args, out object result, out bool running)
    {
        running = true;
        result = null;
        switch (method)
        {
            case "bind":
                result = new Dictionary<string, object> { { "ok", DoBind(dm, args) } };
                return true;
            case "unbind":
                TryUnbind(dm);
                result = new Dictionary<string, object>();
                return true;
            case "capture":
                result = DoCapture(dm, map, args);
                return true;
            case "move_to":
                result = CallOk(dm, "MoveTo", GetInt(args, "x"), GetInt(args, "y"));
                return true;
            case "mouse_click":
                result = CallOk(dm, MouseMethod(GetString(args, "button"), "click"));
                return true;
            case "mouse_double_click":
                result = CallOk(dm, MouseMethod(GetString(args, "button"), "double"));
                return true;
            case "mouse_down":
                result = CallOk(dm, MouseMethod(GetString(args, "button"), "down"));
                return true;
            case "mouse_up":
                result = CallOk(dm, MouseMethod(GetString(args, "button"), "up"));
                return true;
            case "wheel":
                result = DoWheel(dm, GetInt(args, "delta"));
                return true;
            case "key_down":
                result = CallOk(dm, "KeyDown", GetInt(args, "vk_code"));
                return true;
            case "key_up":
                result = CallOk(dm, "KeyUp", GetInt(args, "vk_code"));
                return true;
            case "key_press":
                result = CallOk(dm, "KeyPress", GetInt(args, "vk_code"));
                return true;
            case "key_press_str":
                result = CallOk(dm, "KeyPressStr", GetString(args, "text"), GetInt(args, "delay", 30));
                return true;
            case "client_size":
                result = DoClientSize(dm, GetInt(args, "hwnd"));
                return true;
            case "last_error":
                result = LastError(dm);
                return true;
            case "shutdown":
                TryUnbind(dm);
                result = new Dictionary<string, object>();
                running = false;
                return true;
            default:
                return false;
        }
    }

    static bool DoBind(object dm, Dictionary<string, object> args)
    {
        int displayHwnd = GetInt(args, "display_hwnd");
        int inputHwnd = GetInt(args, "input_hwnd");
        string display = GetString(args, "display");
        string mouse = GetString(args, "mouse");
        string keypad = GetString(args, "keypad");
        int mode = GetInt(args, "mode");
        if (displayHwnd == inputHwnd || inputHwnd <= 0)
            return CallOk(dm, "BindWindow", displayHwnd, display, mouse, keypad, mode);
        try
        {
            return IsSuccessInt(Invoke(dm, "BindWindowEx", displayHwnd, display, mouse, keypad, "", mode));
        }
        catch (Exception)
        {
            return CallOk(dm, "BindWindow", displayHwnd, display, mouse, keypad, mode);
        }
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

    static bool DoWheel(object dm, int delta)
    {
        if (delta == 0)
            return false;
        return CallOk(dm, delta > 0 ? "WheelUp" : "WheelDown");
    }

    static bool Authorize(object dm, string regCode)
    {
        try
        {
            object ver = Invoke(dm, "Ver", regCode);
            if (IsSuccessInt(ver))
                return true;
            if (!IsVersionString(ver))
                return false;
        }
        catch (Exception)
        {
        }
        object reg = Invoke(dm, "Reg", regCode, "");
        return IsSuccessInt(reg);
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
            return IsSuccessInt(ret);
        }
        catch (Exception)
        {
            return false;
        }
    }

    static byte[] GetScreenDataBmp(object dm, int x1, int y1, int x2, int y2)
    {
        try
        {
            object[] invokeArgs = { x1, y1, x2, y2, 0, 0 };
            ParameterModifier mods = new ParameterModifier(6);
            mods[4] = true;
            mods[5] = true;
            dm.GetType().InvokeMember(
                "GetScreenDataBmp",
                BindingFlags.InvokeMethod,
                null,
                dm,
                invokeArgs,
                new[] { mods },
                null,
                null);
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

    static void TryUnbind(object dm)
    {
        if (dm == null)
            return;
        try
        {
            Invoke(dm, "UnBindWindow");
        }
        catch (Exception)
        {
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
        switch (action)
        {
            case "double":
                return prefix + "DoubleClick";
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

}
