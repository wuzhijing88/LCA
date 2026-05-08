import ctypes
import json
import time

from typing import Tuple, List, Callable, Union

from .OLAPlugDLLHelper import OLAPlugDLLHelper


class OLAPlugServer:

    _LAZY_INIT_EXEMPT_METHODS = {
        "__init__",
        "__getattribute__",
        "_ensure_ola_object",
        "CreateCOLAPlugInterFace",
        "DestroyCOLAPlugInterFace",
        "ReleaseObj",
        "Reg",
        "PtrToStringUTF8",
    }

    def __init__(self):
        self.OLAObject = None
        self.UserCode = ""
        self.SoftCode = ""
        self.FeatureList = ""

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if name in object.__getattribute__(self, "_LAZY_INIT_EXEMPT_METHODS"):
            return attr
        if name.startswith("_") or not callable(attr):
            return attr

        def _wrapped(*args, **kwargs):
            object.__getattribute__(self, "_ensure_ola_object")()
            return attr(*args, **kwargs)

        return _wrapped

    def _ensure_ola_object(self) -> int:
        return self.CreateCOLAPlugInterFace()
        # 设置默认编码为UTF-8

    def PtrToStringUTF8(self, ptr) -> str:
        """
        根据指针返回字符串
        :param ptr: 指针地址
        :return: 对应的字符串
        """
        if ptr==0:
            return ""

        try:
            str_ptr = ctypes.cast(ptr, ctypes.c_char_p)
            byte_str = str_ptr.value
            text = byte_str.decode("utf-8") if byte_str else ""
        except Exception as e:
            print(e)
        finally:
            self.FreeStringPtr(ptr)

        return text

    def ReleaseObj(self) -> int:
        if self.OLAObject is None:
            return 1
        result = self.DestroyCOLAPlugInterFace()
        self.OLAObject = None
        return result

    def CreateCOLAPlugInterFace(self) -> int:
        """创建OLA对象

        Returns:
            OLAPlug对象指针，用于后续接口的传参

        Notes:
            1. DLL与COM的调用模式不一样。创建的对象需要使用 DestroyCOLAPlugInterFace 接口释放内存。
        """
        if self.OLAObject is not None:
            return self.OLAObject

        func = OLAPlugDLLHelper.get_function("CreateCOLAPlugInterFace")
        created = func()
        self.OLAObject = created

        if created:
            config_func = OLAPlugDLLHelper.get_function("SetConfigByKey")
            config_func(created, "DefaultEncoding", "1")

        return self.OLAObject

    def DestroyCOLAPlugInterFace(self) -> int:
        """释放OLA对象内存

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该接口为DLL版本专用。
        """
        if self.OLAObject is None:
            return 1

        func = OLAPlugDLLHelper.get_function("DestroyCOLAPlugInterFace")
        result = func(self.OLAObject)
        if result:
            self.OLAObject = None
        return result

    def Ver(self) -> str:
        """返回当前插件版本号。

        Returns:
            当前插件的版本描述字符串

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("Ver")
        return self.PtrToStringUTF8(func())

    def GetPlugInfo(self, _type: int) -> str:
        """获取插件信息

        Args:
            _type: 信息类型，可选值:
                1: 精简版信息
                2: 完整版信息

        Returns:
            插件信息

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("GetPlugInfo")
        return self.PtrToStringUTF8(func(_type))

    def SetPath(self, path: str) -> int:
        """设置全局路径。建议使用 SetConfig 接口。

        Args:
            path: 要设置的路径值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetPath")
        return func(self.OLAObject, path)

    def GetPath(self) -> str:
        """获取全局路径。(可用于调试) 建议使用 GetConfig 接口。

        Returns:
            以字符串的形式返回当前设置的全局路径

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("GetPath")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def GetMachineCode(self) -> str:
        """获取本机的机器码。此机器码用于网站后台。要求调用进程必须有管理员权限，否则返回空串。

        Returns:
            字符串表达的机器码。

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
            2. 此机器码包含的硬件设备有硬盘、显卡、网卡等。重装系统不会改变此值。
            3. 插拔任何USB设备，以及安装任何网卡驱动程序，都会导致机器码改变。
        """
        func = OLAPlugDLLHelper.get_function("GetMachineCode")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def GetBasePath(self) -> str:
        """获取注册在系统中的OLAPlug.dll的路径。

        Returns:
            返回OLAPlug.dll所在路径。

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("GetBasePath")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def Reg(self, userCode: str, softCode: str, featureList: str) -> int:
        """调用此函数来注册，从而使用插件的高级功能。推荐使用此函数。多个OLA对象仅需要注册一次。

        Args:
            userCode: 用户码
            softCode: 软件码
            featureList: 功能列表

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Reg")
        return func(userCode, softCode, featureList)

    def BindWindow(self, hwnd: int, display: str, mouse: str, keypad: str, mode: int) -> int:
        """绑定指定的窗口，并指定这个窗口的屏幕颜色获取方式、鼠标仿真模式、键盘仿真模式以及模式设定

        Args:
            hwnd: 指定的窗口句柄
            display: 屏幕颜色获取方式，可选值:
                normal: 正常模式，平常我们用的前台截屏模式
                gdi: gdi模式
                gdi2: gdi2模式，此模式兼容性较强，但是速度比gdi模式要慢许多
                gdi3: gdi3模式，此模式兼容性较强，但是速度比gdi模式要慢许多
                gdi4: gdi4模式，支持小程序、浏览器截图
                gdi5: gdi5模式，支持小程序、浏览器截图
                dxgi: DXGI模式, 支持小程序和浏览器截图,在windows10 1903及以上版本中支持
                vnc: vnc模式
                dx: dx模式（需要管理员权限）
                vmware: 虚拟机模式（需要管理员权限）
            mouse: 鼠标仿真模式，可选值:
                normal: 正常模式，平常我们用的前台鼠标模式
                windows: Windows模式，采取模拟windows消息方式
                windows3: Windows3模式,采取模拟windows消息方式,适用于多窗口的进程
                vnc: vnc模式
                dx.mouse.position.lock.api: 通过封锁系统API来锁定鼠标位置
                dx.mouse.position.lock.message: 通过封锁系统消息来锁定鼠标位置
                dx.mouse.focus.input.api: 通过封锁系统API来锁定鼠标输入焦点
                dx.mouse.focus.input.message: 通过封锁系统消息来锁定鼠标输入焦点
                dx.mouse.clip.lock.api: 通过封锁系统API来锁定刷新区域
                dx.mouse.input.lock.api: 通过封锁系统API来锁定鼠标输入接口
                dx.mouse.state.api: 通过封锁系统API来锁定鼠标输入状态
                dx.mouse.state.message: 通过封锁系统消息来锁定鼠标输入状态
                dx.mouse.api: 通过封锁系统API来模拟dx鼠标输入
                dx.mouse.cursor: 开启后台获取鼠标特征码
                dx.mouse.raw.input: 特定窗口鼠标操作支持
                dx.mouse.input.lock.api2: 防止前台鼠标移动
                dx.mouse.input.lock.api3: 防止前台鼠标移动
                dx.mouse.raw.input.active: 配合dx.mouse.raw.input使用
                dx.mouse.vmware: 虚拟机鼠标穿透模式,目前只支持vm16,仅限高级版使用
            keypad: 键盘仿真模式，可选值:
                normal: 正常模式，平常我们用的前台键盘模式
                windows: Windows模式，采取模拟windows消息方式
                vnc: vnc模式
                dx.keypad.input.lock.api: 通过封锁系统API来锁定键盘输入接口
                dx.keypad.state.api: 通过封锁系统API来锁定键盘输入状态
                dx.keypad.api: 通过封锁系统API来模拟dx键盘输入
                dx.keypad.raw.input: 特定窗口键盘操作支持
                dx.keypad.raw.input.active: 配合dx.keypad.raw.input使用
                dx.keypad.vmware: 虚拟机键盘穿透模式,目前只支持vm16,仅限高级版使用
            mode: 模式设定，可选值:
                0: 推荐模式，此模式比较通用，而且后台效果是最好的
                1: 远程线程注入
                2: 驱动注入模式1,当0,1无法使用时使用,需要加载驱动,第一次使用驱动会下载PDB文件绑定时间会变长
                3: 驱动注入模式2,当0,1无法使用时使用,需要加载驱动,第一次使用驱动会下载PDB文件绑定时间会变长
                4: 驱动注入模式3,当0,1无法使用时使用,需要加载驱动,第一次使用驱动会下载PDB文件绑定时间会变长

        Returns:
            操作结果
                0: 绑定失败
                1: 绑定成功

        Notes:
            1. dx模式组合可以使用"|"连接多个模式，例如："dx.mouse.position.lock.api|dx.mouse.focus.input.api"
        """
        func = OLAPlugDLLHelper.get_function("BindWindow")
        return func(self.OLAObject, hwnd, display, mouse, keypad, mode)

    def BindWindowEx(self, hwnd: int, display: str, mouse: str, keypad: str, pubstr: str, mode: int) -> int:
        """绑定指定的窗口，并指定这个窗口的屏幕颜色获取方式、鼠标仿真模式、键盘仿真模式以及模式设定

        Args:
            hwnd: 指定的窗口句柄
            display: 屏幕颜色获取方式，可选值:
                normal: 正常模式，平常我们用的前台截屏模式
                gdi: gdi模式
                gdi2: gdi2模式，此模式兼容性较强，但是速度比gdi模式要慢许多
                gdi3: gdi3模式，此模式兼容性较强，但是速度比gdi模式要慢许多
                gdi4: gdi4模式，支持小程序、浏览器截图
                gdi5: gdi5模式，支持小程序、浏览器截图
                dxgi: DXGI模式, 支持小程序和浏览器截图,在windows10 1903及以上版本中支持
                vnc: vnc模式
                dx: dx模式（需要管理员权限）
                vmware: 虚拟机模式（需要管理员权限）
            mouse: 鼠标仿真模式，可选值:
                normal: 正常模式，平常我们用的前台鼠标模式
                windows: Windows模式，采取模拟windows消息方式
                windows3: Windows3模式,采取模拟windows消息方式,适用于多窗口的进程
                vnc: vnc模式
                dx.mouse.position.lock.api: 通过封锁系统API来锁定鼠标位置
                dx.mouse.position.lock.message: 通过封锁系统消息来锁定鼠标位置
                dx.mouse.focus.input.api: 通过封锁系统API来锁定鼠标输入焦点
                dx.mouse.focus.input.message: 通过封锁系统消息来锁定鼠标输入焦点
                dx.mouse.clip.lock.api: 通过封锁系统API来锁定刷新区域
                dx.mouse.input.lock.api: 通过封锁系统API来锁定鼠标输入接口
                dx.mouse.state.api: 通过封锁系统API来锁定鼠标输入状态
                dx.mouse.state.message: 通过封锁系统消息来锁定鼠标输入状态
                dx.mouse.api: 通过封锁系统API来模拟dx鼠标输入
                dx.mouse.cursor: 开启后台获取鼠标特征码
                dx.mouse.raw.input: 特定窗口鼠标操作支持
                dx.mouse.input.lock.api2: 防止前台鼠标移动
                dx.mouse.input.lock.api3: 防止前台鼠标移动
                dx.mouse.raw.input.active: 配合dx.mouse.raw.input使用
                dx.mouse.vmware: 虚拟机鼠标穿透模式,目前只支持vm16,仅限高级版使用
            keypad: 键盘仿真模式，可选值:
                normal: 正常模式，平常我们用的前台键盘模式
                windows: Windows模式，采取模拟windows消息方式
                vnc: vnc模式
                dx.keypad.input.lock.api: 通过封锁系统API来锁定键盘输入接口
                dx.keypad.state.api: 通过封锁系统API来锁定键盘输入状态
                dx.keypad.api: 通过封锁系统API来模拟dx键盘输入
                dx.keypad.raw.input: 特定窗口键盘操作支持
                dx.keypad.raw.input.active: 配合dx.keypad.raw.input使用
                dx.keypad.vmware: 虚拟机键盘穿透模式,目前只支持vm16,仅限高级版使用
            pubstr: 通用绑定模式（暂未启用），可选值:
                dx.public.graphic.revert: 翻转DX截图的图像结果
                dx.public.active.api: 自动定时发送激活命令
                dx.public.active.api2: 自动定时发送激活命令2
                ola.bypass.guard: 绑定失败的时候可以尝试打开
            mode: 模式设定，可选值:
                0: 推荐模式，此模式比较通用，而且后台效果是最好的
                1: 远程线程注入
                2: 驱动注入模式1,当0,1无法使用时使用,需要加载驱动,第一次使用驱动会下载PDB文件绑定时间会变长
                3: 驱动注入模式2,当0,1无法使用时使用,需要加载驱动,第一次使用驱动会下载PDB文件绑定时间会变长
                4: 驱动注入模式3,当0,1无法使用时使用,需要加载驱动,第一次使用驱动会下载PDB文件绑定时间会变长

        Returns:
            操作结果
                0: 绑定失败
                1: 绑定成功

        Notes:
            1. dx模式组合可以使用"|"连接多个模式，例如："dx.mouse.position.lock.api|dx.mouse.focus.input.api"
        """
        func = OLAPlugDLLHelper.get_function("BindWindowEx")
        return func(self.OLAObject, hwnd, display, mouse, keypad, pubstr, mode)

    def UnBindWindow(self) -> int:
        """解绑窗口，取消之前通过 BindWindow 或 BindWindowEx 绑定的窗口。

        Returns:
            操作结果
                0: 解绑失败
                1: 解绑成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnBindWindow")
        return func(self.OLAObject)

    def GetBindWindow(self) -> int:
        """获取当前对象已经绑定的窗口句柄，如果没有绑定窗口则返回0

        Returns:
            返回当前绑定的窗口句柄。如果没有绑定窗口，则返回0。

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetBindWindow")
        return func(self.OLAObject)

    def ReleaseWindowsDll(self, hwnd: int) -> int:
        """强制卸载已经注入到指定窗口的HookDLL。此函数用于清理和释放窗口相关的DLL资源，但需要谨慎使用，因为它会影响其他使用相同DLL的OLA对象。

        Args:
            hwnd: 窗口句柄

        Returns:
            0 卸载失败（可能原因：无效的窗口句柄、DLL已卸载、权限不足等），1 卸载成功。
                0: 卸载失败
                1: 卸载成功

        Notes:
            1. 此操作为强制卸载，会影响使用相同DLL的其他OLA对象。
            2. 建议在程序退出前的清理工作、确认没有其他OLA对象需要使用该DLL、或处理DLL加载异常时使用。
            3. 卸载DLL后，相关的功能将无法使用
            4. 建议在卸载前保存必要的数据。
            5. 某些系统窗口可能会拒绝DLL卸载操作。
            6. 如果有多个OLA对象共享DLL，应协调好卸载时机。
            7. 建议实现错误处理和日志记录机制
            8. 在批量操作时要注意性能和稳定性。
        """
        func = OLAPlugDLLHelper.get_function("ReleaseWindowsDll")
        return func(self.OLAObject, hwnd)

    def FreeStringPtr(self, ptr: int) -> int:
        """释放字符串内存。

        Args:
            ptr: 要释放的字符串内存地址

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FreeStringPtr")
        return func(ptr)

    def FreeMemoryPtr(self, ptr: int) -> int:
        """释放字节流内存。

        Args:
            ptr: 要释放的字节流地址

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FreeMemoryPtr")
        return func(ptr)

    def GetStringSize(self, ptr: int) -> int:
        """读取字符串大小。

        Args:
            ptr: 字符串内存地址

        Returns:
            字符串缓冲区大小

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetStringSize")
        return func(ptr)

    def GetStringFromPtr(self, ptr: int, lpString: str, size: int) -> int:
        """从指定内存地址读取字符串，参考windows函数 GetWindowText实现。

        Args:
            ptr: 字符串内存地址。
            lpString: 接收字符串的缓冲区。
            size: 缓冲区大小，可以通过 GetStringSize 接口读取字符串大小，size要+1用于存储终止符'\0'。

        Returns:
            成功返回字符串实际长度，失败返回0。

        Notes:
            1. 使用此函数时需要确保传入的内存地址有效且可访问。
            2. 建议在使用前先通过 GetStringSize 接口获取实际需要的缓冲区大小。
            3. 缓冲区大小不足可能导致字符串截断。
        """
        func = OLAPlugDLLHelper.get_function("GetStringFromPtr")
        return func(ptr, lpString, size)

    def Delay(self, millisecond: int) -> int:
        """延时指定的毫秒，过程中不阻塞UI操作。一般高级语言使用。按键用不到。

        Args:
            millisecond: 延时时间（毫秒）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Delay")
        return func(millisecond)

    def Delays(self, minMillisecond: int, maxMillisecond: int) -> int:
        """延时指定范围内随机毫秒，过程中不阻塞UI操作。一般高级语言使用。按键用不到。

        Args:
            minMillisecond: 最小延时时间（毫秒）
            maxMillisecond: 最大延时时间（毫秒）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Delays")
        return func(minMillisecond, maxMillisecond)

    def SetUAC(self, enable: int) -> int:
        """开启/关闭UAC。

        Args:
            enable: 是否启用UAC。

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetUAC")
        return func(self.OLAObject, enable)

    def CheckUAC(self) -> int:
        """检测当前系统是否有开启UAC(用户账户控制)。

        Returns:
            当前状态
                0: 关闭
                1: 开启

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CheckUAC")
        return func(self.OLAObject)

    def RunApp(self, appPath: str, mode: int) -> int:
        """运行指定的应用程序。

        Args:
            appPath: 要运行的程序路径。
            mode: 运行模式，可选值:
                0: 普通模式
                1: 加强模式

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RunApp")
        return func(self.OLAObject, appPath, mode)

    def ExecuteCmd(self, cmd: str, current_dir: str, time_out: int) -> str:
        """执行指定的CMD指令，并返回cmd的输出结果。

        Args:
            cmd: 要执行的cmd命令。
            current_dir: 执行此cmd命令时所在目录。如果为空，表示使用当前目录。
            time_out: 超时设置，单位是毫秒。0表示一直等待。大于0表示等待指定的时间后强制结束。

        Returns:
            cmd指令的执行结果。返回空字符串表示执行失败。

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("ExecuteCmd")
        return self.PtrToStringUTF8(func(self.OLAObject, cmd, current_dir, time_out))

    def GetConfig(self, configKey: str) -> str:
        """读取用户自定义设置。

        Args:
            configKey: 配置项名称。

        Returns:
            返回匹配结果，例如 {"EnableRealKeypad":false, "EnableRealMouse":true, ...}。

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("GetConfig")
        return self.PtrToStringUTF8(func(self.OLAObject, configKey))

    def SetConfig(self, configStr: Union[str, dict]) -> int:
        """修改用户自定义设置。

        Args:
            configStr: 配置项字符串，格式为 {"key1":value1,"key2":"value2"}。

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        if not isinstance(configStr, str):
            configStr = json.dumps(configStr)
        func = OLAPlugDLLHelper.get_function("SetConfig")
        return func(self.OLAObject, configStr)

    def SetConfigByKey(self, key: str, value: str) -> int:
        """修改用户自定义设置。

        Args:
            key: 配置项字符串，如: RealMouseMode。
            value: 配置项值字符串，如: true。

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetConfigByKey")
        return func(self.OLAObject, key, value)

    def SendDropFiles(self, hwnd: int, file_path: str) -> int:
        """拖动文件到指定窗口。

        Args:
            hwnd: 窗口句柄
            file_path: 文件路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SendDropFiles")
        return func(self.OLAObject, hwnd, file_path)

    def SetDefaultEncode(self, inputEncoding: int, outputEncoding: int) -> int:
        """设置默认编码。

        Args:
            inputEncoding: 输入编码。默认值0，可选值:
                0: gbk
                1: utf-8
                2: Unicode
            outputEncoding: 输出编码。默认值1，可选值:
                0: gbk
                1: utf-8
                2: Unicode

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetDefaultEncode")
        return func(inputEncoding, outputEncoding)

    def GetLastError(self) -> int:
        """获取最后一次错误ID。

        Returns:
            错误ID

        Notes:
            1. 错误ID为0表示没有错误。
        """
        func = OLAPlugDLLHelper.get_function("GetLastError")
        return func()

    def GetLastErrorString(self) -> str:
        """获取最后一次错误字符串。

        Returns:
            错误字符串

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存。
        """
        func = OLAPlugDLLHelper.get_function("GetLastErrorString")
        return self.PtrToStringUTF8(func())

    def HideModule(self, moduleName: str) -> int:
        """隐藏指定模块

        Args:
            moduleName: 模块名称

        Returns:
            隐藏上下文

        Notes:
            1. 隐藏模块可能会导致未知的问题,请谨慎使用
            2. 隐藏上下文需要调用 UnhideModule 接口释放
        """
        func = OLAPlugDLLHelper.get_function("HideModule")
        return func(self.OLAObject, moduleName)

    def UnhideModule(self, ctx: int) -> int:
        """恢复指定模块

        Args:
            ctx: 隐藏上下文

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 隐藏上下文需要调用 HideModule 接口生成，并且不能重复释放
            2. 释放后，模块将恢复显示
        """
        func = OLAPlugDLLHelper.get_function("UnhideModule")
        return func(self.OLAObject, ctx)

    def GetRandomNumber(self, _min: int, _max: int) -> int:
        """获取随机整数

        Args:
            _min: 随机数的最小值（包含）
            _max: 随机数的最大值（包含）

        Returns:
            返回指定范围内的随机整数

        Notes:
            1. 返回的随机数包含最小值和最大值
            2. 每个线程使用独立的随机种子，确保多线程环境下的随机性
            3. 适用于需要生成随机整数用于测试、游戏、模拟等场景
            4. 与 GetRandomDouble 函数配合使用可以实现更复杂的随机数需求
            5. 建议在程序初始化时调用一次，确保随机种子正确初始化
        """
        func = OLAPlugDLLHelper.get_function("GetRandomNumber")
        return func(self.OLAObject, _min, _max)

    def GetRandomDouble(self, _min: float, _max: float) -> float:
        """获取随机浮点数

        Args:
            _min: 随机数的最小值（包含）
            _max: 随机数的最大值（包含）

        Returns:
            返回指定范围内的随机浮点数

        Notes:
            1. 返回的随机数包含最小值和最大值
            2. 每个线程使用独立的随机种子，确保多线程环境下的随机性
            3. 适用于需要高精度随机数的场景，如概率计算、模拟仿真等
            4. 与 GetRandomNumber 函数配合使用可以实现更复杂的随机数需求
            5. 浮点数精度取决于系统实现，通常为双精度（64位）
            6. 建议在程序初始化时调用一次，确保随机种子正确初始化
        """
        func = OLAPlugDLLHelper.get_function("GetRandomDouble")
        return func(self.OLAObject, _min, _max)

    def ExcludePos(self, _json: str, _type: int, x1: int, y1: int, x2: int, y2: int) -> str:
        """排除掉指定区域结果，用于颜色识别结果及图像识别

        Args:
            _json: 识别返回的结果
            _type: 识别类型，可选值:
                1: 颜色识别
                2: 图像识别
            x1: 排除区域左上角的X坐标
            y1: 排除区域左上角的Y坐标
            x2: 排除区域右下角的X坐标
            y2: 排除区域右下角的Y坐标

        Returns:
            返回排除掉指定区域结果的JSON数据

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("ExcludePos")
        return self.PtrToStringUTF8(func(self.OLAObject, _json, _type, x1, y1, x2, y2))

    def FindNearestPos(self, _json: str, _type: int, x: int, y: int) -> str:
        """返回离坐标点最近的结果，用于颜色识别结果及图像识别

        Args:
            _json: 识别结果返回值
            _type: 识别类型，可选值:
                1: 颜色识别
                2: 图像识别
            x: 返回结果的X坐标
            y: 返回结果的Y坐标

        Returns:
            返回最近结果的JSON字符串

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
            2. 返回格式根据 type 不同而不同：
            3. 颜色识别：{"x":10,"y":20}
            4. 图像识别：{"MatchVal":0.85,"MatchState":true,"Index":0,"Angle":45.0,"MatchPoint":{"x":100,"y":200}}
        """
        func = OLAPlugDLLHelper.get_function("FindNearestPos")
        return self.PtrToStringUTF8(func(self.OLAObject, _json, _type, x, y))

    def SortPosDistance(self, _json: str, _type: int, x: int, y: int) -> str:
        """根据坐标点距离排序，用于颜色识别结果及图像识别

        Args:
            _json: 识别结果返回值
            _type: 识别类型，可选值:
                1: 颜色识别
                2: 图像识别
            x: 锚点的X坐标
            y: 锚点的Y坐标

        Returns:
            按顺序排列后的坐标点列表（字符串形式）

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("SortPosDistance")
        return self.PtrToStringUTF8(func(self.OLAObject, _json, _type, x, y))

    def GetDenseRect(self, image: int, width: int, height: int, x1: int = None, y1: int = None, x2: int = None, y2: int = None) -> Tuple[int, int, int, int, int]:
        """查找二值化图片中像素最密集区域，可以配合找色块等功能做二次分析。

        Args:
            image: 图像
            width: 宽度
            height: 高度
            x1: 返回左上角x坐标
            y1: 返回左上角y坐标
            x2: 返回右下角x坐标
            y2: 返回右下角y坐标

        Returns:
            返回元组: (操作结果, 返回左上角x坐标, 返回左上角y坐标, 返回右下角x坐标, 返回右下角y坐标)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetDenseRect")
        return func(self.OLAObject, image, width, height, x1, y1, x2, y2)

    def PathPlanning(self, image: int, startX: int, startY: int, endX: int, endY: int, potentialRadius: float, searchRadius: float) -> List[dict]:
        """寻路算法

        Args:
            image: 二值化图像句柄
            startX: 起点x坐标
            startY: 起点y坐标
            endX: 终点x坐标
            endY: 终点y坐标
            potentialRadius: 潜在半径
            searchRadius: 搜索半径

        Returns:
            返回路径规划结果字符串指针，格式为坐标点数组的JSON字符串

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 确保输入的图像为二值化图像，白色区域为可通行，黑色区域为障碍物
            3. 起点和终点坐标必须在图像范围内
            4. potentialRadius 和 searchRadius 参数影响路径质量和搜索效率
            5. 当 potentialRadius 或 searchRadius 为负数时，只返回JPS寻路数据，不做路径优化
        """
        func = OLAPlugDLLHelper.get_function("PathPlanning")
        result = self.PtrToStringUTF8(func(self.OLAObject, image, startX, startY, endX, endY, potentialRadius, searchRadius))
        if result == "":
            return []
        return json.loads(result)

    def CreateGraph(self, _json: str) -> int:
        """创建图

        Args:
            _json: 图的JSON表示，包含节点和边的信息,传空创建一个空的图对象

        Returns:
            图的指针

        Notes:
            1. 返回的图指针需要调用 DeleteGraph 释放内存
            2. 确保 JSON 格式正确，否则可能导致创建失败
        """
        func = OLAPlugDLLHelper.get_function("CreateGraph")
        return func(self.OLAObject, _json)

    def GetGraph(self, graphPtr: int) -> int:
        """获取图

        Args:
            graphPtr: 图的指针，由CreateGraph接口返回

        Returns:
            返回图的指针，如果图不存在或无效返回0。

        Notes:
            1. 确保传入的 graphPtr 是有效的图指针
            2. 返回的指针用于验证图的有效性，不需要额外释放内存
            3. 在调用其他图操作函数前，建议先调用此函数验证图的有效性
        """
        func = OLAPlugDLLHelper.get_function("GetGraph")
        return func(self.OLAObject, graphPtr)

    def AddEdge(self, graphPtr: int, _from: str, to: str, weight: float, isDirected: bool) -> int:
        """添加边

        Args:
            graphPtr: 图的指针
            _from: 起点
            to: 终点
            weight: 权重
            isDirected: 是否是有向边

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 确保 from 和 to 节点在图中存在
            2. 权重值应为正数，用于最短路径计算
            3. 有向边只允许从 from 到 to 的方向，无向边允许双向通行
            4. 重复添加相同的边可能会覆盖之前的权重设置
        """
        func = OLAPlugDLLHelper.get_function("AddEdge")
        return func(self.OLAObject, graphPtr, _from, to, weight, isDirected)

    def GetShortestPath(self, graphPtr: int, _from: str, to: str) -> str:
        """获取最短路径

        Args:
            graphPtr: 图的指针
            _from: 起点
            to: 终点

        Returns:
            最短路径

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 确保 startNode 节点在图中存在
            3. 如果起点无法到达某些节点，这些节点将不会出现在结果中
            4. 返回的JSON格式包含每个可达节点的距离和路径信息
            5. 算法会考虑边的权重，寻找总权重最小的路径
            6. 适用于需要分析图中所有节点可达性的场景
            7. 对于大型图，计算时间可能较长
        """
        func = OLAPlugDLLHelper.get_function("GetShortestPath")
        return self.PtrToStringUTF8(func(self.OLAObject, graphPtr, _from, to))

    def GetShortestDistance(self, graphPtr: int, _from: str, to: str) -> float:
        """获取最短距离

        Args:
            graphPtr: 图的指针
            _from: 起点
            to: 终点

        Returns:
            最短距离

        Notes:
            1. 距离是路径上所有边权重的总和
            2. 如果两点间不存在路径，函数返回-1
            3. 确保 from 和 to 节点在图中存在
            4. 算法会考虑边的权重，寻找总权重最小的路径
            5. 对于无向图，from到to的距离等于to到from的距离
        """
        func = OLAPlugDLLHelper.get_function("GetShortestDistance")
        return func(self.OLAObject, graphPtr, _from, to)

    def ClearGraph(self, graphPtr: int) -> int:
        """清空图

        Args:
            graphPtr: 图的指针

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 清空操作会删除所有节点和边，但保留图的基本结构
            2. 清空后可以重新添加节点和边
            3. 清空操作不可逆，请谨慎使用
            4. 建议在清空前备份重要的图数据
        """
        func = OLAPlugDLLHelper.get_function("ClearGraph")
        return func(self.OLAObject, graphPtr)

    def DeleteGraph(self, graphPtr: int) -> int:
        """删除图

        Args:
            graphPtr: 图的指针

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 删除操作会释放图对象占用的所有内存资源
            2. 删除后不能再使用该图指针进行任何操作
            3. 建议在程序结束前删除所有创建的图对象
            4. 删除操作不可逆，请确保不再需要该图对象
            5. 删除图对象后，相关的路径计算结果也会失效
        """
        func = OLAPlugDLLHelper.get_function("DeleteGraph")
        return func(self.OLAObject, graphPtr)

    def GetNodeCount(self, graphPtr: int) -> int:
        """获取节点数量.

        Args:
            graphPtr: 图的指针

        Returns:
            节点数量

        Notes:
            1. 节点数量在创建图时确定，添加边不会改变节点数量
            2. 如果图指针无效，可能返回0或错误值
            3. 节点数量反映了图的基本规模
            4. 建议在创建图后立即检查节点数量以验证图的正确性
        """
        func = OLAPlugDLLHelper.get_function("GetNodeCount")
        return func(self.OLAObject, graphPtr)

    def GetEdgeCount(self, graphPtr: int) -> int:
        """获取边数量

        Args:
            graphPtr: 图的指针

        Returns:
            边数量

        Notes:
            1. 边数量会随着 AddEdge 操作而增加
            2. 对于无向图，一条边只计算一次
            3. 如果图指针无效，可能返回0或错误值
            4. 边数量反映了图的连接复杂度
            5. 建议在添加边后检查边数量以验证操作是否成功
        """
        func = OLAPlugDLLHelper.get_function("GetEdgeCount")
        return func(self.OLAObject, graphPtr)

    def GetShortestPathToAllNodes(self, graphPtr: int, startNode: str) -> str:
        """获取最短路径到所有节点

        Args:
            graphPtr: 图的指针
            startNode: 起点

        Returns:
            最短路径到所有节点

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 确保 startNode 节点在图中存在
            3. 如果起点无法到达某些节点，这些节点将不会出现在结果中
            4. 返回的JSON格式包含每个可达节点的距离和路径信息
            5. 算法会考虑边的权重，寻找总权重最小的路径
            6. 适用于需要分析图中所有节点可达性的场景
            7. 对于大型图，计算时间可能较长
        """
        func = OLAPlugDLLHelper.get_function("GetShortestPathToAllNodes")
        return self.PtrToStringUTF8(func(self.OLAObject, graphPtr, startNode))

    def GetMinimumSpanningTree(self, graphPtr: int) -> str:
        """获取最小生成树

        Args:
            graphPtr: 图的指针

        Returns:
            最小生成树

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 最小生成树要求图是连通的
            3. 如果图不连通，函数返回0
            4. 最小生成树包含n-1条边（n为节点数）
            5. 算法会考虑边的权重，选择总权重最小的树
            6. 适用于网络设计、电路设计等需要最小成本连接的场景
            7. 对于无向图，最小生成树是唯一的（当所有边权重不同时）
            8. 返回的JSON包含总权重和所有边的详细信息
        """
        func = OLAPlugDLLHelper.get_function("GetMinimumSpanningTree")
        return self.PtrToStringUTF8(func(self.OLAObject, graphPtr))

    def GetDirectedPathToAllNodes(self, graphPtr: int, startNode: str) -> str:
        """获取有向路径到所有节点.

        Args:
            graphPtr: 图的指针
            startNode: 起点

        Returns:
            有向路径到所有节点

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 确保 startNode 节点在图中存在
            3. 如果起点无法到达某些节点，这些节点将不会出现在结果中
            4. 返回的字符串包含每个可达节点的有向路径和距离信息
            5. 算法会考虑边的权重，寻找总权重最小的有向路径
            6. 适用于需要分析有向图中所有节点可达性的场景
            7. 对于大型有向图，计算时间可能较长
            8. 有向路径考虑了边的方向性，与无向图的最短路径不同
        """
        func = OLAPlugDLLHelper.get_function("GetDirectedPathToAllNodes")
        return self.PtrToStringUTF8(func(self.OLAObject, graphPtr, startNode))

    def GetMinimumArborescence(self, graphPtr: int, root: str) -> str:
        """获取有向图最小生成树.

        Args:
            graphPtr: 图的指针
            root: 根节点

        Returns:
            返回最小生成树信息的字符串指针，格式为JSON；如果无法生成最小树形图返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 最小树形图要求从根节点能够到达所有其他节点
            3. 如果根节点无法到达某些节点，函数返回0
            4. 最小树形图包含n-1条边（n为节点数）
            5. 算法会考虑边的权重，选择总权重最小的有向树
            6. 适用于网络设计、依赖关系分析等需要最小成本有向连接的场景
            7. 对于有向图，最小树形图可能不唯一
        """
        func = OLAPlugDLLHelper.get_function("GetMinimumArborescence")
        return self.PtrToStringUTF8(func(self.OLAObject, graphPtr, root))

    def CreateGraphFromCoordinates(self, _json: str, connectAll: bool, maxDistance: float, useEuclideanDistance: bool) -> int:
        """通过坐标创建图

        Args:
            _json: 坐标节点JSON数据
            connectAll: 是否连接所有节点（默认为true）
            maxDistance: 最大连接距离（默认为无穷大）
            useEuclideanDistance: 是否使用欧几里得距离作为权重（默认为true）

        Returns:
            图的指针，失败返回0

        Notes:
            1. 返回的图指针需要调用 DeleteGraph 释放内存
            2. JSON格式支持两种：
            3. 数组格式: [{"name":"A","x":0,"y":0},{"name":"B","x":1,"y":1}]
            4. 对象格式: {"A":{"x":0,"y":0},"B":{"x":1,"y":1}}
            5. connectAll为true时，所有节点间距离小于maxDistance的会被连接
            6. useEuclideanDistance为true时，边权重为节点间的欧几里得距离
        """
        func = OLAPlugDLLHelper.get_function("CreateGraphFromCoordinates")
        return func(self.OLAObject, _json, connectAll, maxDistance, useEuclideanDistance)

    def AddCoordinateNode(self, graphPtr: int, name: str, x: float, y: float, connectToExisting: bool, maxDistance: float, useEuclideanDistance: bool) -> int:
        """添加坐标节点到现有图

        Args:
            graphPtr: 图的指针
            name: 节点名称
            x: X坐标
            y: Y坐标
            connectToExisting: 是否连接到现有节点（默认为true）
            maxDistance: 最大连接距离（默认为无穷大）
            useEuclideanDistance: 是否使用欧几里得距离作为权重（默认为true）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 确保 graphPtr 是有效的图指针
            2. 如果节点名称已存在，会更新坐标信息
            3. connectToExisting为true时，新节点会连接到距离小于maxDistance的现有节点
        """
        func = OLAPlugDLLHelper.get_function("AddCoordinateNode")
        return func(self.OLAObject, graphPtr, name, x, y, connectToExisting, maxDistance, useEuclideanDistance)

    def GetNodeCoordinates(self, graphPtr: int, name: str) -> str:
        """获取节点的坐标信息

        Args:
            graphPtr: 图的指针
            name: 节点名称

        Returns:
            节点坐标信息的JSON字符串指针，节点不存在返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 返回格式: {"name":"节点名","x":坐标X,"y":坐标Y}
            3. 确保 graphPtr 是有效的图指针
            4. 如果节点不存在，返回0
        """
        func = OLAPlugDLLHelper.get_function("GetNodeCoordinates")
        return self.PtrToStringUTF8(func(self.OLAObject, graphPtr, name))

    def SetNodeConnection(self, graphPtr: int, _from: str, to: str, canConnect: bool, weight: float) -> int:
        """设置节点间的连接关系

        Args:
            graphPtr: 图的指针
            _from: 起始节点名称
            to: 目标节点名称
            canConnect: 是否可以连接（true为可以连接，false为不能连接）
            weight: 连接权重（如果canConnect为true时使用，-1表示使用欧几里得距离）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 确保 graphPtr 是有效的图指针
            2. 节点必须已存在于图中
            3. 设置连接关系会影响路径计算
            4. 如果canConnect为false，会删除对应的边
        """
        func = OLAPlugDLLHelper.get_function("SetNodeConnection")
        return func(self.OLAObject, graphPtr, _from, to, canConnect, weight)

    def GetNodeConnectionStatus(self, graphPtr: int, _from: str, to: str) -> int:
        """获取节点间的连接状态

        Args:
            graphPtr: 图的指针
            _from: 起始节点名称
            to: 目标节点名称

        Returns:
            当前状态
                0: 表示不能连接
                1: 表示可以连接
                -1: 表示节点不存在或图指针无效

        Notes:
            1. 确保 graphPtr 是有效的图指针
        """
        func = OLAPlugDLLHelper.get_function("GetNodeConnectionStatus")
        return func(self.OLAObject, graphPtr, _from, to)

    def AsmCall(self, hwnd: int, asmStr: str, _type: int, baseAddr: int) -> int:
        """执行汇编指令

        Args:
            hwnd: 窗口句柄
            asmStr: 汇编语言字符串,大小写均可以。比如 "mov eax,1" 也支持输入机器码
            _type: 执行类型，可选值:
                0: 在本进程中执行(创建线程),hwnd无效
                1: 在hwnd指定进程内执行(创建远程线程)
                2: 在已注入绑定的目标进程创建线程执行(需排队)
                3: 同模式2,但在hwnd所在线程直接执行
                4: 同模式0,但在当前线程直接执行
                5: 在hwnd指定进程内执行(APC注入)
                6: 直接在hwnd所在线程执行
            baseAddr: 汇编指令所在的地址,如果为0则自动分配内存

        Returns:
            32位进程返回EAX，64位进程返回RAX，执行失败返回0

        Notes:
            1. 使用此函数需要谨慎，错误的汇编指令可能导致程序崩溃
            2. 建议在测试环境中先验证汇编代码的正确性
            3. 不同执行模式适用于不同的应用场景，请根据需求选择合适的type参数
            4. 在目标进程中执行需要相应的权限
            5. 使用APC注入模式(type=5)
            6. 返回值的解释取决于汇编指令的具体内容
            7. 建议在使用前备份重要数据
        """
        func = OLAPlugDLLHelper.get_function("AsmCall")
        return func(self.OLAObject, hwnd, asmStr, _type, baseAddr)

    def Assemble(self, asmStr: str, baseAddr: int, arch: int, mode: int) -> str:
        """把汇编语言字符串转换为机器码并用16进制字符串的形式输出

        Args:
            asmStr: 汇编语言字符串，大小写均可，如"mov eax,1"
            baseAddr: 汇编指令所在的地址，用于计算相对地址；对于绝对地址指令可以设为0
            arch: 架构类型，可选值:
                0: x86
                1: arm
                2: arm64
            mode: 模式，可选值:
                16: 16位
                32: 32位
                64: 64位

        Returns:
            成功返回机器码字符串的指针（16进制格式，如"aa bb cc"）；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 支持的汇编语法取决于底层汇编器
            3. baseAddr 参数用于计算相对地址
            4. 不同架构和模式支持的指令集不同
            5. 建议在使用前验证汇编语法的正确性
            6. 机器码输出格式为16进制字符串，如"aa bb cc"
            7. 此函数适用于代码分析和逆向工程工具开发
        """
        func = OLAPlugDLLHelper.get_function("Assemble")
        return self.PtrToStringUTF8(func(self.OLAObject, asmStr, baseAddr, arch, mode))

    def Disassemble(self, asmCode: str, baseAddr: int, arch: int, mode: int, showType: int) -> str:
        """把指定的机器码转换为汇编语言输出

        Args:
            asmCode: 机器码，形式如"aa bb cc"这样的16进制表示的字符串（空格可忽略）
            baseAddr: 指令所在的地址，用于计算相对地址和符号解析
            arch: 架构类型，可选值:
                0: x86
                1: arm
                2: arm64
            mode: 模式，可选值:
                16: 16位
                32: 32位
                64: 64位
            showType: 显示类型，可选值:
                0: 显示详细汇编信息（包括地址、机器码、汇编指令）
                1: 只显示机器码

        Returns:
            成功返回汇编语言字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 如果有多条指令，则每条指令以字符"|"连接
            3. showType=0时显示详细汇编信息，包括地址、机器码、汇编指令
            4. showType=1时只显示机器码
            5. 机器码输入格式为16进制字符串，空格可以忽略
            6. 不同架构和模式支持的指令集不同
            7. baseAddr 参数用于计算相对地址和符号解析
            8. 此函数适用于逆向工程、代码分析和调试工具开发
        """
        func = OLAPlugDLLHelper.get_function("Disassemble")
        return self.PtrToStringUTF8(func(self.OLAObject, asmCode, baseAddr, arch, mode, showType))

    def Login(self, userCode: str, softCode: str, featureList: str, softVersion: str, dealerCode: str) -> str:
        """登录。

        Args:
            userCode: (字符串): 用户码。
            softCode: (字符串): 软件码。
            featureList: (字符串): 功能列表。为空只使用授权系统，不注册插件
            softVersion: (字符串): 软件版本。
            dealerCode: (字符串): 经销商码。

        Returns:
            JSON字符串: 登录结果。

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Login")
        return self.PtrToStringUTF8(func(userCode, softCode, featureList, softVersion, dealerCode))

    def Activate(self, userCode: str, softCode: str, softVersion: str, dealerCode: str, licenseKey: str) -> str:
        """激活。

        Args:
            userCode: (字符串): 用户码。
            softCode: (字符串): 软件码。
            softVersion: (字符串): 软件版本。
            dealerCode: (字符串): 经销商码。
            licenseKey: (字符串): 激活码。

        Returns:
            JSON字符串: 激活结果。

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Activate")
        return self.PtrToStringUTF8(func(userCode, softCode, softVersion, dealerCode, licenseKey))

    def DmaAddDevice(self, vmId: int) -> int:
        """添加VMware DMA设备(默认连接字符串)

        Args:
            vmId: VMware虚拟机ID

        Returns:
            成功返回设备ID(>=0), 失败返回-1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaAddDevice")
        return func(self.OLAObject, vmId)

    def DmaAddDeviceEx(self, connectionString: str) -> int:
        """添加自定义DMA设备

        Args:
            connectionString: 设备连接字符串(如"vmware://rw=1,id=1", "fpga://algo=4"等)

        Returns:
            成功返回设备ID(>=0), 失败返回-1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaAddDeviceEx")
        return func(self.OLAObject, connectionString)

    def DmaRemoveDevice(self, deviceId: int) -> int:
        """删除DMA设备

        Args:
            deviceId: 设备ID

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaRemoveDevice")
        return func(self.OLAObject, deviceId)

    def DmaGetPidFromName(self, deviceId: int, processName: str) -> int:
        """根据进程名获取PID

        Args:
            deviceId: 设备ID
            processName: 进程名(支持部分匹配)

        Returns:
            成功返回PID, 失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaGetPidFromName")
        return func(self.OLAObject, deviceId, processName)

    def DmaGetPidList(self, deviceId: int) -> str:
        """获取所有进程PID列表

        Args:
            deviceId: 设备ID

        Returns:
            返回二进制字符串的指针，数据格式:"pid1|pid2|pid3...",失败返回空字符串

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaGetPidList")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId))

    def DmaGetProcessInfo(self, deviceId: int, pid: int) -> str:
        """获取进程基本信息

        Args:
            deviceId: 设备ID
            pid: 进程PID

        Returns:
            返回二进制字符串的指针，数据格式:"进程名,镜像基址,镜像大小",失败返回空字符串

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaGetProcessInfo")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid))

    def DmaGetModuleBase(self, deviceId: int, pid: int, moduleName: str) -> int:
        """获取模块基址

        Args:
            deviceId: 设备ID
            pid: 进程PID
            moduleName: 模块名(空字符串表示主模块)

        Returns:
            成功返回模块基址, 失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaGetModuleBase")
        return func(self.OLAObject, deviceId, pid, moduleName)

    def DmaGetModuleSize(self, deviceId: int, pid: int, moduleName: str) -> int:
        """获取模块大小

        Args:
            deviceId: 设备ID
            pid: 进程PID
            moduleName: 模块名

        Returns:
            成功返回模块大小, 失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaGetModuleSize")
        return func(self.OLAObject, deviceId, pid, moduleName)

    def DmaGetProcAddress(self, deviceId: int, pid: int, moduleName: str, functionName: str) -> int:
        """获取模块导出函数地址

        Args:
            deviceId: 设备ID
            pid: 进程PID
            moduleName: 模块名
            functionName: 函数名

        Returns:
            成功返回函数地址, 失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaGetProcAddress")
        return func(self.OLAObject, deviceId, pid, moduleName, functionName)

    def DmaScatterCreate(self, deviceId: int, pid: int) -> int:
        """创建散列读句柄

        Args:
            deviceId: 设备ID
            pid: 进程PID

        Returns:
            成功返回散列句柄, 失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaScatterCreate")
        return func(self.OLAObject, deviceId, pid)

    def DmaScatterPrepare(self, scatterHandle: int, address: int, size: int) -> int:
        """准备散列读地址

        Args:
            scatterHandle: 散列句柄
            address: 地址
            size: 大小

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaScatterPrepare")
        return func(self.OLAObject, scatterHandle, address, size)

    def DmaScatterExecute(self, scatterHandle: int) -> int:
        """执行散列读

        Args:
            scatterHandle: 散列句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaScatterExecute")
        return func(self.OLAObject, scatterHandle)

    def DmaScatterRead(self, scatterHandle: int, address: int, buffer: int, size: int) -> int:
        """从散列读结果中读取数据

        Args:
            scatterHandle: 散列句柄
            address: 地址
            buffer: 输出缓冲区地址
            size: 读取大小

        Returns:
            实际读取的字节数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaScatterRead")
        return func(self.OLAObject, scatterHandle, address, buffer, size)

    def DmaScatterClear(self, scatterHandle: int) -> int:
        """清除散列读准备的数据

        Args:
            scatterHandle: 散列句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaScatterClear")
        return func(self.OLAObject, scatterHandle)

    def DmaScatterClose(self, scatterHandle: int) -> int:
        """关闭散列读句柄

        Args:
            scatterHandle: 散列句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaScatterClose")
        return func(self.OLAObject, scatterHandle)

    def DmaFindData(self, deviceId: int, pid: int, addr_range: str, data: str) -> str:
        """

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            data: 要搜索的二进制数据,支持CE数据格式 比如"00 01 23 45 * ?? ?b c? * f1"等.

        Returns:
            返回二进制字符串的指针

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindData")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, data))

    def DmaFindDataEx(self, deviceId: int, pid: int, addr_range: str, data: str, step: int, multi_thread: int, mode: int) -> str:
        """

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            data: 要搜索的二进制数据,支持CE数据格式 比如"00 01 23 45 * ?? ?b c? * f1"等.
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindDataEx")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, data, step, multi_thread, mode))

    def DmaFindDouble(self, deviceId: int, pid: int, addr_range: str, double_value_min: float, double_value_max: float) -> str:
        """通过DMA搜索指定范围内的双精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            double_value_min: 最小值
            double_value_max: 最大值

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindDouble")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, double_value_min, double_value_max))

    def DmaFindDoubleEx(self, deviceId: int, pid: int, addr_range: str, double_value_min: float, double_value_max: float, step: int, multi_thread: int, mode: int) -> str:
        """通过DMA搜索指定范围内的双精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            double_value_min: 最小值
            double_value_max: 最大值
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindDoubleEx")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, double_value_min, double_value_max, step, multi_thread, mode))

    def DmaFindFloat(self, deviceId: int, pid: int, addr_range: str, float_value_min: float, float_value_max: float) -> str:
        """通过DMA搜索指定范围内的单精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            float_value_min: 最小值
            float_value_max: 最大值

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindFloat")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, float_value_min, float_value_max))

    def DmaFindFloatEx(self, deviceId: int, pid: int, addr_range: str, float_value_min: float, float_value_max: float, step: int, multi_thread: int, mode: int) -> str:
        """通过DMA搜索指定范围内的单精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            float_value_min: 最小值
            float_value_max: 最大值
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindFloatEx")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, float_value_min, float_value_max, step, multi_thread, mode))

    def DmaFindInt(self, deviceId: int, pid: int, addr_range: str, int_value_min: int, int_value_max: int, _type: int) -> str:
        """通过DMA搜索指定范围内的整数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            int_value_min: 最小值
            int_value_max: 最大值
            _type: 搜索的整数类型,取值如下，可选值:
                0: 32位
                1: 16位
                2: 8位
                3: 64位

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindInt")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, int_value_min, int_value_max, _type))

    def DmaFindIntEx(self, deviceId: int, pid: int, addr_range: str, int_value_min: int, int_value_max: int, _type: int, step: int, multi_thread: int, mode: int) -> str:
        """通过DMA搜索指定范围内的整数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            int_value_min: 最小值
            int_value_max: 最大值
            _type: 搜索的整数类型,取值如下，可选值:
                0: 32位
                1: 16位
                2: 8位
                3: 64位
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindIntEx")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, int_value_min, int_value_max, _type, step, multi_thread, mode))

    def DmaFindString(self, deviceId: int, pid: int, addr_range: str, string_value: str, _type: int) -> str:
        """通过DMA搜索指定范围内的字符串

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            string_value: 要搜索的字符串
            _type: 类型，可选值:
                0: 返回Ascii表达的字符串
                1: 返回Unicode表达的字符串
                2: 返回UTF8表达的字符串

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindString")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, string_value, _type))

    def DmaFindStringEx(self, deviceId: int, pid: int, addr_range: str, string_value: str, _type: int, step: int, multi_thread: int, mode: int) -> str:
        """通过DMA搜索指定范围内的字符串

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr_range: 地址范围
            string_value: 要搜索的字符串
            _type: 类型，可选值:
                0: 返回Ascii表达的字符串
                1: 返回Unicode表达的字符串
                2: 返回UTF8表达的字符串
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3...|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaFindStringEx")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr_range, string_value, _type, step, multi_thread, mode))

    def DmaReadData(self, deviceId: int, pid: int, addr: str, _len: int) -> str:
        """通过DMA读取指定地址的数据

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _len: 长度

        Returns:
            返回二进制字符串的指针，数据格式:读取到的数值,以16进制表示的字符串 每个字节以空格相隔比如"12 34 56 78 ab cd ef"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaReadData")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr, _len))

    def DmaReadDataAddr(self, deviceId: int, pid: int, addr: int, _len: int) -> str:
        """通过DMA读取指定地址的数据

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            _len: 长度

        Returns:
            返回二进制字符串的指针，数据格式:读取到的数值,以16进制表示的字符串 每个字节以空格相隔比如"12 34 56 78 ab cd ef"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaReadDataAddr")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr, _len))

    def DmaReadDataAddrToBin(self, deviceId: int, pid: int, addr: int, _len: int) -> int:
        """通过DMA读取指定地址的数据到本地缓冲区

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            _len: 长度

        Returns:
            读取到的数据字符串指针. 返回0表示读取失败.

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadDataAddrToBin")
        return func(self.OLAObject, deviceId, pid, addr, _len)

    def DmaReadDataToBin(self, deviceId: int, pid: int, addr: str, _len: int) -> int:
        """通过DMA读取指定地址的数据到本地缓冲区

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _len: 长度

        Returns:
            读取到的内存地址

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadDataToBin")
        return func(self.OLAObject, deviceId, pid, addr, _len)

    def DmaReadDouble(self, deviceId: int, pid: int, addr: str) -> float:
        """通过DMA读取指定地址的双精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10

        Returns:
            读取到的双精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadDouble")
        return func(self.OLAObject, deviceId, pid, addr)

    def DmaReadDoubleAddr(self, deviceId: int, pid: int, addr: int) -> float:
        """通过DMA读取指定地址的双精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址

        Returns:
            读取到的双精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadDoubleAddr")
        return func(self.OLAObject, deviceId, pid, addr)

    def DmaReadFloat(self, deviceId: int, pid: int, addr: str) -> float:
        """通过DMA读取指定地址的单精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10

        Returns:
            读取到的单精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadFloat")
        return func(self.OLAObject, deviceId, pid, addr)

    def DmaReadFloatAddr(self, deviceId: int, pid: int, addr: int) -> float:
        """通过DMA读取指定地址的单精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址

        Returns:
            读取到的单精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadFloatAddr")
        return func(self.OLAObject, deviceId, pid, addr)

    def DmaReadInt(self, deviceId: int, pid: int, addr: str, _type: int) -> int:
        """通过DMA读取指定地址的整数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号

        Returns:
            读取到的整数值64位

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadInt")
        return func(self.OLAObject, deviceId, pid, addr, _type)

    def DmaReadIntAddr(self, deviceId: int, pid: int, addr: int, _type: int) -> int:
        """通过DMA读取指定地址的整数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号

        Returns:
            读取到的整数值64位

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaReadIntAddr")
        return func(self.OLAObject, deviceId, pid, addr, _type)

    def DmaReadString(self, deviceId: int, pid: int, addr: str, _type: int, _len: int) -> str:
        """通过DMA读取指定地址的字符串

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 字符串类型,取值如下，可选值:
                0: GBK字符串
                1: Unicode字符串
                2: UTF8字符串
            _len: 需要读取的字节数目.如果为0，则自动判定字符串长度.

        Returns:
            返回二进制字符串的指针，数据格式:读取到的字符串,以UTF-8编码

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaReadString")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr, _type, _len))

    def DmaReadStringAddr(self, deviceId: int, pid: int, addr: int, _type: int, _len: int) -> str:
        """通过DMA读取指定地址的字符串

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            _type: 字符串类型,取值如下，可选值:
                0: GBK字符串
                1: Unicode字符串
                2: UTF8字符串
            _len: 需要读取的字节数目.如果为0，则自动判定字符串长度.

        Returns:
            返回二进制字符串的指针，数据格式:读取到的字符串,以UTF-8编码

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DmaReadStringAddr")
        return self.PtrToStringUTF8(func(self.OLAObject, deviceId, pid, addr, _type, _len))

    def DmaWriteData(self, deviceId: int, pid: int, addr: str, data: str) -> int:
        """通过DMA写入指定地址的数据

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            data: 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteData")
        return func(self.OLAObject, deviceId, pid, addr, data)

    def DmaWriteDataFromBin(self, deviceId: int, pid: int, addr: str, data: int, _len: int) -> int:
        """通过DMA写入指定地址的数据(源为本地缓冲区)

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            data: 字符串数据地址
            _len: 数据长度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteDataFromBin")
        return func(self.OLAObject, deviceId, pid, addr, data, _len)

    def DmaWriteDataAddr(self, deviceId: int, pid: int, addr: int, data: str) -> int:
        """通过DMA写入指定地址的数据

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            data: 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteDataAddr")
        return func(self.OLAObject, deviceId, pid, addr, data)

    def DmaWriteDataAddrFromBin(self, deviceId: int, pid: int, addr: int, data: int, _len: int) -> int:
        """通过DMA写入指定地址的数据(源为本地缓冲区)

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            data: 数据 二进制数据地址
            _len: 数据长度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteDataAddrFromBin")
        return func(self.OLAObject, deviceId, pid, addr, data, _len)

    def DmaWriteDouble(self, deviceId: int, pid: int, addr: str, double_value: float) -> int:
        """通过DMA写入指定地址的双精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            double_value: 双精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteDouble")
        return func(self.OLAObject, deviceId, pid, addr, double_value)

    def DmaWriteDoubleAddr(self, deviceId: int, pid: int, addr: int, double_value: float) -> int:
        """通过DMA写入指定地址的双精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            double_value: 双精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteDoubleAddr")
        return func(self.OLAObject, deviceId, pid, addr, double_value)

    def DmaWriteFloat(self, deviceId: int, pid: int, addr: str, float_value: float) -> int:
        """通过DMA写入指定地址的单精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            float_value: 单精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteFloat")
        return func(self.OLAObject, deviceId, pid, addr, float_value)

    def DmaWriteFloatAddr(self, deviceId: int, pid: int, addr: int, float_value: float) -> int:
        """通过DMA写入指定地址的单精度浮点数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            float_value: 单精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteFloatAddr")
        return func(self.OLAObject, deviceId, pid, addr, float_value)

    def DmaWriteInt(self, deviceId: int, pid: int, addr: str, _type: int, value: int) -> int:
        """通过DMA写入指定地址的整数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号
            value: 要写入的整数值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteInt")
        return func(self.OLAObject, deviceId, pid, addr, _type, value)

    def DmaWriteIntAddr(self, deviceId: int, pid: int, addr: int, _type: int, value: int) -> int:
        """通过DMA写入指定地址的整数

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号
            value: 要写入的整数值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteIntAddr")
        return func(self.OLAObject, deviceId, pid, addr, _type, value)

    def DmaWriteString(self, deviceId: int, pid: int, addr: str, _type: int, value: str) -> int:
        """通过DMA写入指定地址的字符串

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 字符串类型,取值如下，可选值:
                0: Ascii字符串
                1: Unicode字符串
                2: UTF8字符串
            value: 要写入的字符串

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteString")
        return func(self.OLAObject, deviceId, pid, addr, _type, value)

    def DmaWriteStringAddr(self, deviceId: int, pid: int, addr: int, _type: int, value: str) -> int:
        """通过DMA写入指定地址的字符串

        Args:
            deviceId: 设备ID
            pid: 进程PID
            addr: 地址
            _type: 字符串类型,取值如下，可选值:
                0: Ascii字符串
                1: Unicode字符串
                2: UTF8字符串
            value: 要写入的字符串

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DmaWriteStringAddr")
        return func(self.OLAObject, deviceId, pid, addr, _type, value)

    def DrawGuiCleanup(self) -> int:
        """释放绘制系统资源并清理所有对象

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiCleanup")
        return func(self.OLAObject)

    def DrawGuiSetGuiActive(self, active: int) -> int:
        """启用或禁用绘制系统

        Args:
            active: 1 启用，0 禁用

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetGuiActive")
        return func(self.OLAObject, active)

    def DrawGuiIsGuiActive(self) -> int:
        """查询绘制系统是否启用

        Returns:
            状态，0 未启用，1 已启用

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiIsGuiActive")
        return func(self.OLAObject)

    def DrawGuiSetGuiClickThrough(self, enabled: int) -> int:
        """设置绘制窗口是否可穿透点击

        Args:
            enabled: 1 可穿透，0 不可穿透

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetGuiClickThrough")
        return func(self.OLAObject, enabled)

    def DrawGuiIsGuiClickThrough(self) -> int:
        """查询绘制窗口是否设置为可穿透

        Returns:
            状态
                0: 否
                1: 是

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiIsGuiClickThrough")
        return func(self.OLAObject)

    def DrawGuiRectangle(self, x: int, y: int, width: int, height: int, mode: int, lineThickness: float) -> int:
        """创建矩形对象

        Args:
            x: 左上角X
            y: 左上角Y
            width: 宽度
            height: 高度
            mode: 绘制模式，见DrawMode
            lineThickness: 线宽（像素），对描边模式有效

        Returns:
            对象句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiRectangle")
        return func(self.OLAObject, x, y, width, height, mode, lineThickness)

    def DrawGuiCircle(self, x: int, y: int, radius: int, mode: int, lineThickness: float) -> int:
        """创建圆形对象

        Args:
            x: 圆心X
            y: 圆心Y
            radius: 半径
            mode: 绘制模式，见DrawMode
            lineThickness: 线宽（像素），对描边模式有效

        Returns:
            对象句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiCircle")
        return func(self.OLAObject, x, y, radius, mode, lineThickness)

    def DrawGuiLine(self, x1: int, y1: int, x2: int, y2: int, lineThickness: float) -> int:
        """创建直线对象

        Args:
            x1: 起点X
            y1: 起点Y
            x2: 终点X
            y2: 终点Y
            lineThickness: 线宽（像素）

        Returns:
            对象句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiLine")
        return func(self.OLAObject, x1, y1, x2, y2, lineThickness)

    def DrawGuiText(self, text: str, x: int, y: int, fontPath: str, fontSize: int, align: int) -> int:
        """创建文本对象

        Args:
            text: 文本内容
            x: 左上角X
            y: 左上角Y
            fontPath: 字体文件路径（ttf/otf）
            fontSize: 字号（像素）
            align: 对齐方式，见TextAlign

        Returns:
            对象句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiText")
        return func(self.OLAObject, text, x, y, fontPath, fontSize, align)

    def DrawGuiImage(self, imagePath: str, x: int, y: int) -> int:
        """创建图片对象

        Args:
            imagePath: 图片文件路径
            x: 左上角X
            y: 左上角Y

        Returns:
            对象句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiImage")
        return func(self.OLAObject, imagePath, x, y)

    def DrawGuiImagePtr(self, imagePtr: int, x: int, y: int) -> int:
        """创建图片对象

        Args:
            imagePtr: 图片指针
            x: 左上角X
            y: 左上角Y

        Returns:
            对象句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiImagePtr")
        return func(self.OLAObject, imagePtr, x, y)

    def DrawGuiWindow(self, title: str, x: int, y: int, width: int, height: int, style: int) -> int:
        """创建窗口对象

        Args:
            title: 标题文本
            x: 左上角X
            y: 左上角Y
            width: 宽度
            height: 高度
            style: 窗口样式，见WindowStyle

        Returns:
            窗口句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiWindow")
        return func(self.OLAObject, title, x, y, width, height, style)

    def DrawGuiPanel(self, parentHandle: int, x: int, y: int, width: int, height: int) -> int:
        """创建面板对象

        Args:
            parentHandle: 父对象句柄（窗口/面板）
            x: 左上角X
            y: 左上角Y
            width: 宽度
            height: 高度

        Returns:
            面板句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiPanel")
        return func(self.OLAObject, parentHandle, x, y, width, height)

    def DrawGuiButton(self, parentHandle: int, text: str, x: int, y: int, width: int, height: int) -> int:
        """创建按钮对象

        Args:
            parentHandle: 父对象句柄（窗口/面板）
            text: 按钮文本
            x: 左上角X
            y: 左上角Y
            width: 宽度
            height: 高度

        Returns:
            按钮句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiButton")
        return func(self.OLAObject, parentHandle, text, x, y, width, height)

    def DrawGuiSetPosition(self, handle: int, x: int, y: int) -> int:
        """设置对象位置

        Args:
            handle: 对象句柄
            x: 左上角X
            y: 左上角Y

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetPosition")
        return func(self.OLAObject, handle, x, y)

    def DrawGuiSetSize(self, handle: int, width: int, height: int) -> int:
        """设置对象尺寸

        Args:
            handle: 对象句柄
            width: 宽度
            height: 高度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetSize")
        return func(self.OLAObject, handle, width, height)

    def DrawGuiSetColor(self, handle: int, r: int, g: int, b: int, a: int) -> int:
        """设置对象颜色（RGBA）

        Args:
            handle: 对象句柄
            r: 红色分量（0-255）
            g: 绿色分量（0-255）
            b: 蓝色分量（0-255）
            a: 透明度（0-255）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetColor")
        return func(self.OLAObject, handle, r, g, b, a)

    def DrawGuiSetAlpha(self, handle: int, alpha: int) -> int:
        """设置对象整体透明度

        Args:
            handle: 对象句柄
            alpha: 透明度（0-255）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetAlpha")
        return func(self.OLAObject, handle, alpha)

    def DrawGuiSetDrawMode(self, handle: int, mode: int) -> int:
        """设置绘制模式

        Args:
            handle: 对象句柄
            mode: 绘制模式，见DrawMode

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetDrawMode")
        return func(self.OLAObject, handle, mode)

    def DrawGuiSetLineThickness(self, handle: int, thickness: float) -> int:
        """设置线宽

        Args:
            handle: 对象句柄
            thickness: 线宽（像素）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetLineThickness")
        return func(self.OLAObject, handle, thickness)

    def DrawGuiSetFont(self, handle: int, fontPath: str, fontSize: int) -> int:
        """设置文本字体

        Args:
            handle: 文本对象句柄
            fontPath: 字体文件路径（ttf/otf）
            fontSize: 字号（像素）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetFont")
        return func(self.OLAObject, handle, fontPath, fontSize)

    def DrawGuiSetTextAlign(self, handle: int, align: int) -> int:
        """设置文本对齐

        Args:
            handle: 文本对象句柄
            align: 对齐方式，见TextAlign

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetTextAlign")
        return func(self.OLAObject, handle, align)

    def DrawGuiSetText(self, handle: int, text: str) -> int:
        """设置文本内容

        Args:
            handle: 文本对象句柄
            text: 文本内容

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetText")
        return func(self.OLAObject, handle, text)

    def DrawGuiSetWindowTitle(self, handle: int, title: str) -> int:
        """设置窗口标题

        Args:
            handle: 窗口句柄
            title: 标题文本

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetWindowTitle")
        return func(self.OLAObject, handle, title)

    def DrawGuiSetWindowStyle(self, handle: int, style: int) -> int:
        """设置窗口样式

        Args:
            handle: 窗口句柄
            style: 窗口样式，见WindowStyle

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetWindowStyle")
        return func(self.OLAObject, handle, style)

    def DrawGuiSetWindowTopMost(self, handle: int, topMost: int) -> int:
        """设置窗口是否置顶

        Args:
            handle: 窗口句柄
            topMost: 1 置顶，0 取消置顶

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetWindowTopMost")
        return func(self.OLAObject, handle, topMost)

    def DrawGuiSetWindowTransparency(self, handle: int, alpha: int) -> int:
        """设置窗口透明度

        Args:
            handle: 窗口句柄
            alpha: 透明度（0-255）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetWindowTransparency")
        return func(self.OLAObject, handle, alpha)

    def DrawGuiDeleteObject(self, handle: int) -> int:
        """删除对象

        Args:
            handle: 对象句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiDeleteObject")
        return func(self.OLAObject, handle)

    def DrawGuiClearAll(self) -> int:
        """清空所有对象

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiClearAll")
        return func(self.OLAObject)

    def DrawGuiSetVisible(self, handle: int, visible: int) -> int:
        """设置对象可见性

        Args:
            handle: 对象句柄
            visible: 1 可见，0 隐藏

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetVisible")
        return func(self.OLAObject, handle, visible)

    def DrawGuiSetZOrder(self, handle: int, zOrder: int) -> int:
        """设置对象Z序（绘制顺序）

        Args:
            handle: 对象句柄
            zOrder: Z序值，数值越大越靠前

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetZOrder")
        return func(self.OLAObject, handle, zOrder)

    def DrawGuiSetParent(self, handle: int, parentHandle: int) -> int:
        """设置对象父子关系

        Args:
            handle: 子对象句柄
            parentHandle: 父对象句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetParent")
        return func(self.OLAObject, handle, parentHandle)

    def DrawGuiSetButtonCallback(self, handle: int, callback: Callable[[int], None]) -> int:
        """设置按钮点击回调

        Args:
            handle: 按钮对象句柄
            callback: 按钮回调函数指针

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetButtonCallback")
        return func(self.OLAObject, handle, callback)

    def DrawGuiSetMouseCallback(self, handle: int, callback: Callable[[int, int, int, int], None]) -> int:
        """设置鼠标事件回调

        Args:
            handle: 目标对象句柄
            callback: 鼠标回调函数指针

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiSetMouseCallback")
        return func(self.OLAObject, handle, callback)

    def DrawGuiGetDrawObjectType(self, handle: int) -> int:
        """获取对象类型

        Args:
            handle: 对象句柄

        Returns:
            对象类型，见DrawType

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiGetDrawObjectType")
        return func(self.OLAObject, handle)

    def DrawGuiGetPosition(self, handle: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """获取对象位置

        Args:
            handle: 对象句柄
            x: 返回左上角X（输出）
            y: 返回左上角Y（输出）

        Returns:
            返回元组: (操作结果, 返回左上角X（输出）, 返回左上角Y（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiGetPosition")
        return func(self.OLAObject, handle, x, y)

    def DrawGuiGetSize(self, handle: int, width: int = None, height: int = None) -> Tuple[int, int, int]:
        """获取对象尺寸

        Args:
            handle: 对象句柄
            width: 返回宽度（输出）
            height: 返回高度（输出）

        Returns:
            返回元组: (操作结果, 返回宽度（输出）, 返回高度（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiGetSize")
        return func(self.OLAObject, handle, width, height)

    def DrawGuiIsPointInObject(self, handle: int, x: int, y: int) -> int:
        """判断坐标点是否在对象内

        Args:
            handle: 对象句柄
            x: X坐标
            y: Y坐标

        Returns:
            结果enum 0 否enum 1 是

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawGuiIsPointInObject")
        return func(self.OLAObject, handle, x, y)

    def SetMemoryMode(self, mode: int) -> int:
        """设置内存读写模式

        Args:
            mode: 内存模式，可选值:
                0: 远程模式
                1: 本地模式(需要DLL注入)
                2: 驱动API方式读写内存
                3: 驱动MDL方式读写内存

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetMemoryMode")
        return func(self.OLAObject, mode)

    def ExportDriver(self, driver_path: str, _type: int) -> int:
        """导出驱动

        Args:
            driver_path: 驱动路径
            _type: 驱动类型

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ExportDriver")
        return func(self.OLAObject, driver_path, _type)

    def LoadDriver(self, driver_name: str, driver_path: str) -> int:
        """加载驱动

        Args:
            driver_name: 驱动名称,为空则初始化欧拉驱动
            driver_path: 驱动路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LoadDriver")
        return func(self.OLAObject, driver_name, driver_path)

    def UnloadDriver(self, driver_name: str) -> int:
        """卸载驱动

        Args:
            driver_name: 驱动名称

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnloadDriver")
        return func(self.OLAObject, driver_name)

    def DriverTest(self) -> int:
        """测试驱动是否正常加载

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DriverTest")
        return func(self.OLAObject)

    def LoadPdb(self) -> int:
        """加载PDB文件,驱动加载失败时可以尝试加载PDB文件

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LoadPdb")
        return func(self.OLAObject)

    def GetPdbDownloadUrls(self) -> str:
        """获取PDB文件下载URL和保存路径列表

        Returns:
            PDB文件下载URL|保存路径列表

        Notes:
            1. 返回的URL列表格式为： url1|path1\nurl2|path2\nurl3|path3\n...
            2. 需要调用 FreeStringPtr 释放返回的URL列表
        """
        func = OLAPlugDLLHelper.get_function("GetPdbDownloadUrls")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def HideProcess(self, pid: int, enable: int) -> int:
        """隐藏进程

        Args:
            pid: 进程ID
            enable: 是否隐藏

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("HideProcess")
        return func(self.OLAObject, pid, enable)

    def ProtectProcess(self, pid: int, enable: int) -> int:
        """保护进程

        Args:
            pid: 进程ID
            enable: 是否保护

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectProcess")
        return func(self.OLAObject, pid, enable)

    def ProtectProcess2(self, pid: int, enable: int) -> int:
        """保护进程模式2

        Args:
            pid: 进程ID
            enable: 是否保护

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectProcess2")
        return func(self.OLAObject, pid, enable)

    def AddProtectPID(self, pid: int, mode: int, allow_pid: int) -> int:
        """添加保护进程

        Args:
            pid: 进程ID
            mode: 保护模式
            allow_pid: 允许的进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("AddProtectPID")
        return func(self.OLAObject, pid, mode, allow_pid)

    def RemoveProtectPID(self, pid: int) -> int:
        """删除保护进程

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RemoveProtectPID")
        return func(self.OLAObject, pid)

    def AddAllowPID(self, pid: int) -> int:
        """添加允许进程

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("AddAllowPID")
        return func(self.OLAObject, pid)

    def RemoveAllowPID(self, pid: int) -> int:
        """删除允许进程

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RemoveAllowPID")
        return func(self.OLAObject, pid)

    def FakeProcess(self, pid: int, fake_pid: int) -> int:
        """伪装进程

        Args:
            pid: 进程ID
            fake_pid: 伪装的目标进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FakeProcess")
        return func(self.OLAObject, pid, fake_pid)

    def ProtectWindow(self, hwnd: int, flag: int) -> int:
        """保护窗口,防止截屏

        Args:
            hwnd: 窗口句柄
            flag: 保护标志 0还原 1黑屏 2透明

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectWindow")
        return func(self.OLAObject, hwnd, flag)

    def KeOpenProcess(self, pid: int, process_handle: int = None) -> Tuple[int, int]:
        """打开进程

        Args:
            pid: 进程ID
            process_handle: 进程句柄

        Returns:
            返回元组: (1成功 其他失败, 进程句柄)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeOpenProcess")
        return func(self.OLAObject, pid, process_handle)

    def KeOpenThread(self, thread_id: int, thread_handle: int = None) -> Tuple[int, int]:
        """打开线程

        Args:
            thread_id: 线程ID
            thread_handle: 线程句柄

        Returns:
            返回元组: (1成功 其他失败, 线程句柄)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeOpenThread")
        return func(self.OLAObject, thread_id, thread_handle)

    def StartSecurityGuard(self) -> int:
        """启动安全守护

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("StartSecurityGuard")
        return func(self.OLAObject)

    def ProtectFileTestDriver(self) -> int:
        """测试文件保护驱动通信是否正常

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileTestDriver")
        return func(self.OLAObject)

    def ProtectFileEnableDriver(self) -> int:
        """启用文件保护驱动

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileEnableDriver")
        return func(self.OLAObject)

    def ProtectFileDisableDriver(self) -> int:
        """禁用文件保护驱动

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileDisableDriver")
        return func(self.OLAObject)

    def ProtectFileStartFilter(self) -> int:
        """启动文件系统过滤器

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileStartFilter")
        return func(self.OLAObject)

    def ProtectFileStopFilter(self) -> int:
        """停止文件系统过滤器

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileStopFilter")
        return func(self.OLAObject)

    def ProtectFileAddProtectedPath(self, path: str, mode: int, is_directory: int) -> int:
        """添加受保护路径

        Args:
            path: 要保护的文件或文件夹路径
            mode: 保护模式：0-全部拦截, 1-允许白名单, 2-拦截黑名单
            is_directory: 是否为目录 (1-目录, 0-文件)

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileAddProtectedPath")
        return func(self.OLAObject, path, mode, is_directory)

    def ProtectFileRemoveProtectedPath(self, path: str) -> int:
        """移除受保护路径

        Args:
            path: 要移除保护的文件或文件夹路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileRemoveProtectedPath")
        return func(self.OLAObject, path)

    def ProtectFileClearProtectedPaths(self) -> int:
        """清空所有受保护路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileClearProtectedPaths")
        return func(self.OLAObject)

    def ProtectFileQueryProtectedPath(self, path: str, mode: int = None) -> Tuple[int, int]:
        """查询路径是否受保护

        Args:
            path: 要查询的文件或文件夹路径
            mode: 输出参数，用于接收该路径的保护模式（可为NULL）

        Returns:
            返回元组: (1-路径受保护, 0-路径未受保护或查询失败, 输出参数，用于接收该路径的保护模式（可为NULL）)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileQueryProtectedPath")
        return func(self.OLAObject, path, mode)

    def ProtectFileAddWhitelist(self, pid: int) -> int:
        """添加进程到白名单

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileAddWhitelist")
        return func(self.OLAObject, pid)

    def ProtectFileRemoveWhitelist(self, pid: int) -> int:
        """从白名单移除进程

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileRemoveWhitelist")
        return func(self.OLAObject, pid)

    def ProtectFileClearWhitelist(self) -> int:
        """清空白名单

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileClearWhitelist")
        return func(self.OLAObject)

    def ProtectFileQueryWhitelist(self, pid: int) -> int:
        """查询进程是否在白名单中

        Args:
            pid: 进程ID

        Returns:
            1-在白名单中, 0-不在白名单中或查询失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileQueryWhitelist")
        return func(self.OLAObject, pid)

    def ProtectFileAddBlacklist(self, pid: int) -> int:
        """添加进程到黑名单

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileAddBlacklist")
        return func(self.OLAObject, pid)

    def ProtectFileRemoveBlacklist(self, pid: int) -> int:
        """从黑名单移除进程

        Args:
            pid: 进程ID

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileRemoveBlacklist")
        return func(self.OLAObject, pid)

    def ProtectFileClearBlacklist(self) -> int:
        """清空黑名单

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileClearBlacklist")
        return func(self.OLAObject)

    def ProtectFileQueryBlacklist(self, pid: int) -> int:
        """查询进程是否在黑名单中

        Args:
            pid: 进程ID

        Returns:
            1-在黑名单中, 0-不在黑名单中或查询失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ProtectFileQueryBlacklist")
        return func(self.OLAObject, pid)

    def EnabletVtDriver(self, enable: int) -> int:
        """启用VT驱动

        Args:
            enable: 是否启用VT驱动

        Returns:
            1加载VT驱动成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("EnabletVtDriver")
        return func(self.OLAObject, enable)

    def VtFakeWriteData(self, hwnd: int, addr: str, data: str) -> int:
        """写入指定地址的数据. 可以让执行和读写分离，可以有效的解决CRC检测

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            data: 数据 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VtFakeWriteData")
        return func(self.OLAObject, hwnd, addr, data)

    def VtFakeWriteDataFromBin(self, hwnd: int, addr: str, data: int, _len: int) -> int:
        """写入指定地址的数据. 可以让执行和读写分离，可以有效的解决CRC检测

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            data: 字符串数据地址
            _len: 数据长度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VtFakeWriteDataFromBin")
        return func(self.OLAObject, hwnd, addr, data, _len)

    def VtFakeWriteDataAddr(self, hwnd: int, addr: int, data: str) -> int:
        """写入指定地址的数据. 可以让执行和读写分离，可以有效的解决CRC检测

        Args:
            hwnd: 窗口句柄
            addr: 地址
            data: 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VtFakeWriteDataAddr")
        return func(self.OLAObject, hwnd, addr, data)

    def VtFakeWriteDataAddrFromBin(self, hwnd: int, addr: int, data: int, _len: int) -> int:
        """写入指定地址的数据. 可以让执行和读写分离，可以有效的解决CRC检测

        Args:
            hwnd: 窗口句柄
            addr: 地址
            data: 数据 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"
            _len: 数据长度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VtFakeWriteDataAddrFromBin")
        return func(self.OLAObject, hwnd, addr, data, _len)

    def VtUnFakeMemoryAddr(self, hwnd: int, addr: int) -> int:
        """卸载伪造内存

        Args:
            hwnd: 窗口句柄
            addr: 地址

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VtUnFakeMemoryAddr")
        return func(self.OLAObject, hwnd, addr)

    def VtUnFakeMemory(self, hwnd: int, addr: str) -> int:
        """卸载伪造内存

        Args:
            hwnd: 窗口句柄
            addr: 地址

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VtUnFakeMemory")
        return func(self.OLAObject, hwnd, addr)

    def VipProtectEnableDriver(self) -> int:
        """开启高级保护

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectEnableDriver")
        return func(self.OLAObject)

    def VipProtectDisableDriver(self) -> int:
        """关闭高级保护

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectDisableDriver")
        return func(self.OLAObject)

    def VipProtectAddProtect(self, pid: int, path: str, mode: int, permission: int) -> int:
        """添加保护

        Args:
            pid: 需要保护的进程ID
            path: 需要保护的文件或文件夹路径
            mode: 保护模式：1-允许白名单进程访问, 2-禁止全部访问, 3-禁止黑名单进程访问,4-允许白名单文件路径访问, 5-禁止黑名单文件路径访问
            permission: 保护权限：位标志组合，VIP_PERMISSION_BLOCK_OPEN |VIP_PERMISSION_HIDE_INFORMATION | VIP_PERMISSION_BLOCK_MEMORY | VIP_PERMISSION_BLOCK_WINDOWS

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectAddProtect")
        return func(self.OLAObject, pid, path, mode, permission)

    def VipProtectRemoveProtect(self, pid: int, path: str) -> int:
        """移除保护

        Args:
            pid: 需要移除保护的进程ID
            path: 需要移除保护的文件或文件夹路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectRemoveProtect")
        return func(self.OLAObject, pid, path)

    def VipProtectClearAll(self) -> int:
        """清空所有保护

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectClearAll")
        return func(self.OLAObject)

    def VipProtectAddWhitelist(self, pid: int, path: str) -> int:
        """添加白名单

        Args:
            pid: 需要添加白名单的进程ID
            path: 需要添加白名单的文件或文件夹路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectAddWhitelist")
        return func(self.OLAObject, pid, path)

    def VipProtectRemoveWhitelist(self, pid: int, path: str) -> int:
        """移除白名单

        Args:
            pid: 需要移除白名单的进程ID
            path: 需要移除白名单的文件或文件夹路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectRemoveWhitelist")
        return func(self.OLAObject, pid, path)

    def VipProtectClearWhitelist(self) -> int:
        """清空白名单

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectClearWhitelist")
        return func(self.OLAObject)

    def VipProtectAddBlacklist(self, pid: int, path: str) -> int:
        """添加黑名单

        Args:
            pid: 需要添加黑名单的进程ID
            path: 需要添加黑名单的文件或文件夹路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectAddBlacklist")
        return func(self.OLAObject, pid, path)

    def VipProtectRemoveBlacklist(self, pid: int, path: str) -> int:
        """移除黑名单

        Args:
            pid: 需要移除黑名单的进程ID
            path: 需要移除黑名单的文件或文件夹路径

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectRemoveBlacklist")
        return func(self.OLAObject, pid, path)

    def VipProtectClearBlacklist(self) -> int:
        """清空黑名单

        Returns:
            1成功 其他失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VipProtectClearBlacklist")
        return func(self.OLAObject)

    def GenerateRSAKey(self, publicKeyPath: str, privateKeyPath: str, _type: int, keySize: int) -> int:
        """生成RSA密钥

        Args:
            publicKeyPath: 公钥路径
            privateKeyPath: 私钥路径
            _type: 类型,取值如下:，可选值:
                0: 生成pem格式秘钥
                1: 生成xml格式秘钥
                2: 生成PKCS1格式秘钥
            keySize: 密钥大小,取值如下:，可选值:
                512: 512位
                1024: 1024位
                2048: 2048位
                4096: 4096位

        Returns:
            0 成功,其他 失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GenerateRSAKey")
        return func(self.OLAObject, publicKeyPath, privateKeyPath, _type, keySize)

    def ConvertRSAPublicKey(self, publicKey: str, inputType: int, outputType: int) -> str:
        """转换RSA公钥

        Args:
            publicKey: 公钥
            inputType: 输入类型,取值如下:，可选值:
                0: pem格式
                1: xml格式
                2: PKCS1格式
            outputType: 输出类型,取值如下:，可选值:
                0: pem格式
                1: xml格式
                2: PKCS1格式

        Returns:
            成功返回转换后的公钥字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("ConvertRSAPublicKey")
        return self.PtrToStringUTF8(func(self.OLAObject, publicKey, inputType, outputType))

    def ConvertRSAPrivateKey(self, privateKey: str, inputType: int, outputType: int) -> str:
        """转换RSA私钥

        Args:
            privateKey: 私钥
            inputType: 输入类型,取值如下:，可选值:
                0: pem格式
                1: xml格式
                2: PKCS1格式
            outputType: 输出类型,取值如下:，可选值:
                0: pem格式
                1: xml格式
                2: PKCS1格式

        Returns:
            成功返回转换后的私钥字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("ConvertRSAPrivateKey")
        return self.PtrToStringUTF8(func(self.OLAObject, privateKey, inputType, outputType))

    def EncryptWithRsa(self, message: str, publicKey: str, paddingType: int) -> str:
        """使用RSA公钥加密

        Args:
            message: 明文
            publicKey: 公钥
            paddingType: 填充类型,取值如下:，可选值:
                0: PKCS1
                1: OAEP

        Returns:
            成功返回加密后的密文字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("EncryptWithRsa")
        return self.PtrToStringUTF8(func(self.OLAObject, message, publicKey, paddingType))

    def DecryptWithRsa(self, cipher: str, privateKey: str, paddingType: int) -> str:
        """使用RSA私钥解密

        Args:
            cipher: 密文
            privateKey: 私钥
            paddingType: 填充类型,取值如下:，可选值:
                0: PKCS1
                1: OAEP

        Returns:
            成功返回解密后的明文字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("DecryptWithRsa")
        return self.PtrToStringUTF8(func(self.OLAObject, cipher, privateKey, paddingType))

    def SignWithRsa(self, message: str, privateCer: str, shaType: int, paddingType: int) -> str:
        """使用RSA私钥签名

        Args:
            message: 明文
            privateCer: 私钥
            shaType: 哈希类型,取值如下:，可选值:
                0: MD5
                1: SHA1
                2: SHA256
                3: SHA384
                4: SHA512
                5: SHA3-256
                6: SHA3-384
                7: SHA3-512
            paddingType: 填充类型,取值如下:，可选值:
                0: Pkcs1
                1: Pss

        Returns:
            成功返回签名后的base64字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("SignWithRsa")
        return self.PtrToStringUTF8(func(self.OLAObject, message, privateCer, shaType, paddingType))

    def VerifySignWithRsa(self, message: str, signature: str, shaType: int, paddingType: int, publicCer: str) -> int:
        """使用RSA公钥验证签名

        Args:
            message: 明文
            signature: 签名
            shaType: 哈希类型,取值如下:，可选值:
                0: MD5
                1: SHA1
                2: SHA256
                3: SHA384
                4: SHA512
                5: SHA3-256
                6: SHA3-384
                7: SHA3-512
            paddingType: 填充类型,取值如下:，可选值:
                0: Pkcs1
                1: Pss
            publicCer: 公钥

        Returns:
            验证结果
                0: 验证失败
                1: 验证成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VerifySignWithRsa")
        return func(self.OLAObject, message, signature, shaType, paddingType, publicCer)

    def AESEncrypt(self, source: str, key: str) -> str:
        """AES加密简化版本，使用默认参数

        Args:
            source: 源数据
            key: 密钥字符串长度应为16/24/32个字符，对应AES-128/192/256

        Returns:
            成功返回加密后的数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 此接口使用CBC模式和PKCS7填充，默认IV为0。如需自定义参数请使用 AESEncryptEx
        """
        func = OLAPlugDLLHelper.get_function("AESEncrypt")
        return self.PtrToStringUTF8(func(self.OLAObject, source, key))

    def AESDecrypt(self, source: str, key: str) -> str:
        """AES解密简化版本，使用默认参数

        Args:
            source: 源数据
            key: 密钥字符串长度应为16/24/32个字符，对应AES-128/192/256)

        Returns:
            成功返回解密后的数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
            2. 此接口使用CBC模式和PKCS7填充，默认IV为0。如需自定义参数请使用 AESDecryptEx
        """
        func = OLAPlugDLLHelper.get_function("AESDecrypt")
        return self.PtrToStringUTF8(func(self.OLAObject, source, key))

    def AESEncryptEx(self, source: str, key: str, iv: str, mode: int, paddingType: int) -> str:
        """AES加密

        Args:
            source: 源数据
            key: 密钥
            iv: 初始向量
            mode: 加密模式,取值如下:，可选值:
                0: CBC
                1: ECB
                2: CFB
                3: OFB
                4: CTS
            paddingType: 填充类型,取值如下:，可选值:
                0: PKCS7
                1: Zeros
                2: AnsiX923
                3: ISO10126
                4: NoPadding

        Returns:
            成功返回加密后的数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("AESEncryptEx")
        return self.PtrToStringUTF8(func(self.OLAObject, source, key, iv, mode, paddingType))

    def AESDecryptEx(self, source: str, key: str, iv: str, mode: int, paddingType: int) -> str:
        """AES解密

        Args:
            source: 源数据
            key: 密钥
            iv: 初始向量
            mode: 加密模式,取值如下:，可选值:
                0: CBC
                1: ECB
                2: CFB
                3: OFB
                4: CTS
            paddingType: 填充类型,取值如下:，可选值:
                0: PKCS7
                1: Zeros
                2: AnsiX923
                3: ISO10126
                4: NoPadding

        Returns:
            成功返回解密后的数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("AESDecryptEx")
        return self.PtrToStringUTF8(func(self.OLAObject, source, key, iv, mode, paddingType))

    def MD5Encrypt(self, source: str) -> str:
        """MD5加密

        Args:
            source: 源数据

        Returns:
            成功返回加密后的数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("MD5Encrypt")
        return self.PtrToStringUTF8(func(self.OLAObject, source))

    def SHAHash(self, source: str, shaType: int) -> str:
        """SHA系列哈希算法

        Args:
            source: 源数据
            shaType: 哈希类型,取值如下:，可选值:
                0: MD5
                1: SHA1
                2: SHA256
                3: SHA384
                4: SHA512
                5: SHA3-256
                6: SHA3-384
                7: SHA3-512

        Returns:
            成功返回哈希后的数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("SHAHash")
        return self.PtrToStringUTF8(func(self.OLAObject, source, shaType))

    def HMAC(self, source: str, key: str, shaType: int) -> str:
        """HMAC消息认证码

        Args:
            source: 源数据
            key: 密钥
            shaType: 哈希类型,取值如下:，可选值:
                0: MD5
                1: SHA1
                2: SHA256
                3: SHA384
                4: SHA512
                5: SHA3-256
                6: SHA3-384
                7: SHA3-512

        Returns:
            成功返回HMAC值；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("HMAC")
        return self.PtrToStringUTF8(func(self.OLAObject, source, key, shaType))

    def GenerateRandomBytes(self, length: int, _type: int) -> str:
        """生成随机字节

        Args:
            length: 要生成的随机字节长度
            _type: 字符类型,取值如下:，可选值:
                0: 十六进制字符(0-9A-F)
                1: 数字+大写字母(0-9A-Z)
                2: 数字+大小写字母(0-9A-Za-z)
                3: 可打印ASCII字符(包含特殊字符)
                4: Base64字符集(A-Za-z0-9+/)

        Returns:
            成功返回随机字节字符串的指针；失败返回0

        Notes:
            1. 可直接用作AES密钥，推荐长度：16/24/32
            2. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("GenerateRandomBytes")
        return self.PtrToStringUTF8(func(self.OLAObject, length, _type))

    def GenerateGuid(self, _type: int) -> str:
        """生成GUID

        Args:
            _type: 类型,取值如下:，可选值:
                0: 带-的GUID如{123e4567-e89b-12d3-a456-426614174000}
                1: 不带-的GUID如123e4567e89b12d3a456426614174000

        Returns:
            成功返回GUID字符串的指针；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("GenerateGuid")
        return self.PtrToStringUTF8(func(self.OLAObject, _type))

    def Base64Encode(self, source: str) -> str:
        """Base64编码

        Args:
            source: 源数据

        Returns:
            成功返回Base64编码后的字符串；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("Base64Encode")
        return self.PtrToStringUTF8(func(self.OLAObject, source))

    def Base64Decode(self, source: str) -> str:
        """Base64解码

        Args:
            source: Base64编码的字符串

        Returns:
            成功返回解码后的原始数据；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("Base64Decode")
        return self.PtrToStringUTF8(func(self.OLAObject, source))

    def PBKDF2(self, password: str, salt: str, iterations: int, keyLength: int, shaType: int) -> str:
        """PBKDF2密钥派生函数

        Args:
            password: 密码
            salt: 盐值
            iterations: 迭代次数
            keyLength: 派生密钥长度
            shaType: 哈希类型,取值如下:，可选值:
                1: SHA1
                2: SHA256
                3: SHA384
                4: SHA512

        Returns:
            成功返回派生密钥；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("PBKDF2")
        return self.PtrToStringUTF8(func(self.OLAObject, password, salt, iterations, keyLength, shaType))

    def MD5File(self, filePath: str) -> str:
        """计算文件MD5哈希值

        Args:
            filePath: 文件路径

        Returns:
            成功返回MD5哈希值；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("MD5File")
        return self.PtrToStringUTF8(func(self.OLAObject, filePath))

    def SHAFile(self, filePath: str, shaType: int) -> str:
        """计算文件SHA哈希值

        Args:
            filePath: 文件路径
            shaType: 哈希类型,取值如下:，可选值:
                0: MD5
                1: SHA1
                2: SHA256
                3: SHA384
                4: SHA512
                5: SHA3-256
                6: SHA3-384
                7: SHA3-512

        Returns:
            成功返回哈希值；失败返回0

        Notes:
            1. 返回的字符串指针需要调用 FreeStringPtr 释放内存
        """
        func = OLAPlugDLLHelper.get_function("SHAFile")
        return self.PtrToStringUTF8(func(self.OLAObject, filePath, shaType))

    def CreateFolder(self, path: str) -> int:
        """创建文件夹

        Args:
            path: 文件夹路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateFolder")
        return func(self.OLAObject, path)

    def DeleteFolder(self, path: str) -> int:
        """删除文件夹

        Args:
            path: 文件夹路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DeleteFolder")
        return func(self.OLAObject, path)

    def GetFolderList(self, path: str, baseDir: str) -> str:
        """获取文件夹列表

        Args:
            path: 文件夹路径
            baseDir: 基础目录,不为空时返回这个相对路径

        Returns:
            返回字符串，失败返回0

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("GetFolderList")
        return self.PtrToStringUTF8(func(self.OLAObject, path, baseDir))

    def IsDirectory(self, path: str) -> int:
        """判断文件夹是否存在

        Args:
            path: 文件夹路径

        Returns:
            是否存在，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("IsDirectory")
        return func(self.OLAObject, path)

    def IsFile(self, path: str) -> int:
        """判断文件是否存在

        Args:
            path: 文件路径

        Returns:
            是否存在，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("IsFile")
        return func(self.OLAObject, path)

    def CreateFile(self, path: str) -> int:
        """创建文件

        Args:
            path: 文件路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateFile")
        return func(self.OLAObject, path)

    def DeleteFile(self, path: str) -> int:
        """删除文件

        Args:
            path: 文件路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DeleteFile")
        return func(self.OLAObject, path)

    def CopyFile(self, src: str, dst: str) -> int:
        """复制文件

        Args:
            src: 源文件路径
            dst: 目标文件路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CopyFile")
        return func(self.OLAObject, src, dst)

    def MoveFile(self, src: str, dst: str) -> int:
        """移动文件

        Args:
            src: 源文件路径
            dst: 目标文件路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MoveFile")
        return func(self.OLAObject, src, dst)

    def RenameFile(self, src: str, dst: str) -> int:
        """重命名文件

        Args:
            src: 源文件路径
            dst: 目标文件路径

        Returns:
            操作结果
                0: 失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RenameFile")
        return func(self.OLAObject, src, dst)

    def GetFileSize(self, path: str) -> int:
        """获取文件大小

        Args:
            path: 文件路径

        Returns:
            文件大小，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetFileSize")
        return func(self.OLAObject, path)

    def GetFileList(self, path: str, baseDir: str) -> str:
        """获取文件列表

        Args:
            path: 文件夹路径
            baseDir: 基础目录,不为空时返回这个相对路径

        Returns:
            返回字符串，失败返回0

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("GetFileList")
        return self.PtrToStringUTF8(func(self.OLAObject, path, baseDir))

    def GetFileName(self, path: str, withExtension: int) -> str:
        """获取文件名

        Args:
            path: 文件路径
            withExtension: 是否包含扩展名

        Returns:
            文件名，失败返回0

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("GetFileName")
        return self.PtrToStringUTF8(func(self.OLAObject, path, withExtension))

    def ToAbsolutePath(self, path: str) -> str:
        """转为绝对路径

        Args:
            path: 文件路径

        Returns:
            绝对路径，失败返回0

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("ToAbsolutePath")
        return self.PtrToStringUTF8(func(self.OLAObject, path))

    def ToRelativePath(self, path: str) -> str:
        """转为相对路径

        Args:
            path: 文件路径

        Returns:
            相对路径，失败返回0

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("ToRelativePath")
        return self.PtrToStringUTF8(func(self.OLAObject, path))

    def FileOrDirectoryExists(self, path: str) -> int:
        """判断文件/目录是否存在

        Args:
            path: 文件路径

        Returns:
            是否存在，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FileOrDirectoryExists")
        return func(self.OLAObject, path)

    def ReadFileString(self, filePath: str, encoding: int) -> str:
        """读取文件

        Args:
            filePath: 文件路径
            encoding: 编码，可选值:
                -1: : 自动检测编码
                0: : GBK字符串
                1: : Unicode字符串
                2: : UTF8字符串
                3: : UTF-8 with BOM auto-remove

        Returns:
            返回字符串，失败返回0

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("ReadFileString")
        return self.PtrToStringUTF8(func(self.OLAObject, filePath, encoding))

    def ReadBytesFromFile(self, filePath: str, offset: int, size: int) -> int:
        """从文件中读取指定偏移量的指定大小的字节

        Args:
            filePath: 文件路径
            offset: 偏移量
            size: 大小,0表示读取整个文件

        Returns:
            返回缓冲区地址,失败返回0

        Notes:
            1. 返回的缓冲区地址需调用FreeMemoryPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("ReadBytesFromFile")
        return func(self.OLAObject, filePath, offset, size)

    def WriteBytesToFile(self, filePath: str, dataAddr: int, dataSize: int) -> int:
        """将字节流写入文件

        Args:
            filePath: 文件路径
            dataAddr: 数据地址
            dataSize: 数据大小

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteBytesToFile")
        return func(self.OLAObject, filePath, dataAddr, dataSize)

    def WriteStringToFile(self, filePath: str, data: str, encoding: int) -> int:
        """将字符串写入文件

        Args:
            filePath: 文件路径
            data: 数据
            encoding: 编码

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteStringToFile")
        return func(self.OLAObject, filePath, data, encoding)

    def StartHotkeyHook(self) -> int:
        """启动全局钩子

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("StartHotkeyHook")
        return func(self.OLAObject)

    def StopHotkeyHook(self) -> int:
        """停止全局钩子

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("StopHotkeyHook")
        return func(self.OLAObject)

    def RegisterHotkey(self, keycode: int, modifiers: int, callback: Callable[[int, int], int]) -> int:
        """注册热键

        Args:
            keycode: 按键码
            modifiers: 修饰键组合，使用Modifier枚举值的位或组合，比如按下Ctrl+Alt modifiers:2+8=10enum 0 无掩码enum 1 左Shift键掩码enum 2 左Ctrl键掩码enum 4 左Meta键掩码enum 8 左Alt键掩码enum 16 右Shift键掩码enum 32 右Ctrl键掩码enum 64 右Meta键掩码enum 128 右Alt键掩码
            callback: 回调函数 int HotKeyCallback(int keycode, int modifiers) 参考接口参数定义

        Returns:
            注册监听状态
                0: 失败
                1: 成功

        Notes:
            1. 注册键盘快捷键监听,可监听单个按键、组合键等，同一组按键只能创建一个监听
            2. 注册键盘快捷键监听前需要调用StartHotkeyHook安装键盘鼠标钩子
            3. 回调函数 int HotKeyCallback(int keycode, intmodifiers)，参考接口参数定义，回1阻断消息传递，keycode传0可以监听所有按键信息
            4. 参考windows函数 SetWindowsHookExW 实现
        """
        func = OLAPlugDLLHelper.get_function("RegisterHotkey")
        return func(self.OLAObject, keycode, modifiers, callback)

    def UnregisterHotkey(self, keycode: int, modifiers: int) -> int:
        """注销热键

        Args:
            keycode: 按键码
            modifiers: 修饰键组合，使用Modifier枚举值的位或组合，比如按下Ctrl+Alt modifiers:2+8=10enum 1 左Shift键掩码enum 2 左Ctrl键掩码enum 4 左Meta键掩码enum 8 左Alt键掩码enum 16 右Shift键掩码enum 32 右Ctrl键掩码enum 64 右Meta键掩码enum 128 右Alt键掩码

        Returns:
            卸载监听状态

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnregisterHotkey")
        return func(self.OLAObject, keycode, modifiers)

    def RegisterMouseButton(self, button: int, _type: int, callback: Callable[[int, int, int, int], None]) -> int:
        """注册鼠标按钮事件

        Args:
            button: 按键类型enum 1 鼠标左键enum 2 鼠标右键enum 3 鼠标中键enum 4 拓展键1enum 5 拓展键2
            _type: 按键状态，使用Modifier枚举值的位或组合enum 0 鼠标点击enum 1 鼠标按下enum 2 鼠标释放
            callback: 回调函数 void MouseCallback(int button,int x, int y, int clicks)

        Returns:
            注册监听状态
                0: 失败
                1: 成功

        Notes:
            1. 注册鼠标快捷键监听前需要调用StartHotkeyHook安装键盘鼠标钩子
            2. 回调函数 void MouseCallback(int button,int x, int y, int clicks)button 参考参数定义x X坐标y Y坐标clicks 点击次数
            3. 参考windows函数 SetWindowsHookExW 实现
        """
        func = OLAPlugDLLHelper.get_function("RegisterMouseButton")
        return func(self.OLAObject, button, _type, callback)

    def UnregisterMouseButton(self, button: int, _type: int) -> int:
        """注销鼠标按钮事件

        Args:
            button: 按键类型enum 1 鼠标左键enum 2 鼠标右键enum 3 鼠标中键enum 4 拓展键1enum 5 拓展键2
            _type: 按键状态，使用Modifier枚举值的位或组合enum 0 鼠标点击enum 1 鼠标按下enum 2 鼠标释放

        Returns:
            卸载监听状态
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnregisterMouseButton")
        return func(self.OLAObject, button, _type)

    def RegisterMouseWheel(self, callback: Callable[[int, int, int, int], None]) -> int:
        """注册鼠标滚轮事件

        Args:
            callback: 回调函数 void MouseWheelCallback(int x, int y, int amount, int rotation)

        Returns:
            注册监听状态
                0: 失败
                1: 成功

        Notes:
            1. 注册鼠标快捷键监听前需要调用StartHotkeyHook安装键盘鼠标钩子
            2. 回调函数 void MouseWheelCallback(int x, int y, int amount, int rotation) 参数定义x 鼠标X坐标y 鼠标Y坐标amount 滚动量rotation 滚动方向
            3. 参考windows函数 SetWindowsHookExW 实现
        """
        func = OLAPlugDLLHelper.get_function("RegisterMouseWheel")
        return func(self.OLAObject, callback)

    def UnregisterMouseWheel(self) -> int:
        """注销鼠标滚轮事件

        Returns:
            卸载监听状态
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnregisterMouseWheel")
        return func(self.OLAObject)

    def RegisterMouseMove(self, callback: Callable[[int, int], None]) -> int:
        """注册鼠标移动事件

        Args:
            callback: 回调函数 void MouseMoveCallback(int x, int y)

        Returns:
            注册监听状态
                0: 失败
                1: 成功

        Notes:
            1. 注册鼠标快捷键监听前需要调用StartHotkeyHook安装键盘鼠标钩子
            2. 回调函数 void MouseMoveCallback(int x, int y) 参数定义x 鼠标X坐标y 鼠标Y坐标
            3. 参考windows函数 SetWindowsHookExW 实现
        """
        func = OLAPlugDLLHelper.get_function("RegisterMouseMove")
        return func(self.OLAObject, callback)

    def UnregisterMouseMove(self) -> int:
        """注销鼠标移动事件

        Returns:
            卸载监听状态
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnregisterMouseMove")
        return func(self.OLAObject)

    def RegisterMouseDrag(self, callback: Callable[[int, int], None]) -> int:
        """注册鼠标拖动事件

        Args:
            callback: 回调函数 void MouseDragCallback(int x, int y)

        Returns:
            注册监听状态
                0: 失败
                1: 成功

        Notes:
            1. 注册鼠标快捷键监听前需要调用StartHotkeyHook安装键盘鼠标钩子
            2. 回调函数 void MouseDragCallback(int x, int y) 参数定义x 鼠标X坐标y 鼠标Y坐标
            3. 参考windows函数 SetWindowsHookExW 实现
        """
        func = OLAPlugDLLHelper.get_function("RegisterMouseDrag")
        return func(self.OLAObject, callback)

    def UnregisterMouseDrag(self) -> int:
        """注销鼠标拖动事件

        Returns:
            卸载监听状态
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnregisterMouseDrag")
        return func(self.OLAObject)

    def Inject(self, hwnd: int, dll_path: str, _type: int, bypassGuard: int) -> int:
        """注入DLL

        Args:
            hwnd: 窗口句柄
            dll_path: DLL文件的完整路径
            _type: 注入类型，可选值:
                1: 标准注入(CreateRemoteThread)
                2: 驱动注入模式1
                3: 驱动注入模式2
                4: 驱动注入模式
            bypassGuard: 是否绕过保护，可选值:
                0: 不绕过
                1: 尝试绕过常见反注入保护

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. DLL文件必须存在且路径正确
            2. 目标进程必须有足够的权限允许注入
            3. 不同注入类型的成功率和兼容性可能不同
            4. 标准注入(type=0)最稳定,但容易被检测
            5. 手动映射注入(type=3)隐蔽性最好,但兼容性较差
            6. 绕过保护选项可能无法对抗所有反注入机制
            7. 注入系统进程或受保护进程需要管理员权限
            8. 32位进程只能注入32位DLL,64位进程只能注入64位DLL
            9. 建议在注入前确认DLL的架构与目标进程匹配
            10. 注入失败可能导致目标进程崩溃,请谨慎使用
            11. 某些杀毒软件可能会拦截DLL注入操作
        """
        func = OLAPlugDLLHelper.get_function("Inject")
        return func(self.OLAObject, hwnd, dll_path, _type, bypassGuard)

    def InjectFromUrl(self, hwnd: int, url: str, _type: int, bypassGuard: int) -> int:
        """从网络URL下载DLL文件并注入到指定窗口进程,支持远程注入场景。(部分模式文件会落盘)

        Args:
            hwnd: 窗口句柄
            url: DLL文件的下载URL地址
            _type: 注入类型，可选值:
                1: 标准注入(CreateRemoteThread)
                2: 驱动注入模式1
                3: 驱动注入模式2
                4: 驱动注入模式
            bypassGuard: 是否绕过保护，可选值:
                0: 不绕过
                1: 尝试绕过常见反注入保护

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. URL必须可访问且指向有效的DLL文件
            2. 需要网络连接,下载可能需要一定时间
            3. 下载的DLL会临时保存到本地再进行注入
            4. 建议使用HTTPS协议确保传输安全
            5. 下载失败或DLL损坏会导致注入失败
            6. 防火墙或杀毒软件可能会拦截下载
            7. 下载的临时文件会在注入后清理
            8. 目标进程必须有足够的权限允许注入
            9. 不同注入类型的成功率和兼容性可能不同
            10. 32位进程只能注入32位DLL,64位进程只能注入64位DLL
            11. 注入系统进程或受保护进程需要管理员权限
            12. 某些网络环境可能不支持直接下载可执行文件
            13. 建议验证下载文件的完整性和来源安全性
        """
        func = OLAPlugDLLHelper.get_function("InjectFromUrl")
        return func(self.OLAObject, hwnd, url, _type, bypassGuard)

    def InjectFromBuffer(self, hwnd: int, bufferAddr: int, bufferSize: int, _type: int, bypassGuard: int) -> int:
        """从内存缓冲区直接注入DLL到指定窗口进程,无需落地文件,隐蔽性最强。(部分模式文件会落盘)

        Args:
            hwnd: 窗口句柄
            bufferAddr: DLL数据在内存中的起始地址
            bufferSize: DLL数据的大小(字节)
            _type: 注入类型，可选值:
                1: 标准注入(CreateRemoteThread)
                2: 驱动注入模式1
                3: 驱动注入模式2
                4: 驱动注入模式
            bypassGuard: 是否绕过保护，可选值:
                0: 不绕过
                1: 尝试绕过常见反注入保护

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. DLL数据必须完整且有效,缓冲区不能损坏
            2. 内存注入无需落地文件,隐蔽性最强
            3. 推荐使用手动映射注入(type=3)以获得最佳兼容性
            4. 标准注入(type=0)可能无法从内存加载
            5. 确保bufferAddr指向的内存在注入完成前保持有效
            6. 注入完成后可以立即释放bufferAddr指向的内存
            7. 目标进程必须有足够的权限允许注入
            8. 32位进程只能注入32位DLL,64位进程只能注入64位DLL
            9. 注入系统进程或受保护进程需要管理员权限
            10. 内存注入可以有效规避部分文件监控类反注入
            11. 某些杀毒软件的内存扫描仍可能检测到注入行为
            12. 建议对DLL数据进行加密,在注入前解密以提高隐蔽性
            13. bufferSize必须与实际DLL文件大小完全一致
        """
        func = OLAPlugDLLHelper.get_function("InjectFromBuffer")
        return func(self.OLAObject, hwnd, bufferAddr, bufferSize, _type, bypassGuard)

    def JsonCreateObject(self) -> int:
        """创建空的JSON对象

        Returns:
            返回新创建的JSON对象句柄，失败时返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonCreateObject")
        return func()

    def JsonCreateArray(self) -> int:
        """创建空的JSON数组

        Returns:
            返回新创建的JSON数组句柄，失败时返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonCreateArray")
        return func()

    def JsonParse(self, _str: str, err: int = None) -> Tuple[int, int]:
        """解析JSON字符串

        Args:
            _str: 要解析的JSON字符串
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回解析后的JSON对象句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonParse")
        return func(_str, err)

    def JsonStringify(self, obj: int, indent: int, err: int = None) -> Tuple[str, int]:
        """将JSON对象序列化为字符串

        Args:
            obj: JSON对象句柄
            indent: 缩进空格数，0表示不格式化
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回JSON字符串，需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonStringify")
        return self.PtrToStringUTF8(func(obj, indent, err))

    def JsonFree(self, obj: int) -> int:
        """释放JSON对象

        Args:
            obj: 要释放的JSON对象句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonFree")
        return func(obj)

    def JsonGetValue(self, obj: int, key: str, err: int = None) -> Tuple[int, int]:
        """获取JSON对象中的值

        Args:
            obj: JSON对象句柄
            key: 键名
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回对应的JSON值句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonGetValue")
        return func(obj, key, err)

    def JsonGetArrayItem(self, arr: int, index: int, err: int = None) -> Tuple[int, int]:
        """获取JSON数组中的元素

        Args:
            arr: JSON数组句柄
            index: 元素索引
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回数组元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonGetArrayItem")
        return func(arr, index, err)

    def JsonGetString(self, obj: int, key: str, err: int = None) -> Tuple[str, int]:
        """获取JSON对象中的字符串值

        Args:
            obj: JSON对象句柄
            key: 键名
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回字符串值，需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonGetString")
        return self.PtrToStringUTF8(func(obj, key, err))

    def JsonGetNumber(self, obj: int, key: str, err: int = None) -> Tuple[float, int]:
        """获取JSON对象中的数值

        Args:
            obj: JSON对象句柄
            key: 键名
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回数值，失败时返回0.0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonGetNumber")
        return func(obj, key, err)

    def JsonGetBool(self, obj: int, key: str, err: int = None) -> Tuple[int, int]:
        """获取JSON对象中的布尔值

        Args:
            obj: JSON对象句柄
            key: 键名
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回布尔值，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonGetBool")
        return func(obj, key, err)

    def JsonGetSize(self, obj: int, err: int = None) -> Tuple[int, int]:
        """获取JSON对象或数组的大小

        Args:
            obj: JSON对象或数组句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Returns:
            返回元组: (返回对象属性数量或数组长度，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonGetSize")
        return func(obj, err)

    def JsonSetValue(self, obj: int, key: str, value: int) -> int:
        """设置JSON对象中的值

        Args:
            obj: JSON对象句柄
            key: 键名
            value: 要设置的值句柄

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonSetValue")
        return func(obj, key, value)

    def JsonArrayAppend(self, arr: int, value: int) -> int:
        """向JSON数组添加元素

        Args:
            arr: JSON数组句柄
            value: 要添加的元素句柄

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonArrayAppend")
        return func(arr, value)

    def JsonSetString(self, obj: int, key: str, value: str) -> int:
        """设置JSON对象中的字符串值

        Args:
            obj: JSON对象句柄
            key: 键名
            value: 字符串值

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonSetString")
        return func(obj, key, value)

    def JsonSetNumber(self, obj: int, key: str, value: float) -> int:
        """设置JSON对象中的数值

        Args:
            obj: JSON对象句柄
            key: 键名
            value: 数值

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonSetNumber")
        return func(obj, key, value)

    def JsonSetBool(self, obj: int, key: str, value: int) -> int:
        """设置JSON对象中的布尔值

        Args:
            obj: JSON对象句柄
            key: 键名
            value: 布尔值

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonSetBool")
        return func(obj, key, value)

    def JsonDeleteKey(self, obj: int, key: str) -> int:
        """删除JSON对象中的键

        Args:
            obj: JSON对象句柄
            key: 要删除的键名

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonDeleteKey")
        return func(obj, key)

    def JsonClear(self, obj: int) -> int:
        """清空JSON对象或数组

        Args:
            obj: JSON对象或数组句柄

        Returns:
            返回操作结果错误码
                0: 操作成功
                1: 无效的句柄
                2: JSON解析失败
                3: 类型不匹配
                4: 键不存在
                5: 索引超出范围
                6: 未知错误

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("JsonClear")
        return func(obj)

    def ParseMatchImageJson(self, _str: str, matchState: int = None, x: int = None, y: int = None, width: int = None, height: int = None, matchVal: float = None, angle: float = None, index: int = None) -> Tuple[int, int, int, int, int, int, float, float, int]:
        """解析匹配图像JSON

        Args:
            _str: 匹配图像JSON字符串
            matchState: 匹配状态
            x: 匹配点X坐标
            y: 匹配点Y坐标
            width: 匹配宽度
            height: 匹配高度
            matchVal: 匹配值
            angle: 匹配角度
            index: 匹配索引

        Returns:
            返回元组: (返回操作结果错误码, 匹配状态, 匹配点X坐标, 匹配点Y坐标, 匹配宽度, 匹配高度, 匹配值, 匹配角度, 匹配索引)
            返回操作结果错误码:
                1: 解析成功
                0: 解析失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ParseMatchImageJson")
        return func(_str, matchState, x, y, width, height, matchVal, angle, index)

    def GetMatchImageAllCount(self, _str: str) -> int:
        """获取匹配图像JSON数量

        Args:
            _str: 匹配图像JSON字符串

        Returns:
            返回匹配图像JSON数量

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetMatchImageAllCount")
        return func(_str)

    def ParseMatchImageAllJson(self, _str: str, parseIndex: int, matchState: int = None, x: int = None, y: int = None, width: int = None, height: int = None, matchVal: float = None, angle: float = None, index: int = None) -> Tuple[int, int, int, int, int, int, float, float, int]:
        """解析匹配图像JSON所有

        Args:
            _str: 匹配图像JSON字符串
            parseIndex: 解析索引
            matchState: 匹配状态
            x: 匹配点X坐标
            y: 匹配点Y坐标
            width: 匹配宽度
            height: 匹配高度
            matchVal: 匹配值
            angle: 匹配角度
            index: 匹配索引

        Returns:
            返回元组: (返回操作结果错误码, 匹配状态, 匹配点X坐标, 匹配点Y坐标, 匹配宽度, 匹配高度, 匹配值, 匹配角度, 匹配索引)
            返回操作结果错误码:
                1: 解析成功
                0: 解析失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ParseMatchImageAllJson")
        return func(_str, parseIndex, matchState, x, y, width, height, matchVal, angle, index)

    def GetResultCount(self, resultStr: str) -> int:
        """对插件部分接口的返回值进行解析,并返回result中的元素个数,针对JSON格式和,|分割的字符串

        Args:
            resultStr: (字符串): 插件接口的返回值。

        Returns:
            整型数: result中的元素个数。

        Notes:
            1. 此函数用于对插件部分接口的返回值进行解析,并返回result中的元素个数。
        """
        func = OLAPlugDLLHelper.get_function("GetResultCount")
        return func(resultStr)

    def GenerateMouseTrajectory(self, startX: int, startY: int, endX: int, endY: int) -> str:
        """生成鼠标移动轨迹数据,用于二次开发

        Args:
            startX: 起点X坐标
            startY: 起点Y坐标
            endX: 终点X坐标
            endY: 终点Y坐标

        Returns:
            返回轨迹数据,如 [{"deltaX": 8,"deltaY": 5,"time": 7,"x": 108,"y": 105}, ...]

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("GenerateMouseTrajectory")
        return self.PtrToStringUTF8(func(self.OLAObject, startX, startY, endX, endY))

    def KeyDown(self, vk_code: int) -> int:
        """按住指定的虚拟键码

        Args:
            vk_code: 按键码

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeyDown")
        return func(self.OLAObject, vk_code)

    def KeyUp(self, vk_code: int) -> int:
        """弹起来虚拟键vk_code

        Args:
            vk_code: 按键码

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeyUp")
        return func(self.OLAObject, vk_code)

    def KeyPress(self, vk_code: int) -> int:
        """按下指定的虚拟键码

        Args:
            vk_code: 按键码

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeyPress")
        return func(self.OLAObject, vk_code)

    def LeftDown(self) -> int:
        """按住鼠标左键

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LeftDown")
        return func(self.OLAObject)

    def LeftUp(self) -> int:
        """弹起鼠标左键

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LeftUp")
        return func(self.OLAObject)

    def MoveTo(self, x: int, y: int) -> int:
        """把鼠标移动到目的点(x, y)

        Args:
            x: 目标X坐标
            y: 目标Y坐标

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MoveTo")
        return func(self.OLAObject, x, y)

    def MoveToWithoutSimulator(self, x: int, y: int) -> int:
        """把鼠标移动到目的点(x, y),不使用鼠标轨迹,即使开启鼠标轨迹这个接口也不会生效

        Args:
            x: X坐标
            y: Y坐标

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MoveToWithoutSimulator")
        return func(self.OLAObject, x, y)

    def RightClick(self) -> int:
        """执行鼠标右键点击操作

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
            1. 此函数执行完整的右键点击操作（按下并释放）
            2. 如果需要单独控制按下和释放，请使用 RightDown 和 RightUp 函数
            3. 点击操作会使用当前鼠标位置
            4. 如果需要移动到特定位置后点击，请先使用 MoveTo 函数
            5. 在调用此函数前，确保鼠标右键未被其他程序占用
        """
        func = OLAPlugDLLHelper.get_function("RightClick")
        return func(self.OLAObject)

    def RightDoubleClick(self) -> int:
        """鼠标右键双击

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RightDoubleClick")
        return func(self.OLAObject)

    def RightDown(self) -> int:
        """按住鼠标右键

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RightDown")
        return func(self.OLAObject)

    def RightUp(self) -> int:
        """弹起鼠标右键

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RightUp")
        return func(self.OLAObject)

    def GetCursorShape(self) -> str:
        """获取鼠标特征码

        Returns:
            返回鼠标特征码

        Notes:
            1. 并非所有的游戏都支持后台鼠标特征码,在获取特征码之前,需先操作鼠标
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("GetCursorShape")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def GetCursorImage(self) -> int:
        """获取鼠标图标

        Returns:
            OLAImage对象的地址

        Notes:
            1. 图片使用完后需要调用 FreeImagePtr 接口进行释放
        """
        func = OLAPlugDLLHelper.get_function("GetCursorImage")
        return func(self.OLAObject)

    def KeyPressStr(self, keyStr: str, delay: int) -> int:
        """根据指定的字符串序列，依次按顺序按下其中的字符

        Args:
            keyStr: 需要按下的字符串序列. 比如"1234","abcd","7389,1462"等
            delay: 每按下一个按键，需要延时多久。单位毫秒（ms），这个值越大，按的速度越慢

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
            1. 在某些情况下，SendString和SendString2都无法输入文字时，可以考虑用这个来输入
            2. 但这个接口只支持"a-z 0-9 ~-=[];',./"和空格,其它字符一律不支持.(包括中国)
        """
        func = OLAPlugDLLHelper.get_function("KeyPressStr")
        return func(self.OLAObject, keyStr, delay)

    def SendString(self, hwnd: int, _str: str) -> int:
        """发送字符串到指定窗口

        Args:
            hwnd: 窗口句柄
            _str: 字符串

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SendString")
        return func(self.OLAObject, hwnd, _str)

    def SendStringEx(self, hwnd: int, addr: int, _len: int, _type: int) -> int:
        """发送字符串到指定地址

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _len: 长度
            _type: 类型  字符串类型,取值如下，可选值:
                0: GBK字符串
                1: Unicode字符串
                2: UTF8字符串

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SendStringEx")
        return func(self.OLAObject, hwnd, addr, _len, _type)

    def KeyPressChar(self, keyStr: str) -> int:
        """按下指定的虚拟键码keyStr

        Args:
            keyStr: 按键字符

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeyPressChar")
        return func(self.OLAObject, keyStr)

    def KeyDownChar(self, keyStr: str) -> int:
        """按住指定的虚拟键码keyStr

        Args:
            keyStr: 按键字符

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeyDownChar")
        return func(self.OLAObject, keyStr)

    def KeyUpChar(self, keyStr: str) -> int:
        """弹起来虚拟键keyStr

        Args:
            keyStr: 按键字符

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("KeyUpChar")
        return func(self.OLAObject, keyStr)

    def MoveR(self, rx: int, ry: int) -> int:
        """鼠标相对于上次的位置移动rx, ry, 前台模式鼠标相对移动时相对当前鼠标位置

        Args:
            rx: 相对于上次的X偏移
            ry: 相对于上次的Y偏移

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MoveR")
        return func(self.OLAObject, rx, ry)

    def MiddleClick(self) -> int:
        """滚轮点击

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MiddleClick")
        return func(self.OLAObject)

    def MoveToEx(self, x: int, y: int, w: int, h: int) -> str:
        """将鼠标移动到指定范围内的随机位置

        Args:
            x: 目标区域左上角的X坐标
            y: 目标区域左上角的Y坐标
            w: 目标区域的宽度（从x计算起）
            h: 目标区域的高度（从y计算起）

        Returns:
            DLL调用: 返回字符串指针，包含移动后的坐标，格式为"x,y"

        Notes:
            1. 需要调用 FreeStringPtr 释放内存
            2. 此函数会在指定范围内随机选择一个点作为目标位置
            3. 坐标系统原点(0,0)在屏幕左上角
            4. 确保指定的范围在屏幕可见区域内
            5. 如果范围参数无效（如负数），函数将返回失败
            6. 移动操作是即时的，没有动画效果
            7. 建议在移动后添加适当的延时，使操作更自然
        """
        func = OLAPlugDLLHelper.get_function("MoveToEx")
        return self.PtrToStringUTF8(func(self.OLAObject, x, y, w, h))

    def GetCursorPos(self, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """获取鼠标位置

        Args:
            x: 返回的鼠标X坐标
            y: 返回的鼠标Y坐标

        Returns:
            返回元组: (操作结果, 返回的鼠标X坐标, 返回的鼠标Y坐标)
            操作结果:
                0: 失败@eunm 1 成功

        Notes:
            1. 此接口绑定后使用，获取的是相当游戏窗口的鼠标坐标
        """
        func = OLAPlugDLLHelper.get_function("GetCursorPos")
        return func(self.OLAObject, x, y)

    def MiddleUp(self) -> int:
        """弹起鼠标中键

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MiddleUp")
        return func(self.OLAObject)

    def MiddleDown(self) -> int:
        """按住鼠标中键

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
            1. 此函数仅模拟按下中键，不会自动释放
            2. 如果需要释放中键，需要调用 MiddleUp 函数
            3. 建议在操作完成后及时释放中键，避免影响后续操作
            4. 如果系统不支持中键操作，函数将返回失败
            5. 在调用此函数前，确保鼠标中键未被其他程序占用
        """
        func = OLAPlugDLLHelper.get_function("MiddleDown")
        return func(self.OLAObject)

    def MiddleDoubleClick(self) -> int:
        """滚轮双击

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
            1. 此函数执行完整的鼠标中键双击操作（按下并释放）
            2. 如果需要单独控制按下和释放，请使用 MiddleDown 和 MiddleUp 函数
            3. 点击操作会使用当前鼠标位置
            4. 如果需要移动到特定位置后点击，请先使用 MoveTo 函数
            5. 在调用此函数前，确保鼠标中键未被其他程序占用
        """
        func = OLAPlugDLLHelper.get_function("MiddleDoubleClick")
        return func(self.OLAObject)

    def LeftClick(self) -> int:
        """鼠标左键点击

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LeftClick")
        return func(self.OLAObject)

    def LeftDoubleClick(self) -> int:
        """鼠标左键双击

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LeftDoubleClick")
        return func(self.OLAObject)

    def WheelUp(self) -> int:
        """滚轮向上滚

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WheelUp")
        return func(self.OLAObject)

    def WheelDown(self) -> int:
        """滚轮向下滚

        Returns:
            操作结果
                0: 失败@eunm 1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WheelDown")
        return func(self.OLAObject)

    def WaitKey(self, vk_code: int, time_out: int) -> int:
        """等待指定的按键按下 (前台,不是后台)

        Args:
            vk_code: 等待的按键码
            time_out: 等待超时时间，单位毫秒

        Returns:
            等待结果
                0: 超时
                1: 指定的按键按下

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WaitKey")
        return func(self.OLAObject, vk_code, time_out)

    def EnableMouseAccuracy(self, enable: int) -> int:
        """设置当前系统鼠标的精确度开关

        Args:
            enable: 是否提高指针精确度，一般推荐关闭，可选值:
                0: 关闭指针精确度开关
                1: 打开指针精确度开关

        Returns:
            设置之前的精确度开关

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("EnableMouseAccuracy")
        return func(self.OLAObject, enable)

    def GenerateInvoluteMouseTrajectory(self, startX: int, startY: int, radius: int, stepDistance: int, curvature: float, noiseAmplitude: float) -> str:
        """生成鼠标渐开线随机移动轨迹

        Args:
            startX: 起点X坐标（中心点）
            startY: 起点Y坐标（中心点）
            radius: 移动半径范围（像素）
            stepDistance: 轨迹点之间的距离（像素，建议3-10，0表示自动计算为5）
            curvature: 曲率系数（0.5-2.0，越大越弯曲，默认1.0）
            noiseAmplitude: 随机扰动幅度（0-5像素，默认2.0）

        Returns:
            返回JSON格式的轨迹点数据，格式：{"points":[{"x":100,"y":200},...], "count":150}

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr接口释放内存
            2. 此函数生成在指定半径范围内的渐开线式随机游走轨迹，模拟自然的鼠标移动
            3. stepDistance越小轨迹越平滑但点数越多，建议值：精细3-5，标准5-8，快速8-10
            4. curvature控制弯曲程度，值越大轨迹越弯曲，建议范围0.5-2.0
            5. noiseAmplitude控制随机抖动幅度，模拟人手抖动，建议范围1.0-3.0
        """
        func = OLAPlugDLLHelper.get_function("GenerateInvoluteMouseTrajectory")
        return self.PtrToStringUTF8(func(self.OLAObject, startX, startY, radius, stepDistance, curvature, noiseAmplitude))

    def LogShutdown(self, loggerHandle: int) -> int:
        """关闭用户日志系统并释放资源

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 可以使用位或运算组合颜色，例如：FOREGROUND_RED | FOREGROUND_GREEN = 黄色
            2. 添加 FOREGROUND_INTENSITY (0x08) 可以使颜色变亮
            3. 关闭后，下次写入日志时会自动重新初始化
            4. 通常在程序退出前调用，或需要完全重置日志系统时使用
        """
        func = OLAPlugDLLHelper.get_function("LogShutdown")
        return func(self.OLAObject, loggerHandle)

    def LogSetFilePath(self, loggerHandle: int, logFilePath: str) -> int:
        """设置日志文件路径

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            logFilePath: 日志文件路径（为空则使用默认路径）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认路径：./user_logs/app.log（程序运行目录下）
            2. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetFilePath")
        return func(self.OLAObject, loggerHandle, logFilePath)

    def LogSetPattern(self, loggerHandle: int, logPattern: str) -> int:
        """设置日志格式（支持占位符）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            logPattern: 日志格式（为空则使用默认格式）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认格式：[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v
            2. 支持的占位符（基于 spdlog 格式）：【时间日期】%Y - 年份（4位数字，如 2026）%y - 年份（2位数字，如 26）%m - 月份（01-12）%d - 日期（01-31）%H - 小时（00-23，24小时制）%I - 小时（01-12，12小时制）%M - 分钟（00-59）%S - 秒（00-59）%e - 毫秒（000-999）%f - 微秒（000000-999999）%F - 纳秒（000000000-999999999）%p - AM/PM 标识%a - 星期简写（Mon, Tue, ...）%A - 星期全称（Monday, Tuesday, ...）%b - 月份简写（Jan, Feb, ...）%B - 月份全称（January, February, ...）%c - 日期时间（Thu Aug 23 15:35:46 2014）%D - 短日期（MM/DD/YY）%x - 日期表示（08/23/14）%X - 时间表示（15:35:46）%T - ISO 8601 时间格式（HH:MM:SS）%R - 24小时制时间（HH:MM）%z - UTC 偏移量（+0800）%Z - 时区名称（CST）%E - Unix 纪元秒数（1440351346）【日志信息】%v - 日志消息内容%l - 日志级别（TRACE, DEBUG, INFO, WARN, ERROR, CRITICAL）%L - 日志级别简写（T, D, I, W, E, C）%n - 日志记录器名称%t - 线程ID%P - 进程ID【源代码信息】%s - 源文件名%g - 源文件短名称（不含路径）%# - 源代码行号%! - 函数名【颜色控制】%^ - 颜色范围开始标记（根据日志级别自动着色）%$ - 颜色范围结束标记【特殊字符】%% - 百分号字面量%+ - spdlog 默认格式
            3. 示例格式："[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v" → [2026-02-28 14:30:45.123] [INFO] 日志消息"[%T.%e] [%L] [%t] %v" → [14:30:45.123] [I] [12345] 日志消息"%Y%m%d %H:%M:%S [%l] %v" → 20260228 14:30:45 [INFO] 日志消息
            4. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetPattern")
        return func(self.OLAObject, loggerHandle, logPattern)

    def LogSetMaxFileSize(self, loggerHandle: int, maxFileSizeMb: int) -> int:
        """设置单个日志文件最大大小

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            maxFileSizeMb: 单个日志文件最大大小（MB）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：100MB
            2. 当日志文件达到此大小时，会自动创建新文件（滚动日志）
            3. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetMaxFileSize")
        return func(self.OLAObject, loggerHandle, maxFileSizeMb)

    def LogSetMaxFiles(self, loggerHandle: int, maxFiles: int) -> int:
        """设置最多保留的日志文件数量

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            maxFiles: 最多保留的日志文件数量

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：10个
            2. 超过此数量时，最旧的日志文件会被自动删除
            3. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetMaxFiles")
        return func(self.OLAObject, loggerHandle, maxFiles)

    def LogSetLevel(self, loggerHandle: int, level: int) -> int:
        """设置日志级别

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            level: 日志级别，见OLALogLevel

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：OLA_LOG_LEVEL_INFO (2)
            2. 只有大于或等于此级别的日志才会被记录
            3. 此设置立即生效，无需重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetLevel")
        return func(self.OLAObject, loggerHandle, level)

    def LogGetLevel(self, loggerHandle: int) -> int:
        """获取当前日志级别

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            当前日志级别，见OLALogLevel，失败返回-1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogGetLevel")
        return func(self.OLAObject, loggerHandle)

    def LogSetTarget(self, loggerHandle: int, targetFlags: int) -> int:
        """设置输出目标

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            targetFlags: 输出目标（OLALogTarget 组合）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：FILE(1) | CONSOLE (3)
            2. 可以使用位或运算组合多个目标，例如：FILE | CONSOLE
            3. 控制台输出支持彩色显示（不同级别显示不同颜色）
            4. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetTarget")
        return func(self.OLAObject, loggerHandle, targetFlags)

    def LogSetAsync(self, loggerHandle: int, enableAsync: int) -> int:
        """设置是否启用异步日志

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            enableAsync: 是否启用异步日志，1 启用，0 禁用

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：1（异步模式）
            2. 异步模式可以提高性能，但可能在程序崩溃时丢失部分日志
            3. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetAsync")
        return func(self.OLAObject, loggerHandle, enableAsync)

    def LogSetColorMode(self, loggerHandle: int, colorMode: int) -> int:
        """设置控制台颜色模式

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            colorMode: 颜色模式，见OLALogColorMode

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：OLA_LOG_COLOR_ALWAYS (1) - 始终启用彩色输出
            2. 默认颜色方案：TRACE - 白色DEBUG - 青色INFO - 绿色WARN - 亮黄色ERROR - 亮红色CRITICAL - 红色背景上的亮白色
            3. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetColorMode")
        return func(self.OLAObject, loggerHandle, colorMode)

    def LogSetLevelColor(self, loggerHandle: int, level: int, color: int) -> int:
        """设置指定日志级别的控制台颜色

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            level: 日志级别，见OLALogLevel
            color: 控制台颜色，见OLALogConsoleColor

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 仅在控制台输出启用且颜色模式不为 NEVER 时生效
            2. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
            3. 示例：OLALogSetLevelColor(instance, 0, OLA_LOG_LEVEL_INFO, OLA_LOG_COLOR_CYAN);
        """
        func = OLAPlugDLLHelper.get_function("LogSetLevelColor")
        return func(self.OLAObject, loggerHandle, level, color)

    def LogResetLevelColors(self, loggerHandle: int) -> int:
        """重置所有日志级别颜色为默认值

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 修改后立即生效，如果日志系统已初始化，会自动重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogResetLevelColors")
        return func(self.OLAObject, loggerHandle)

    def LogSetFlushInterval(self, loggerHandle: int, flushIntervalSeconds: int) -> int:
        """设置自动刷新间隔

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            flushIntervalSeconds: 自动刷新间隔（秒）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：0（每条日志立即刷新到文件）
            2. 设置为 0：每条日志都立即写入文件（最安全，但性能较低）
            3. 设置为 > 0：只有 WARN 及以上级别的日志才会立即刷新，其他日志会缓冲
            4. 无论设置如何，都可以手动调用 OLALogFlush 强制刷新
            5. 此设置立即生效，无需重新初始化
        """
        func = OLAPlugDLLHelper.get_function("LogSetFlushInterval")
        return func(self.OLAObject, loggerHandle, flushIntervalSeconds)

    def LogTrace(self, message: str) -> int:
        """写入 TRACE 级别日志

        Args:
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogTrace")
        return func(self.OLAObject, message)

    def LogDebug(self, message: str) -> int:
        """写入 DEBUG 级别日志

        Args:
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogDebug")
        return func(self.OLAObject, message)

    def LogInfo(self, message: str) -> int:
        """写入 INFO 级别日志

        Args:
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogInfo")
        return func(self.OLAObject, message)

    def LogWarn(self, message: str) -> int:
        """写入 WARN 级别日志

        Args:
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogWarn")
        return func(self.OLAObject, message)

    def LogError(self, message: str) -> int:
        """写入 ERROR 级别日志

        Args:
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogError")
        return func(self.OLAObject, message)

    def LogCritical(self, message: str) -> int:
        """写入 CRITICAL 级别日志

        Args:
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogCritical")
        return func(self.OLAObject, message)

    def LogFlush(self, loggerHandle: int) -> int:
        """立即刷新日志缓冲区到文件

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 如果 flushIntervalSeconds 设置为 0（默认），日志会自动立即刷新，无需手动调用此函数
            2. 如果 flushIntervalSeconds > 0，可以调用此函数强制刷新缓冲区中的日志
        """
        func = OLAPlugDLLHelper.get_function("LogFlush")
        return func(self.OLAObject, loggerHandle)

    def LogCreateInstance(self, instanceName: str) -> int:
        """创建新的日志实例

        Args:
            instanceName: 实例名称（用于标识，如 "NetworkLogger"）

        Returns:
            日志实例句柄，失败返回 0

        Notes:
            1. 新创建的实例使用默认配置
            2. 实例句柄必须通过 OLALogDestroyInstance 释放
            3. 默认实例（句柄 = 0）无需创建，始终存在
        """
        func = OLAPlugDLLHelper.get_function("LogCreateInstance")
        return func(self.OLAObject, instanceName)

    def LogDestroyInstance(self, loggerHandle: int) -> int:
        """销毁日志实例并释放资源

        Args:
            loggerHandle: 要销毁的日志实例句柄

        Returns:
            操作结果
                0: 失败（实例不存在或为默认实例）
                1: 成功

        Notes:
            1. 不能销毁默认实例（句柄 = 0）
            2. 销毁后，该句柄将失效，不可再使用
        """
        func = OLAPlugDLLHelper.get_function("LogDestroyInstance")
        return func(self.OLAObject, loggerHandle)

    def LogSetBaseDirectory(self, loggerHandle: int, baseDirectory: str) -> int:
        """设置日志根目录

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            baseDirectory: 根目录路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认：./user_logs
        """
        func = OLAPlugDLLHelper.get_function("LogSetBaseDirectory")
        return func(self.OLAObject, loggerHandle, baseDirectory)

    def LogSetDirMode(self, loggerHandle: int, dirMode: int) -> int:
        """设置目录组织模式

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            dirMode: 目录模式（可位或组合），见 OLALogDirMode

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认：OLA_LOG_DIR_FLAT (0)
            2. 示例：OLA_LOG_DIR_BY_DATE | OLA_LOG_DIR_BY_MODULE
        """
        func = OLAPlugDLLHelper.get_function("LogSetDirMode")
        return func(self.OLAObject, loggerHandle, dirMode)

    def LogSetModuleName(self, loggerHandle: int, moduleName: str) -> int:
        """设置模块名称

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            moduleName: 模块名称（用于目录组织）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于 OLA_LOG_DIR_BY_MODULE 模式
        """
        func = OLAPlugDLLHelper.get_function("LogSetModuleName")
        return func(self.OLAObject, loggerHandle, moduleName)

    def LogSetFileNamePattern(self, loggerHandle: int, fileNamePattern: str) -> int:
        """设置文件名模式（支持占位符）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            fileNamePattern: 文件名模式

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认值：app.log
            2. 支持的占位符：{date} - 当前日期（格式：YYYY-MM-DD，如 2026-02-28）{time} - 当前时间（格式：HH-MM-SS，如 14-30-45）{datetime} - 日期时间（格式：YYYY-MM-DD_HH-MM-SS，如 2026-02-28_14-30-45）{module} - 模块名称（通过 OLALogSetModuleName 设置）{level} - 日志级别（TRACE, DEBUG, INFO, WARN, ERROR, CRITICAL）{index} - 文件序号（用于文件分割，从 1 开始递增）{pid} - 进程ID（当前进程的唯一标识符）{year} - 年份（4位数字，如 2026）{month} - 月份（01-12）{day} - 日期（01-31）{hour} - 小时（00-23）{minute} - 分钟（00-59）{second} - 秒（00-59）
            3. 示例用法："app_{date}.log" → app_2026-02-28.log"{module}_{date}_{index}.log" → network_2026-02-28_1.log"log_{datetime}_{pid}.log" → log_2026-02-28_14-30-45_12345.log"{year}{month}{day}_{level}.log" → 20260228_INFO.log
            4. 文件分割时 {index} 会自动递增：app_1.log, app_2.log, app_3.log...
            5. 如果不使用 {index}，分割时会自动在文件名后添加序号
        """
        func = OLAPlugDLLHelper.get_function("LogSetFileNamePattern")
        return func(self.OLAObject, loggerHandle, fileNamePattern)

    def LogSetRotationMode(self, loggerHandle: int, rotationMode: int) -> int:
        """设置文件分割模式

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            rotationMode: 分割模式（可位或组合），见 OLALogRotationMode

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认：OLA_LOG_ROTATION_SIZE (1) - 仅按大小分割
            2. 可组合：OLA_LOG_ROTATION_SIZE | OLA_LOG_ROTATION_DAILY - 按大小和日期分割
        """
        func = OLAPlugDLLHelper.get_function("LogSetRotationMode")
        return func(self.OLAObject, loggerHandle, rotationMode)

    def LogSetAppendMode(self, loggerHandle: int, enableAppend: int) -> int:
        """设置文件追加模式

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            enableAppend: 是否启用追加（1 启用，0 禁用）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 默认：1（启用追加）
            2. 启用时：程序重启后继续追加到现有文件
            3. 禁用时：程序重启后将现有文件重命名为备份，创建新文件
        """
        func = OLAPlugDLLHelper.get_function("LogSetAppendMode")
        return func(self.OLAObject, loggerHandle, enableAppend)

    def LogTraceEx(self, loggerHandle: int, message: str) -> int:
        """写入 TRACE 级别日志（扩展版本，支持指定实例）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogTraceEx")
        return func(self.OLAObject, loggerHandle, message)

    def LogDebugEx(self, loggerHandle: int, message: str) -> int:
        """写入 DEBUG 级别日志（扩展版本，支持指定实例）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogDebugEx")
        return func(self.OLAObject, loggerHandle, message)

    def LogInfoEx(self, loggerHandle: int, message: str) -> int:
        """写入 INFO 级别日志（扩展版本，支持指定实例）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogInfoEx")
        return func(self.OLAObject, loggerHandle, message)

    def LogWarnEx(self, loggerHandle: int, message: str) -> int:
        """写入 WARN 级别日志（扩展版本，支持指定实例）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogWarnEx")
        return func(self.OLAObject, loggerHandle, message)

    def LogErrorEx(self, loggerHandle: int, message: str) -> int:
        """写入 ERROR 级别日志（扩展版本，支持指定实例）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogErrorEx")
        return func(self.OLAObject, loggerHandle, message)

    def LogCriticalEx(self, loggerHandle: int, message: str) -> int:
        """写入 CRITICAL 级别日志（扩展版本，支持指定实例）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            message: 日志消息

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogCriticalEx")
        return func(self.OLAObject, loggerHandle, message)

    def LogRotateFile(self, loggerHandle: int) -> int:
        """手动触发日志文件分割

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 立即关闭当前文件并创建新文件
        """
        func = OLAPlugDLLHelper.get_function("LogRotateFile")
        return func(self.OLAObject, loggerHandle)

    def LogCleanupOldFiles(self, loggerHandle: int, keepCount: int) -> int:
        """清理超过保留数量的旧日志文件

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）
            keepCount: 保留文件数量（-1 表示使用配置值）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogCleanupOldFiles")
        return func(self.OLAObject, loggerHandle, keepCount)

    def LogGetCurrentFilePath(self, loggerHandle: int) -> str:
        """获取日志实例的当前文件路径

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            当前文件路径，失败返回空字符串

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("LogGetCurrentFilePath")
        return self.PtrToStringUTF8(func(self.OLAObject, loggerHandle))

    def LogGetCurrentFileSize(self, loggerHandle: int) -> int:
        """获取当前日志文件大小（字节）

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            文件大小（字节），失败返回 -1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogGetCurrentFileSize")
        return func(self.OLAObject, loggerHandle)

    def LogGetTotalFilesCount(self, loggerHandle: int) -> int:
        """获取日志文件总数

        Args:
            loggerHandle: 日志实例句柄（0 表示默认实例）

        Returns:
            文件数量，失败返回 -1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("LogGetTotalFilesCount")
        return func(self.OLAObject, loggerHandle)

    def DoubleToData(self, double_value: float) -> str:
        """把双精度浮点数转换成二进制形式（IEEE 754标准）

        Args:
            double_value: 需要转换的double值

        Returns:
            返回二进制字符串的指针

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("DoubleToData")
        return self.PtrToStringUTF8(func(self.OLAObject, double_value))

    def FloatToData(self, float_value: float) -> str:
        """把单精度浮点数转换成二进制形式. IEEE 754标准

        Args:
            float_value: float值

        Returns:
            返回二进制字符串的指针

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FloatToData")
        return self.PtrToStringUTF8(func(self.OLAObject, float_value))

    def StringToData(self, string_value: str, _type: int) -> str:
        """把字符串转换成二进制形式.

        Args:
            string_value: 字符串值
            _type: 字符串返回的表达类型，可选值:
                0: Ascii
                1: Unicode
                2: UTF8

        Returns:
            返回二进制字符串的指针

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("StringToData")
        return self.PtrToStringUTF8(func(self.OLAObject, string_value, _type))

    def Int64ToInt32(self, v: int) -> int:
        """把64位整数转换成32位整数.

        Args:
            v: 64位整数

        Returns:
            32位整数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Int64ToInt32")
        return func(self.OLAObject, v)

    def Int32ToInt64(self, v: int) -> int:
        """把32位整数转换成64位整数.

        Args:
            v: 32位整数

        Returns:
            64位整数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Int32ToInt64")
        return func(self.OLAObject, v)

    def FindData(self, hwnd: int, addr_range: str, data: str) -> str:
        """

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            data: 要搜索的二进制数据,支持CE数据格式 比如"00 01 23 45 * ?? ?b c? * f1"等.

        Returns:
            返回二进制字符串的指针

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindData")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, data))

    def FindDataEx(self, hwnd: int, addr_range: str, data: str, step: int, multi_thread: int, mode: int) -> str:
        """

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            data: 要搜索的二进制数据,支持CE数据格式 比如"00 01 23 45 * ?? ?b c? * f1"等.
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindDataEx")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, data, step, multi_thread, mode))

    def FindDouble(self, hwnd: int, addr_range: str, double_value_min: float, double_value_max: float) -> str:
        """搜索指定范围内的双精度浮点数.

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            double_value_min: 最小值
            double_value_max: 最大值

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindDouble")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, double_value_min, double_value_max))

    def FindDoubleEx(self, hwnd: int, addr_range: str, double_value_min: float, double_value_max: float, step: int, multi_thread: int, mode: int) -> str:
        """搜索指定范围内的双精度浮点数.

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            double_value_min: 最小值
            double_value_max: 最大值
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindDoubleEx")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, double_value_min, double_value_max, step, multi_thread, mode))

    def FindFloat(self, hwnd: int, addr_range: str, float_value_min: float, float_value_max: float) -> str:
        """搜索指定范围内的单精度浮点数.

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            float_value_min: 最小值
            float_value_max: 最大值

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindFloat")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, float_value_min, float_value_max))

    def FindFloatEx(self, hwnd: int, addr_range: str, float_value_min: float, float_value_max: float, step: int, multi_thread: int, mode: int) -> str:
        """搜索指定范围内的单精度浮点数.

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            float_value_min: 最小值
            float_value_max: 最大值
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindFloatEx")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, float_value_min, float_value_max, step, multi_thread, mode))

    def FindInt(self, hwnd: int, addr_range: str, int_value_min: int, int_value_max: int, _type: int) -> str:
        """搜索指定范围内的长整型数

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            int_value_min: 最小值
            int_value_max: 最大值
            _type: 搜索的整数类型,取值如下，可选值:
                0: 32位
                1: 16 位
                2: 8位
                3: 64位

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindInt")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, int_value_min, int_value_max, _type))

    def FindIntEx(self, hwnd: int, addr_range: str, int_value_min: int, int_value_max: int, _type: int, step: int, multi_thread: int, mode: int) -> str:
        """搜索指定范围内的长整型数

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            int_value_min: 最小值
            int_value_max: 最大值
            _type: 搜索的整数类型,取值如下，可选值:
                0: 32位
                1: 16 位
                2: 8位
                3: 64位
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindIntEx")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, int_value_min, int_value_max, _type, step, multi_thread, mode))

    def FindString(self, hwnd: int, addr_range: str, string_value: str, _type: int) -> str:
        """搜索指定范围内的字符串

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            string_value: 要搜索的字符串
            _type: 类型，可选值:
                0: 返回Ascii表达的字符串
                1: 返回Unicode表达的字符串
                2: 返回UTF8表达的字符串

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindString")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, string_value, _type))

    def FindStringEx(self, hwnd: int, addr_range: str, string_value: str, _type: int, step: int, multi_thread: int, mode: int) -> str:
        """搜索指定范围内的字符串

        Args:
            hwnd: 窗口句柄
            addr_range: 地址范围
            string_value: 要搜索的字符串
            _type: 类型，可选值:
                0: 返回Ascii表达的字符串
                1: 返回Unicode表达的字符串
                2: 返回UTF8表达的字符串
            step: 步长
            multi_thread: 是否开启多线程
            mode: 搜索模式，可选值:
                0: 搜索全部内存类型
                1: 搜索可写内存
                2: 不搜索可写内存
                4: 搜索可执行内存
                8: 不搜索可执行内存
                16: 搜索写时复制内存
                32: 不搜索写时复制内存

        Returns:
            返回二进制字符串的指针，数据格式:字符串"addr1|addr2|addr3…|addrn"比如"123456|ff001122|dc12366"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("FindStringEx")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr_range, string_value, _type, step, multi_thread, mode))

    def ReadData(self, hwnd: int, addr: str, _len: int) -> str:
        """读取指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _len: 长度

        Returns:
            返回二进制字符串的指针，数据格式:读取到的数值,以16进制表示的字符串 每个字节以空格相隔比如"12 34 56 78 ab cd ef"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("ReadData")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr, _len))

    def ReadDataAddr(self, hwnd: int, addr: int, _len: int) -> str:
        """读取指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _len: 长度

        Returns:
            返回二进制字符串的指针，数据格式:读取到的数值,以16进制表示的字符串 每个字节以空格相隔比如"12 34 56 78 ab cd ef"

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("ReadDataAddr")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr, _len))

    def ReadDataAddrToBin(self, hwnd: int, addr: int, _len: int) -> int:
        """读取指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _len: 长度

        Returns:
            读取到的数据字符串指针. 返回0表示读取失败.

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadDataAddrToBin")
        return func(self.OLAObject, hwnd, addr, _len)

    def ReadDataToBin(self, hwnd: int, addr: str, _len: int) -> int:
        """读取指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _len: 长度

        Returns:
            读取到的内存地址

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadDataToBin")
        return func(self.OLAObject, hwnd, addr, _len)

    def ReadDouble(self, hwnd: int, addr: str) -> float:
        """读取指定地址的双精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10

        Returns:
            读取到的双精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadDouble")
        return func(self.OLAObject, hwnd, addr)

    def ReadDoubleAddr(self, hwnd: int, addr: int) -> float:
        """读取指定地址的双精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址

        Returns:
            读取到的双精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadDoubleAddr")
        return func(self.OLAObject, hwnd, addr)

    def ReadFloat(self, hwnd: int, addr: str) -> float:
        """读取指定地址的单精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10

        Returns:
            读取到的单精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadFloat")
        return func(self.OLAObject, hwnd, addr)

    def ReadFloatAddr(self, hwnd: int, addr: int) -> float:
        """读取指定地址的单精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址

        Returns:
            读取到的单精度浮点数

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadFloatAddr")
        return func(self.OLAObject, hwnd, addr)

    def ReadInt(self, hwnd: int, addr: str, _type: int) -> int:
        """读取指定地址的长整型数

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号

        Returns:
            读取到的整数值64位

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadInt")
        return func(self.OLAObject, hwnd, addr, _type)

    def ReadIntAddr(self, hwnd: int, addr: int, _type: int) -> int:
        """读取指定地址的长整型数

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号

        Returns:
            读取到的整数值64位

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ReadIntAddr")
        return func(self.OLAObject, hwnd, addr, _type)

    def ReadString(self, hwnd: int, addr: str, _type: int, _len: int) -> str:
        """读取指定地址的字符串

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 类型  字符串类型,取值如下，可选值:
                0: : GBK字符串
                1: : Unicode字符串
                2: : UTF8字符串
            _len: 需要读取的字节数目.如果为0，则自动判定字符串长度.

        Returns:
            返回二进制字符串的指针，数据格式:读取到的字符串,以UTF-8编码

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("ReadString")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr, _type, _len))

    def ReadStringAddr(self, hwnd: int, addr: int, _type: int, _len: int) -> str:
        """读取指定地址的字符串

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _type: 类型  字符串类型,取值如下，可选值:
                0: GBK字符串
                1: Unicode字符串
                2: UTF8字符串
            _len: 需要读取的字节数目.如果为0，则自动判定字符串长度.

        Returns:
            返回二进制字符串的指针，数据格式:读取到的字符串,以UTF-8编码

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("ReadStringAddr")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr, _type, _len))

    def WriteData(self, hwnd: int, addr: str, data: str) -> int:
        """写入指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            data: 数据 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteData")
        return func(self.OLAObject, hwnd, addr, data)

    def WriteDataFromBin(self, hwnd: int, addr: str, data: int, _len: int) -> int:
        """写入指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            data: 字符串数据地址
            _len: 数据长度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteDataFromBin")
        return func(self.OLAObject, hwnd, addr, data, _len)

    def WriteDataAddr(self, hwnd: int, addr: int, data: str) -> int:
        """写入指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址
            data: 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteDataAddr")
        return func(self.OLAObject, hwnd, addr, data)

    def WriteDataAddrFromBin(self, hwnd: int, addr: int, data: int, _len: int) -> int:
        """写入指定地址的数据

        Args:
            hwnd: 窗口句柄
            addr: 地址
            data: 数据 二进制数据，以字符串形式描述，比如"12 34 56 78 90 ab cd"
            _len: 数据长度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteDataAddrFromBin")
        return func(self.OLAObject, hwnd, addr, data, _len)

    def WriteDouble(self, hwnd: int, addr: str, double_value: float) -> int:
        """写入指定地址的双精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            double_value: 双精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteDouble")
        return func(self.OLAObject, hwnd, addr, double_value)

    def WriteDoubleAddr(self, hwnd: int, addr: int, double_value: float) -> int:
        """写入指定地址的双精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址
            double_value: 双精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteDoubleAddr")
        return func(self.OLAObject, hwnd, addr, double_value)

    def WriteFloat(self, hwnd: int, addr: str, float_value: float) -> int:
        """写入指定地址的单精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            float_value: 单精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteFloat")
        return func(self.OLAObject, hwnd, addr, float_value)

    def WriteFloatAddr(self, hwnd: int, addr: int, float_value: float) -> int:
        """写入指定地址的单精度浮点数

        Args:
            hwnd: 窗口句柄
            addr: 地址
            float_value: 单精度浮点数

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteFloatAddr")
        return func(self.OLAObject, hwnd, addr, float_value)

    def WriteInt(self, hwnd: int, addr: str, _type: int, value: int) -> int:
        """写入指定地址的整数

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号
            value: 要写入的整数值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteInt")
        return func(self.OLAObject, hwnd, addr, _type, value)

    def WriteIntAddr(self, hwnd: int, addr: int, _type: int, value: int) -> int:
        """写入指定地址的整数

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _type: 类型，可选值:
                0: 32位有符号
                1: 16位有符号
                2: 8位有符号
                3: 64位
                4: 32位无符号
                5: 16位无符号
                6: 8位无符号
            value: 要写入的整数值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteIntAddr")
        return func(self.OLAObject, hwnd, addr, _type, value)

    def WriteString(self, hwnd: int, addr: str, _type: int, value: str) -> int:
        """写入指定地址的字符串

        Args:
            hwnd: 窗口句柄
            addr: 地址，支持CE数据格式比如：[[[<module>+offset1]+offset2]+offset3]，<Game.exe>+1234+8+4，[<Game.exe>+1234]+8+4，[[<Game.exe>+1234]+8 ]+4，<Game.exe>+1234，[0x12345678]+10
            _type: 字符串类型,取值如下，可选值:
                0: Ascii字符串
                1: Unicode字符串
                2: UTF8字符串
            value: 要写入的字符串

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteString")
        return func(self.OLAObject, hwnd, addr, _type, value)

    def WriteStringAddr(self, hwnd: int, addr: int, _type: int, value: str) -> int:
        """写入指定地址的字符串

        Args:
            hwnd: 窗口句柄
            addr: 地址
            _type: 字符串类型,取值如下，可选值:
                0: Ascii字符串
                1: Unicode字符串
                2: UTF8字符串
            value: 要写入的字符串

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("WriteStringAddr")
        return func(self.OLAObject, hwnd, addr, _type, value)

    def SetMemoryHwndAsProcessId(self, enable: int) -> int:
        """设置是否把所有内存接口函数中的窗口句柄当作进程ID

        Args:
            enable: 是否启用，可选值:
                0: 不启用
                1: 启用

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetMemoryHwndAsProcessId")
        return func(self.OLAObject, enable)

    def FreeProcessMemory(self, hwnd: int) -> int:
        """释放进程内存

        Args:
            hwnd: 窗口句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FreeProcessMemory")
        return func(self.OLAObject, hwnd)

    def GetModuleBaseAddr(self, hwnd: int, module_name: str) -> int:
        """获取模块基地址

        Args:
            hwnd: 窗口句柄
            module_name: 模块名

        Returns:
            成功返回模块基地址,失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetModuleBaseAddr")
        return func(self.OLAObject, hwnd, module_name)

    def GetModuleSize(self, hwnd: int, module_name: str) -> int:
        """获取模块大小

        Args:
            hwnd: 窗口句柄
            module_name: 模块名

        Returns:
            成功返回模块大小,失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetModuleSize")
        return func(self.OLAObject, hwnd, module_name)

    def GetRemoteApiAddress(self, hwnd: int, module_name: str, fun_name: str) -> int:
        """获取远程API地址

        Args:
            hwnd: 窗口句柄
            module_name: 模块名
            fun_name: 函数名

        Returns:
            成功返回远程API地址,失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetRemoteApiAddress")
        return func(self.OLAObject, hwnd, module_name, fun_name)

    def VirtualAllocEx(self, hwnd: int, addr: int, size: int, _type: int) -> int:
        """在指定的窗口所在进程分配一段内存

        Args:
            hwnd: 窗口句柄或者进程ID. 默认是窗口句柄.如果要指定为进程ID,需要调用SetMemoryHwndAsProcessId
            addr: 预期的分配地址。如果是0表示自动分配，否则就尝试在此地址上分配内存
            size: 需要分配的内存大小
            _type: 需要分配的内存类型，取值如下:，可选值:
                0: 可读可写可执行
                1: 可读可执行，不可写
                2: 可读可写,不可执行

        Returns:
            分配的内存地址，如果是0表示分配失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VirtualAllocEx")
        return func(self.OLAObject, hwnd, addr, size, _type)

    def VirtualFreeEx(self, hwnd: int, addr: int) -> int:
        """释放指定的内存

        Args:
            hwnd: 窗口句柄或者进程ID
            addr: 要释放的内存地址

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VirtualFreeEx")
        return func(self.OLAObject, hwnd, addr)

    def VirtualProtectEx(self, hwnd: int, addr: int, size: int, newProtect: int, oldProtect: int = None) -> Tuple[int, int]:
        """修改指定的内存保护属性

        Args:
            hwnd: 窗口句柄或者进程ID
            addr: 要修改的内存地址
            size: 需要修改的内存大小
            newProtect: 需要修改的内存类型，取值如下:，可选值:
                0x10: PAGE_EXECUTE 可执行
                0x20: PAGE_EXECUTE_READ 可读,可执行
                0x40: PAGE_READWRITE 可读可写,可执行
                0x80: PAGE_EXECUTE_WRITECOPY
            oldProtect: 修改前的保护属性

        Returns:
            返回元组: (成功返回修改之前的读写属性,失败返回-1, 修改前的保护属性)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("VirtualProtectEx")
        return func(self.OLAObject, hwnd, addr, size, newProtect, oldProtect)

    def VirtualQueryEx(self, hwnd: int, addr: int, pmbi: int) -> str:
        """查询指定的内存信息

        Args:
            hwnd: 窗口句柄或者进程ID
            addr: 要查询的内存地址
            pmbi: 内存信息结构体指针

        Returns:
            返回二进制字符串的指针，.内容是"BaseAddress,AllocationBase,AllocationProtect,RegionSize,State,Protect,Type"数值都是10进制表达

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        func = OLAPlugDLLHelper.get_function("VirtualQueryEx")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd, addr, pmbi))

    def CreateRemoteThread(self, hwnd: int, lpStartAddress: int, lpParameter: int, dwCreationFlags: int, lpThreadId: int = None) -> Tuple[int, int]:
        """在指定的窗口所在进程创建一个线程

        Args:
            hwnd: 窗口句柄或者进程ID
            lpStartAddress: 线程入口地址
            lpParameter: 线程参数
            dwCreationFlags: 创建标志
            lpThreadId: 返回线程ID

        Returns:
            返回元组: (成功返回线程句柄,失败返回0, 返回线程ID)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateRemoteThread")
        return func(self.OLAObject, hwnd, lpStartAddress, lpParameter, dwCreationFlags, lpThreadId)

    def CloseHandle(self, handle: int) -> int:
        """关闭一个内核对象

        Args:
            handle: 要关闭的对象句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CloseHandle")
        return func(self.OLAObject, handle)

    def HookRemoteApi(self, hwnd: int, targetAddr: int, size: int, hook_proc: int) -> int:
        """远程Hook API

        Args:
            hwnd: 窗口句柄或者进程ID
            targetAddr: 目标地址
            size: 大小
            hook_proc: 当前进程内回调函数地址（整型传参便于跨语言）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 支持x86和x64目标进程为X64时回调函数为HookCallback64,目标进程为X86时回调函数为HookCallback32。回调在本进程内执行。C#等可使用 Marshal.GetFunctionPointerForDelegate 传入委托地址，并保持委托引用以防被GC回收。
        """
        func = OLAPlugDLLHelper.get_function("HookRemoteApi")
        return func(self.OLAObject, hwnd, targetAddr, size, hook_proc)

    def UnhookRemoteApi(self, hwnd: int, targetAddr: int) -> int:
        """卸载远程Hook API

        Args:
            hwnd: 窗口句柄或者进程ID
            targetAddr: 目标地址

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("UnhookRemoteApi")
        return func(self.OLAObject, hwnd, targetAddr)

    def HttpDownloadFile(self, url: str, save_path: str, callback: Callable[[int, int, int, int], None], user_data: int) -> int:
        """下载文件（支持断点续传与进度）

        Args:
            url: 完整 URL
            save_path: 本地保存路径
            callback:  回调函数 void DownloadCallback(int64_t current, int64_t total, int64_t speed,int64_t user_data)
            user_data: 传给 callback 的用户数据,一般用于传递用户上下文数据

        Returns:
            错误码（OLAHttpDownloadError）：0=成功，负数=失败（参见 OLAHttpDownloadError 枚举）

        Notes:
            1. 回调参数：current 已下载字节数，total 总字节数(0 表示未知)，speed 当前下载速度(字节/秒)，user_data 由调用方传入
        """
        func = OLAPlugDLLHelper.get_function("HttpDownloadFile")
        return func(self.OLAObject, url, save_path, callback, user_data)

    def HttpDownloadFileEx(self, url: str, save_path: str, callback: Callable[[int, int, int, int], None], user_data: int, max_retries: int, connect_timeout_sec: int, read_timeout_sec: int) -> int:
        """下载文件（带重试与超时）

        Args:
            url: 完整 URL
            save_path: 本地保存路径
            callback:  回调函数 void DownloadCallback(int64_t current, int64_t total, int64_t speed,int64_t user_data)
            user_data: 传给 callback 的用户数据,一般用于传递用户上下文数据
            max_retries: 断线后最大重试次数
            connect_timeout_sec: 连接超时秒，0 用默认
            read_timeout_sec: 读超时秒，0 用默认

        Returns:
            错误码（OLAHttpDownloadError）：0=成功，负数=失败（参见 OLAHttpDownloadError 枚举）

        Notes:
            1. 回调参数：current 已下载字节数，total 总字节数(0 表示未知)，speed 当前下载速度(字节/秒)，user_data 由调用方传入
        """
        func = OLAPlugDLLHelper.get_function("HttpDownloadFileEx")
        return func(self.OLAObject, url, save_path, callback, user_data, max_retries, connect_timeout_sec, read_timeout_sec)

    def HttpGet(self, url: str) -> str:
        """发送简单 HTTP GET 请求，返回响应体字符串

        Args:
            url: 完整 URL

        Returns:
            响应体字符串指针，失败返回 0，需要调用 FreeStringPtr 释放

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("HttpGet")
        return self.PtrToStringUTF8(func(self.OLAObject, url))

    def HttpPost(self, url: str, body: str, content_type: str) -> str:
        """发送简单 HTTP POST 请求，返回响应体字符串

        Args:
            url: 完整 URL
            body: 请求体内容
            content_type: Content-Type，例如 \"application/json\"

        Returns:
            响应体字符串指针，失败返回 0，需要调用 FreeStringPtr 释放

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("HttpPost")
        return self.PtrToStringUTF8(func(self.OLAObject, url, body, content_type))

    def HttpRequestEx(self, method: str, url: str, headers: str, body: str, content_type: str, status_code: int = None) -> Tuple[str, int]:
        """高级 HTTP 请求：支持自定义 Method、请求头（含 Cookie）、请求体

        Args:
            method: 方法，如 "GET"/"POST"/"PUT"/"DELETE"，大小写不敏感
            url: 完整 URL
            headers: 自定义请求头，多行字符串，每行 "Name: Value"，如 "Cookie: a=b\r\nUser-Agent:x\r\n"，可为空
            body: 请求体，GET 可传空
            content_type: 如 "application/json"，可为空
            status_code: 输出 HTTP 状态码，可为 NULL

        Returns:
            返回元组: (响应体字符串指针，失败返回 0，需调用 FreeStringPtr 释放, 输出 HTTP 状态码，可为 NULL)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("HttpRequestEx")
        return self.PtrToStringUTF8(func(self.OLAObject, method, url, headers, body, content_type, status_code))

    def TcpClientCreate(self, callback: Callable[[int, int, int, int, int], None], user_data: int, enable_packet_protocol: int) -> int:
        """创建 TCP 客户端（基于回调的事件驱动模式）

        Args:
            callback: 事件回调函数，插件内部会自动转发所有事件到此回调 void TcpClientCallback(int64_tclient_handle, int32_t event_type, int64_t data, int32_t data_len, int64_t user_data)
            user_data: 用户自定义数据，会在回调时传回
            enable_packet_protocol: 是否启用消息分包协议：1=启用（推荐），0=禁用（原始模式）

        Returns:
            客户端句柄，失败返回 0

        Notes:
            1. 回调事件类型：0 = 连接成功1 = 连接失败2 = 接收到数据（data 指向数据，data_len 为长度）3 = 连接断开4 = 发送完成
            2. 消息分包协议格式：[4字节长度前缀(小端序)][消息体]，可自动解决粘包问题
            3. 禁用后为原始模式，可能出现粘包问题，适用于与第三方系统通信
        """
        func = OLAPlugDLLHelper.get_function("TcpClientCreate")
        return func(self.OLAObject, callback, user_data, enable_packet_protocol)

    def TcpClientConnect(self, client_handle: int, host: str, port: int) -> int:
        """连接到服务器（异步操作，结果通过回调通知）

        Args:
            client_handle: 客户端句柄
            host: 主机名或 IP
            port: 端口

        Returns:
            0 失败（参数错误等），1 开始连接（最终结果通过回调通知）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpClientConnect")
        return func(self.OLAObject, client_handle, host, port)

    def TcpClientSend(self, client_handle: int, data: int, data_len: int) -> int:
        """发送数据（异步操作）

        Args:
            client_handle: 客户端句柄
            data: 数据指针
            data_len: 数据长度

        Returns:
            0 失败，1 成功加入发送队列

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpClientSend")
        return func(self.OLAObject, client_handle, data, data_len)

    def TcpClientDisconnect(self, client_handle: int) -> int:
        """断开连接

        Args:
            client_handle: 客户端句柄

        Returns:
            0 失败，1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpClientDisconnect")
        return func(self.OLAObject, client_handle)

    def TcpClientDestroy(self, client_handle: int) -> int:
        """销毁客户端（会自动断开连接）

        Args:
            client_handle: 客户端句柄

        Returns:
            0 失败，1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpClientDestroy")
        return func(self.OLAObject, client_handle)

    def TcpServerCreate(self, bind_addr: str, port: int, callback: Callable[[int, int, int, int, int, int], None], user_data: int, enable_packet_protocol: int) -> int:
        """创建 TCP 服务端（基于回调的事件驱动模式）

        Args:
            bind_addr: 绑定地址，空或 "0.0.0.0" 表示所有接口
            port: 端口
            callback: 事件回调函数，插件内部会自动转发所有事件到此回调 void TcpServerCallback(int64_tserver_handle, int64_t conn_id, int32_t event_type, int64_t data, int32_t data_len, int64_tuser_data)
            user_data: 用户自定义数据，会在回调时传回
            enable_packet_protocol: 是否启用消息分包协议：1=启用（推荐），0=禁用（原始模式）

        Returns:
            服务端句柄，失败返回 0

        Notes:
            1. 回调事件类型：0 = 新连接（conn_id 为新连接的 ID）1 = 接收到数据（data 指向数据，data_len 为长度）2 = 连接断开（conn_id 为断开的连接 ID）3 = 发送完成
            2. 消息分包协议格式：[4字节长度前缀(小端序)][消息体]，可自动解决粘包问题
            3. 禁用后为原始模式，可能出现粘包问题，适用于与第三方系统通信
        """
        func = OLAPlugDLLHelper.get_function("TcpServerCreate")
        return func(self.OLAObject, bind_addr, port, callback, user_data, enable_packet_protocol)

    def TcpServerSend(self, server_handle: int, conn_id: int, data: int, data_len: int) -> int:
        """向指定连接发送数据

        Args:
            server_handle: 服务端句柄
            conn_id: 连接 ID（从回调中获得）
            data: 数据指针
            data_len: 数据长度

        Returns:
            0 失败，1 成功加入发送队列

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpServerSend")
        return func(self.OLAObject, server_handle, conn_id, data, data_len)

    def TcpServerDisconnect(self, server_handle: int, conn_id: int) -> int:
        """断开指定连接

        Args:
            server_handle: 服务端句柄
            conn_id: 连接 ID

        Returns:
            0 失败，1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpServerDisconnect")
        return func(self.OLAObject, server_handle, conn_id)

    def TcpServerStop(self, server_handle: int) -> int:
        """停止服务端（会断开所有连接）

        Args:
            server_handle: 服务端句柄

        Returns:
            0 失败，1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpServerStop")
        return func(self.OLAObject, server_handle)

    def TcpServerGetClientAddress(self, server_handle: int, conn_id: int) -> str:
        """获取客户端地址信息

        Args:
            server_handle: 服务端句柄
            conn_id: 连接 ID

        Returns:
            格式为 "IP:Port" 的字符串指针，失败返回 0，需要调用 FreeStringPtr 释放

        Notes:
            1. 示例返回值: "192.168.1.100:12345" 或 "[::1]:54321" (IPv6)
        """
        func = OLAPlugDLLHelper.get_function("TcpServerGetClientAddress")
        return self.PtrToStringUTF8(func(self.OLAObject, server_handle, conn_id))

    def TcpServerGetAllConnectionIds(self, server_handle: int) -> str:
        """获取所有连接的 ID 列表

        Args:
            server_handle: 服务端句柄

        Returns:
            连接 ID 列表字符串指针，需要调用 FreeStringPtr 释放

        Notes:
            1. 返回的列表字符串需要使用 FreeStringPtr 释放
            2. 示例返回值: "1,2,3"
        """
        func = OLAPlugDLLHelper.get_function("TcpServerGetAllConnectionIds")
        return self.PtrToStringUTF8(func(self.OLAObject, server_handle))

    def TcpServerDestroy(self, server_handle: int) -> int:
        """销毁服务端（会自动停止服务）

        Args:
            server_handle: 服务端句柄

        Returns:
            0 失败，1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TcpServerDestroy")
        return func(self.OLAObject, server_handle)

    def Ocr(self, x1: int, y1: int, x2: int, y2: int) -> str:
        """识别指定窗口区域内的文字

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("Ocr")
        return self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2))

    def OcrFromPtr(self, ptr: int) -> str:
        """识别指定图像中的文字

        Args:
            ptr: 图像指针

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, ptr))

    def OcrFromBmpData(self, ptr: int, size: int) -> str:
        """识别BMP数据中的文字

        Args:
            ptr: BMP图片数据流地址
            size: 图片大小

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrFromBmpData")
        return self.PtrToStringUTF8(func(self.OLAObject, ptr, size))

    def OcrDetails(self, x1: int, y1: int, x2: int, y2: int) -> dict:
        """识别指定窗口区域内的文字

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标

        Returns:
            }

        Notes:
            1. Regions集合为所有识别到的数据集 Score为识别评分,分值越高越准确, Center为识别结果中心点Size为识别范围 Angle为识别结果角度 Vertices为识别结果的4个顶点
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrDetails")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2))
        if result == "":
            return {}
        return json.loads(result)

    def OcrFromPtrDetails(self, ptr: int) -> dict:
        """识别指定图像中的文字

        Args:
            ptr: 图像指针

        Returns:
            }

        Notes:
            1. Regions集合为所有识别到的数据集 Score为识别评分,分值越高越准确, Center为识别结果中心点Size为识别范围 Angle为识别结果角度 Vertices为识别结果的4个顶点
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrFromPtrDetails")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr))
        if result == "":
            return {}
        return json.loads(result)

    def OcrFromBmpDataDetails(self, ptr: int, size: int) -> dict:
        """识别BMP数据中的文字

        Args:
            ptr: BMP图像数据指针
            size: BMP图像数据大小

        Returns:
            返回识别到的字符串

        Notes:
            1. Regions集合为所有识别到的数据集 Score为识别评分,分值越高越准确, Center为识别结果中心点Size为识别范围 Angle为识别结果角度 Vertices为识别结果的4个顶点
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrFromBmpDataDetails")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr, size))
        if result == "":
            return {}
        return json.loads(result)

    def OcrV5(self, x1: int, y1: int, x2: int, y2: int) -> str:
        """使用V5模型识别指定窗口区域内的文字

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrV5")
        return self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2))

    def OcrV5Details(self, x1: int, y1: int, x2: int, y2: int) -> dict:
        """使用V5模型识别指定窗口区域内的文字

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标

        Returns:
            }

        Notes:
            1. Regions集合为所有识别到的数据集 Score为识别评分,分值越高越准确, Center为识别结果中心点Size为识别范围 Angle为识别结果角度 Vertices为识别结果的4个顶点
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrV5Details")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2))
        if result == "":
            return {}
        return json.loads(result)

    def OcrV5FromPtr(self, ptr: int) -> str:
        """使用V5模型识别指定图像中的文字

        Args:
            ptr: 图像指针

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrV5FromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, ptr))

    def OcrV5FromPtrDetails(self, ptr: int) -> dict:
        """使用V5模型识别指定图像中的文字

        Args:
            ptr: 图像指针

        Returns:
            }

        Notes:
            1. Regions集合为所有识别到的数据集 Score为识别评分,分值越高越准确, Center为识别结果中心点Size为识别范围 Angle为识别结果角度 Vertices为识别结果的4个顶点
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("OcrV5FromPtrDetails")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr))
        if result == "":
            return {}
        return json.loads(result)

    def GetOcrConfig(self, configKey: str) -> str:
        """获取OCR配置

        Args:
            configKey: 配置键

        Returns:
            配置值

        Notes:
            1. 支持所有OCR配置参数，包括：
            2. GPU相关参数
            3. OcrUseGpu (bool): 是否使用GPU推理，false使用CPU，true使用GPU，默认false
            4. OcrUseTensorrt (bool): 是否使用TensorRT加速，默认false
            5. OcrGpuId (int): GPU设备ID，0表示第一个GPU，默认0
            6. OcrGpuMem (int): GPU内存大小(MB)，默认4000
            7. CPU相关参数
            8. OcrCpuThreads (int): CPU线程数，默认8
            9. OcrEnableMkldnn (bool): 是否启用MKL-DNN加速，默认true
            10. 推理相关参数
            11. OcrPrecision (string): 推理精度，可选fp32/fp16/int8，默认"int8"
            12. OcrBenchmark (bool): 是否启用性能基准测试，默认false
            13. OcrOutput (string): 基准测试日志保存路径，默认"./output/"
            14. OcrImageDir (string): 输入图像目录，默认""
            15. OcrType (string): 执行类型，ocr或structure，默认"ocr"
            16. 检测相关参数
            17. OcrDetModelDir (string): 检测模型路径，默认"./OCRv5_model/PP-OCRv5_mobile_det_infer/"
            18. OcrLimitType (string): 输入图像限制类型，max或min，默认"max"
            19. OcrLimitSideLen (int): 输入图像限制边长，默认960
            20. OcrDetDbThresh (double): 检测DB阈值，范围0.0-1.0，默认0.3
            21. OcrDetDbBoxThresh (double): 检测DB框阈值，范围0.0-1.0，默认0.6
            22. OcrDetDbUnclipRatio (double): 检测DB未裁剪比例，默认1.5
            23. OcrUseDilation (bool): 是否对输出图使用膨胀操作，默认false
            24. OcrDetDbScoreMode (string): 检测DB评分模式，fast或slow，默认"slow"
            25. OcrVisualize (bool): 是否显示检测结果，默认true
            26. 识别相关参数
            27. OcrRecModelDir (string): 识别模型路径，默认"./OCRv5_model/PP-OCRv5_mobile_rec_infer/"
            28. OcrRecBatchNum (int): 识别批处理数量，默认6
            29. OcrRecCharDictPath (string): 识别字符字典路径，默认"./ppocr/utils/ppocr_keys_v1.txt"
            30. OcrRecImgH (int): 识别图像高度，默认48
            31. OcrRecImgW (int): 识别图像宽度，默认320
            32. 分类相关参数
            33. OcrUseAngleCls (bool): 是否使用角度分类，默认false
            34. OcrClsModelDir (string): 分类模型路径，默认""
            35. OcrClsThresh (double): 分类阈值，范围0.0-1.0，默认0.9
            36. OcrClsBatchNum (int): 分类批处理数量，默认1
            37. 布局相关参数
            38. OcrLayoutModelDir (string): 布局模型路径，默认""
            39. OcrLayoutDictPath (string):布局字典路径，默认"./ppocr/utils/dict/layout_dict/layout_publaynet_dict.txt"
            40. OcrLayoutScoreThreshold (double): 布局评分阈值，范围0.0-1.0，默认0.5
            41. OcrLayoutNmsThreshold (double): 布局NMS阈值，范围0.0-1.0，默认0.5
            42. 表格相关参数
            43. OcrTableModelDir (string): 表格结构模型路径，默认""
            44. OcrTableMaxLen (int): 表格最大长度，默认488
            45. OcrTableBatchNum (int): 表格批处理数量，默认1
            46. OcrMergeNoSpanStructure (bool): 是否合并无跨度结构，默认true
            47. OcrTableCharDictPath (string):表格字符字典路径，默认"./ppocr/utils/dict/table_structure_dict_ch.txt"
            48. 前向相关参数
            49. OcrDet (bool): 是否使用检测，默认true
            50. OcrRec (bool): 是否使用识别，默认true
            51. OcrCls (bool): 是否使用分类，默认false
            52. OcrTable (bool): 是否使用表格结构，默认false
            53. OcrLayout (bool): 是否使用布局分析，默认false
            54. 配置值以JSON字符串形式返回，需要根据参数类型进行转换
            55. 与 SetOcrConfig 和 SetOcrConfigByKey 函数配合使用
            56. 适用于OCR配置管理和调试场景
        """
        func = OLAPlugDLLHelper.get_function("GetOcrConfig")
        return self.PtrToStringUTF8(func(self.OLAObject, configKey))

    def SetOcrConfig(self, configStr: Union[str, dict]) -> int:
        """设置OCR配置

        Args:
            configStr: 配置字符串

        Returns:
            是否成功

        Notes:
            1. 支持所有OCR配置参数，包括：
            2. GPU相关参数
            3. OcrUseGpu (bool): 是否使用GPU推理，false使用CPU，true使用GPU，默认false
            4. OcrUseTensorrt (bool): 是否使用TensorRT加速，默认false
            5. OcrGpuId (int): GPU设备ID，0表示第一个GPU，默认0
            6. OcrGpuMem (int): GPU内存大小(MB)，默认4000
            7. CPU相关参数
            8. OcrCpuThreads (int): CPU线程数，默认8
            9. OcrEnableMkldnn (bool): 是否启用MKL-DNN加速，默认true
            10. 推理相关参数
            11. OcrPrecision (string): 推理精度，可选fp32/fp16/int8，默认"int8"
            12. OcrBenchmark (bool): 是否启用性能基准测试，默认false
            13. OcrOutput (string): 基准测试日志保存路径，默认"./output/"
            14. OcrImageDir (string): 输入图像目录，默认""
            15. OcrType (string): 执行类型，ocr或structure，默认"ocr"
            16. 检测相关参数
            17. OcrDetModelDir (string): 检测模型路径，默认"./OCRv5_model/PP-OCRv5_mobile_det_infer/"
            18. OcrLimitType (string): 输入图像限制类型，max或min，默认"max"
            19. OcrLimitSideLen (int): 输入图像限制边长，默认960
            20. OcrDetDbThresh (double): 检测DB阈值，范围0.0-1.0，默认0.3
            21. OcrDetDbBoxThresh (double): 检测DB框阈值，范围0.0-1.0，默认0.6
            22. OcrDetDbUnclipRatio (double): 检测DB未裁剪比例，默认1.5
            23. OcrUseDilation (bool): 是否对输出图使用膨胀操作，默认false
            24. OcrDetDbScoreMode (string): 检测DB评分模式，fast或slow，默认"slow"
            25. OcrVisualize (bool): 是否显示检测结果，默认true
            26. 识别相关参数
            27. OcrRecModelDir (string): 识别模型路径，默认"./OCRv5_model/PP-OCRv5_mobile_rec_infer/"
            28. OcrRecBatchNum (int): 识别批处理数量，默认6
            29. OcrRecCharDictPath (string): 识别字符字典路径，默认"./ppocr/utils/ppocr_keys_v1.txt"
            30. OcrRecImgH (int): 识别图像高度，默认48
            31. OcrRecImgW (int): 识别图像宽度，默认320
            32. 分类相关参数
            33. OcrUseAngleCls (bool): 是否使用角度分类，默认false
            34. OcrClsModelDir (string): 分类模型路径，默认""
            35. OcrClsThresh (double): 分类阈值，范围0.0-1.0，默认0.9
            36. OcrClsBatchNum (int): 分类批处理数量，默认1
            37. 布局相关参数
            38. OcrLayoutModelDir (string): 布局模型路径，默认""
            39. OcrLayoutDictPath (string):布局字典路径，默认"./ppocr/utils/dict/layout_dict/layout_publaynet_dict.txt"
            40. OcrLayoutScoreThreshold (double): 布局评分阈值，范围0.0-1.0，默认0.5
            41. OcrLayoutNmsThreshold (double): 布局NMS阈值，范围0.0-1.0，默认0.5
            42. 表格相关参数
            43. OcrTableModelDir (string): 表格结构模型路径，默认""
            44. OcrTableMaxLen (int): 表格最大长度，默认488
            45. OcrTableBatchNum (int): 表格批处理数量，默认1
            46. OcrMergeNoSpanStructure (bool): 是否合并无跨度结构，默认true
            47. OcrTableCharDictPath (string):表格字符字典路径，默认"./ppocr/utils/dict/table_structure_dict_ch.txt"
            48. 前向相关参数
            49. OcrDet (bool): 是否使用检测，默认true
            50. OcrRec (bool): 是否使用识别，默认true
            51. OcrCls (bool): 是否使用分类，默认false
            52. OcrTable (bool): 是否使用表格结构，默认false
            53. OcrLayout (bool): 是否使用布局分析，默认false
            54. 配置值以JSON字符串形式返回，需要根据参数类型进行转换
            55. 与 SetOcrConfig 和 SetOcrConfigByKey 函数配合使用
            56. 适用于OCR配置管理和调试场景
        """
        if not isinstance(configStr, str):
            configStr = json.dumps(configStr)
        func = OLAPlugDLLHelper.get_function("SetOcrConfig")
        return func(self.OLAObject, configStr)

    def SetOcrConfigByKey(self, key: str, value: str) -> int:
        """设置OCR配置

        Args:
            key: 配置键
            value: 配置值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 支持所有OCR配置参数，包括：
            2. GPU相关参数
            3. OcrUseGpu (bool): 是否使用GPU推理，false使用CPU，true使用GPU，默认false
            4. OcrUseTensorrt (bool): 是否使用TensorRT加速，默认false
            5. OcrGpuId (int): GPU设备ID，0表示第一个GPU，默认0
            6. OcrGpuMem (int): GPU内存大小(MB)，默认4000
            7. CPU相关参数
            8. OcrCpuThreads (int): CPU线程数，默认8
            9. OcrEnableMkldnn (bool): 是否启用MKL-DNN加速，默认true
            10. 推理相关参数
            11. OcrPrecision (string): 推理精度，可选fp32/fp16/int8，默认"int8"
            12. OcrBenchmark (bool): 是否启用性能基准测试，默认false
            13. OcrOutput (string): 基准测试日志保存路径，默认"./output/"
            14. OcrImageDir (string): 输入图像目录，默认""
            15. OcrType (string): 执行类型，ocr或structure，默认"ocr"
            16. 检测相关参数
            17. OcrDetModelDir (string): 检测模型路径，默认"./OCRv5_model/PP-OCRv5_mobile_det_infer/"
            18. OcrLimitType (string): 输入图像限制类型，max或min，默认"max"
            19. OcrLimitSideLen (int): 输入图像限制边长，默认960
            20. OcrDetDbThresh (double): 检测DB阈值，范围0.0-1.0，默认0.3
            21. OcrDetDbBoxThresh (double): 检测DB框阈值，范围0.0-1.0，默认0.6
            22. OcrDetDbUnclipRatio (double): 检测DB未裁剪比例，默认1.5
            23. OcrUseDilation (bool): 是否对输出图使用膨胀操作，默认false
            24. OcrDetDbScoreMode (string): 检测DB评分模式，fast或slow，默认"slow"
            25. OcrVisualize (bool): 是否显示检测结果，默认true
            26. 识别相关参数
            27. OcrRecModelDir (string): 识别模型路径，默认"./OCRv5_model/PP-OCRv5_mobile_rec_infer/"
            28. OcrRecBatchNum (int): 识别批处理数量，默认6
            29. OcrRecCharDictPath (string): 识别字符字典路径，默认"./ppocr/utils/ppocr_keys_v1.txt"
            30. OcrRecImgH (int): 识别图像高度，默认48
            31. OcrRecImgW (int): 识别图像宽度，默认320
            32. 分类相关参数
            33. OcrUseAngleCls (bool): 是否使用角度分类，默认false
            34. OcrClsModelDir (string): 分类模型路径，默认""
            35. OcrClsThresh (double): 分类阈值，范围0.0-1.0，默认0.9
            36. OcrClsBatchNum (int): 分类批处理数量，默认1
            37. 布局相关参数
            38. OcrLayoutModelDir (string): 布局模型路径，默认""
            39. OcrLayoutDictPath (string):布局字典路径，默认"./ppocr/utils/dict/layout_dict/layout_publaynet_dict.txt"
            40. OcrLayoutScoreThreshold (double): 布局评分阈值，范围0.0-1.0，默认0.5
            41. OcrLayoutNmsThreshold (double): 布局NMS阈值，范围0.0-1.0，默认0.5
            42. 表格相关参数
            43. OcrTableModelDir (string): 表格结构模型路径，默认""
            44. OcrTableMaxLen (int): 表格最大长度，默认488
            45. OcrTableBatchNum (int): 表格批处理数量，默认1
            46. OcrMergeNoSpanStructure (bool): 是否合并无跨度结构，默认true
            47. OcrTableCharDictPath (string):表格字符字典路径，默认"./ppocr/utils/dict/table_structure_dict_ch.txt"
            48. 前向相关参数
            49. OcrDet (bool): 是否使用检测，默认true
            50. OcrRec (bool): 是否使用识别，默认true
            51. OcrCls (bool): 是否使用分类，默认false
            52. OcrTable (bool): 是否使用表格结构，默认false
            53. OcrLayout (bool): 是否使用布局分析，默认false
            54. 配置值以JSON字符串形式返回，需要根据参数类型进行转换
            55. 与 SetOcrConfig 和 SetOcrConfigByKey 函数配合使用
            56. 适用于OCR配置管理和调试场景
        """
        func = OLAPlugDLLHelper.get_function("SetOcrConfigByKey")
        return func(self.OLAObject, key, value)

    def OcrFromDict(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], dict_name: str, matchVal: float) -> str:
        """从字库中识别文字

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            colorJson: 颜色json
            dict_name: 字库名称
            matchVal: 匹配值

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("OcrFromDict")
        return self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, dict_name, matchVal))

    def OcrFromDictDetails(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], dict_name: str, matchVal: float) -> dict:
        """从字库中识别文字

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            colorJson: 颜色json
            dict_name: 字库名称
            matchVal: 匹配值

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("OcrFromDictDetails")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, dict_name, matchVal))
        if result == "":
            return {}
        return json.loads(result)

    def OcrFromDictPtr(self, ptr: int, colorJson: Union[str, List[dict]], dict_name: str, matchVal: float) -> str:
        """从字库中识别文字

        Args:
            ptr: 图像指针
            colorJson: 颜色json
            dict_name: 字库名称
            matchVal: 匹配值

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("OcrFromDictPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, ptr, colorJson, dict_name, matchVal))

    def OcrFromDictPtrDetails(self, ptr: int, colorJson: Union[str, List[dict]], dict_name: str, matchVal: float) -> dict:
        """从字库中识别文字

        Args:
            ptr: 图像指针
            colorJson: 颜色json
            dict_name: 字库名称
            matchVal: 匹配值

        Returns:
            识别到的文字(二进制字符串的指针)

        Notes:
            1. 返回的字符串指针需调用FreeStringPtr释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("OcrFromDictPtrDetails")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr, colorJson, dict_name, matchVal))
        if result == "":
            return {}
        return json.loads(result)

    def FindStr(self, x1: int, y1: int, x2: int, y2: int, _str: str, colorJson: Union[str, List[dict]], _dict: str, matchVal: float, outX: int = None, outY: int = None) -> Tuple[int, int, int]:
        """查找文字

        Args:
            x1: 查找区域的左上角X坐标
            y1: 查找区域的左上角Y坐标
            x2: 查找区域的右下角X坐标
            y2: 查找区域的右下角Y坐标
            _str: 要查找的文字
            colorJson: 颜色列表的json字符串
            _dict: 字典名称
            matchVal: 相似度，如0.85，最大为1
            outX: 输出参数，返回的X坐标
            outY: 输出参数，返回的Y坐标

        Returns:
            返回元组: (操作结果, 输出参数，返回的X坐标, 输出参数，返回的Y坐标)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FindStr")
        return func(self.OLAObject, x1, y1, x2, y2, _str, colorJson, _dict, matchVal, outX, outY)

    def FindStrDetail(self, x1: int, y1: int, x2: int, y2: int, _str: str, colorJson: Union[str, List[dict]], _dict: str, matchVal: float) -> dict:
        """查找指定文字的坐标

        Args:
            x1: 查找区域的左上角X坐标
            y1: 查找区域的左上角Y坐标
            x2: 查找区域的右下角X坐标
            y2: 查找区域的右下角Y坐标
            _str: 要查找的文字
            colorJson: 颜色列表的json字符串
            _dict: 字典名称
            matchVal: 相似度，如0.85，最大为1

        Returns:
            y (整型数): Y坐标

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FindStrDetail")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, _str, colorJson, _dict, matchVal))
        if result == "":
            return {}
        return json.loads(result)

    def FindStrAll(self, x1: int, y1: int, x2: int, y2: int, _str: str, colorJson: Union[str, List[dict]], _dict: str, matchVal: float) -> List[dict]:
        """查找文字返回全部结果

        Args:
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            _str: 查找字符串
            colorJson: 颜色列表的JSON字符串，格式如：[{"StartColor": "3278FA", "EndColor": "6496FF","Type": 0}, {"StartColor": "3278FA", "EndColor": "6496FF", "Type": 1}]
            _dict: 字库名称
            matchVal: 匹配值

        Returns:
            ]

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FindStrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, _str, colorJson, _dict, matchVal))
        if result == "":
            return []
        return json.loads(result)

    def FindStrFromPtr(self, source: int, _str: str, colorJson: Union[str, List[dict]], _dict: str, matchVal: float) -> dict:
        """查找图片中的文字

        Args:
            source: 图片
            _str: 查找字符串
            colorJson: 颜色列表的JSON字符串，格式如：[{"StartColor": "3278FA", "EndColor": "6496FF","Type": 0}, {"StartColor": "3278FA", "EndColor": "6496FF", "Type": 1}]
            _dict: 字库名称
            matchVal: 匹配值

        Returns:
            查找到的结果（格式为二进制字符串指针）

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FindStrFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, _str, colorJson, _dict, matchVal))
        if result == "":
            return {}
        return json.loads(result)

    def FindStrFromPtrAll(self, source: int, _str: str, colorJson: Union[str, List[dict]], _dict: str, matchVal: float) -> List[dict]:
        """查找文字返回全部结果

        Args:
            source: 图片
            _str: 查找字符串
            colorJson: 颜色列表的JSON字符串，格式如：[{"StartColor": "3278FA", "EndColor": "6496FF","Type": 0}, {"StartColor": "3278FA", "EndColor": "6496FF", "Type": 1}]
            _dict: 字库名称
            matchVal: 匹配值

        Returns:
            ]

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FindStrFromPtrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, _str, colorJson, _dict, matchVal))
        if result == "":
            return []
        return json.loads(result)

    def FastNumberOcrFromPtr(self, source: int, numbers: str, colorJson: Union[str, List[dict]], matchVal: float) -> int:
        """快速识别数字

        Args:
            source: 图片
            numbers: 0~9数字图片地址,多个数字用|分割,如img/0.png|img/1.png|img/2.png|img/3.png|img/4.png|img/5.png|img/6.png|img/7.png|img/8.png|img/9.png
            colorJson: 颜色json
            matchVal: 识别率

        Returns:
            识别到的数字,如果失败返回-1

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FastNumberOcrFromPtr")
        return func(self.OLAObject, source, numbers, colorJson, matchVal)

    def FastNumberOcr(self, x1: int, y1: int, x2: int, y2: int, numbers: str, colorJson: Union[str, List[dict]], matchVal: float) -> int:
        """快速识别数字

        Args:
            x1: 图片
            y1: 区域左上角Y坐标
            x2: 区域右下角X坐标
            y2: 区域右下角Y坐标
            numbers: 0~9数字图片地址,多个数字用|分割,如img/0.png|img/1.png|img/2.png|img/3.png|img/4.png|img/5.png|img/6.png|img/7.png|img/8.png|img/9.png
            colorJson: 颜色json
            matchVal: 识别率

        Returns:
            识别到的数字,如果失败返回-1

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("FastNumberOcr")
        return func(self.OLAObject, x1, y1, x2, y2, numbers, colorJson, matchVal)

    def ImportTxtDict(self, dictName: str, dictPath: str) -> int:
        """

        Args:
            dictName: 字库名称
            dictPath: 文本字库路径

        Returns:
            是否成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImportTxtDict")
        return func(self.OLAObject, dictName, dictPath)

    def ExportTxtDict(self, dictName: str, dictPath: str) -> int:
        """导出txt文本字库

        Args:
            dictName: 字库名称
            dictPath: 文本字库路径

        Returns:
            是否成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ExportTxtDict")
        return func(self.OLAObject, dictName, dictPath)

    def Capture(self, x1: int, y1: int, x2: int, y2: int, file: str) -> int:
        """对绑定窗口在指定区域进行截图并保存为图片

        Args:
            x1: 截图区域左上角X坐标（相对于窗口客户区）
            y1: 截图区域左上角Y坐标（相对于窗口客户区）
            x2: 截图区域右下角X坐标（相对于窗口客户区）
            y2: 截图区域右下角Y坐标（相对于窗口客户区）
            file: 输出文件路径，支持bmp/gif/jpg/jpeg/png

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 若目录不存在请确保先行创建；覆盖同名文件
        """
        func = OLAPlugDLLHelper.get_function("Capture")
        return func(self.OLAObject, x1, y1, x2, y2, file)

    def GetScreenDataBmp(self, x1: int, y1: int, x2: int, y2: int, data: int = None, dataLen: int = None) -> Tuple[int, int, int]:
        """获取绑定窗口指定区域的BMP原始数据

        Args:
            x1: 区域左上角X坐标（相对于窗口客户区）
            y1: 区域左上角Y坐标（相对于窗口客户区）
            x2: 区域右下角X坐标（相对于窗口客户区）
            y2: 区域右下角Y坐标（相对于窗口客户区）
            data: 返回BMP数据指针（输出）
            dataLen: 返回数据字节长度（输出）

        Returns:
            返回元组: (操作结果, 返回BMP数据指针（输出）, 返回数据字节长度（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. data需调用FreeImageData释放；数据包含完整BMP文件头，可直接落盘
        """
        func = OLAPlugDLLHelper.get_function("GetScreenDataBmp")
        return func(self.OLAObject, x1, y1, x2, y2, data, dataLen)

    def GetScreenData(self, x1: int, y1: int, x2: int, y2: int, data: int = None, dataLen: int = None, stride: int = None) -> Tuple[int, int, int, int]:
        """获取绑定窗口指定区域的RGB原始数据

        Args:
            x1: 区域左上角X坐标（相对于窗口客户区）
            y1: 区域左上角Y坐标（相对于窗口客户区）
            x2: 区域右下角X坐标（相对于窗口客户区）
            y2: 区域右下角Y坐标（相对于窗口客户区）
            data: 返回像素数据指针（输出，BGR顺序）
            dataLen: 返回数据字节长度（输出）
            stride: 返回每行对齐后的字节跨度（输出）

        Returns:
            返回元组: (操作结果, 返回像素数据指针（输出，BGR顺序）, 返回数据字节长度（输出）, 返回每行对齐后的字节跨度（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. data需调用FreeImageData释放；无文件头，按4字节边界对齐
        """
        func = OLAPlugDLLHelper.get_function("GetScreenData")
        return func(self.OLAObject, x1, y1, x2, y2, data, dataLen, stride)

    def GetScreenDataPtr(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """获取绑定窗口指定区域的图像数据句柄

        Args:
            x1: 区域左上角X坐标（相对于窗口客户区）
            y1: 区域左上角Y坐标（相对于窗口客户区）
            x2: 区域右下角X坐标（相对于窗口客户区）
            y2: 区域右下角Y坐标（相对于窗口客户区）

        Returns:
            返回内部缓存的图像句柄；失败返回0

        Notes:
            1. 返回图像句柄,在不使用的时候需要手动释放
        """
        func = OLAPlugDLLHelper.get_function("GetScreenDataPtr")
        return func(self.OLAObject, x1, y1, x2, y2)

    def CaptureGif(self, x1: int, y1: int, x2: int, y2: int, file: str, delay: int, time: int) -> int:
        """录制绑定窗口指定区域为GIF动画

        Args:
            x1: 区域左上角X坐标（相对于窗口客户区）
            y1: 区域左上角Y坐标（相对于窗口客户区）
            x2: 区域右下角X坐标（相对于窗口客户区）
            y2: 区域右下角Y坐标（相对于窗口客户区）
            file: 输出GIF文件路径
            delay: 帧间隔（毫秒）
            time: 录制总时长（毫秒）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 持续截图编码，性能开销较大
        """
        func = OLAPlugDLLHelper.get_function("CaptureGif")
        return func(self.OLAObject, x1, y1, x2, y2, file, delay, time)

    def LockDisplay(self, enable: int) -> int:
        """锁定当前屏幕图像

        Args:
            enable: 锁定标志，可选值:
                0: 取消锁定，清空锁定图像并释放内存
                非0: 锁定当前屏幕图像，后续截图将返回锁定的图像

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 锁定后，CaptureMat等截图接口将返回锁定的图像数据
        """
        func = OLAPlugDLLHelper.get_function("LockDisplay")
        return func(self.OLAObject, enable)

    def SetSnapCacheTime(self, cacheTime: int) -> int:
        """设置截图缓存时间

        Args:
            cacheTime: 缓存时间（毫秒），可选值:
                0: 不缓存，实时截图
                >0: 缓存截图到指定的毫秒数，在缓存时间内返回缓存的图像

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 设置缓存后，在缓存时间内多次截图将返回同一帧图像，提高性能
        """
        func = OLAPlugDLLHelper.get_function("SetSnapCacheTime")
        return func(self.OLAObject, cacheTime)

    def GetImageData(self, imgPtr: int, data: int = None, size: int = None, stride: int = None) -> Tuple[int, int, int, int]:
        """从图像句柄读取像素数据

        Args:
            imgPtr: 图像句柄（由加载/生成接口返回）
            data: 返回像素数据指针（输出，BGR顺序）
            size: 返回数据字节长度（输出）
            stride: 返回每行字节跨度（输出）

        Returns:
            返回元组: (操作结果, 返回像素数据指针（输出，BGR顺序）, 返回数据字节长度（输出）, 返回每行字节跨度（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. data需调用FreeImageData释放
        """
        func = OLAPlugDLLHelper.get_function("GetImageData")
        return func(self.OLAObject, imgPtr, data, size, stride)

    def MatchImageFromPath(self, source: str, templ: str, matchVal: float, _type: int, angle: float, scale: float) -> dict:
        """使用文件路径在源图中匹配模板图

        Args:
            source: 源图路径
            templ: 模板图路径
            matchVal: 匹配阈值（0~1）
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度（度）
            scale: 缩放比例

        Returns:
            匹配结果（结构体/指针，失败返回0）

        Notes:
            1. 实现取决于type/angle/scale的组合策略
        """
        func = OLAPlugDLLHelper.get_function("MatchImageFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, matchVal, _type, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchImageFromPathAll(self, source: str, templ: str, matchVal: float, _type: int, angle: float, scale: float) -> List[dict]:
        """使用文件路径在源图中查找模板图的所有匹配

        Args:
            source: 源图路径
            templ: 模板图路径
            matchVal: 匹配阈值（0~1）
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度（度）
            scale: 缩放比例

        Returns:
            匹配点列表字符串指针；未找到返回空字符串指针

        Notes:
            1. 返回字符串需调用FreeStringPtr释放
        """
        func = OLAPlugDLLHelper.get_function("MatchImageFromPathAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, matchVal, _type, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def MatchImagePtrFromPath(self, source: int, templ: str, matchVal: float, _type: int, angle: float, scale: float) -> dict:
        """使用内存源图与文件模板进行匹配

        Args:
            source: 源图句柄
            templ: 模板图路径
            matchVal: 匹配阈值（0~1）
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度（度）
            scale: 缩放比例

        Returns:
            匹配结果（结构体/指针，失败返回0）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchImagePtrFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, matchVal, _type, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchImagePtrFromPathAll(self, source: int, templ: str, matchVal: float, _type: int, angle: float, scale: float) -> List[dict]:
        """使用内存源图与文件模板查找所有匹配

        Args:
            source: 源图句柄
            templ: 模板图路径
            matchVal: 匹配阈值（0~1）
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度（度）
            scale: 缩放比例

        Returns:
            匹配点列表字符串指针；未找到返回空字符串指针

        Notes:
            1. 返回字符串需调用FreeStringPtr释放
        """
        func = OLAPlugDLLHelper.get_function("MatchImagePtrFromPathAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, matchVal, _type, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def GetColor(self, x: int, y: int) -> str:
        """获取绑定窗口指定坐标点的颜色值

        Args:
            x: 指定点的X坐标（相对于窗口客户区）
            y: 指定点的Y坐标（相对于窗口客户区）

        Returns:
            返回颜色值（BGR格式的整数），失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetColor")
        return self.PtrToStringUTF8(func(self.OLAObject, x, y))

    def GetColorPtr(self, source: int, x: int, y: int) -> str:
        """获取绑定窗口指定坐标点的颜色值（返回指针）

        Args:
            source: 源对象的指针，通常是一个图像或画布对象
            x: 指定点的X坐标（相对于窗口客户区）
            y: 指定点的Y坐标（相对于窗口客户区）

        Returns:
            返回指向颜色值的指针，数据在内部缓存中；失败返回0

        Notes:
            1. 返回的指针指向内部缓存，不应手动释放；数据为BGR三个字节
        """
        func = OLAPlugDLLHelper.get_function("GetColorPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, source, x, y))

    def CopyImage(self, sourcePtr: int) -> int:
        """复制一份图像数据

        Args:
            sourcePtr: 原始图像句柄

        Returns:
            返回新图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CopyImage")
        return func(self.OLAObject, sourcePtr)

    def FreeImagePath(self, path: str) -> int:
        """释放由MatchImageFromPath等接口产生的图片路径相关资源

        Args:
            path: 图片路径字符串指针

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于释放由MatchImageFromPathAll等返回的字符串资源
        """
        func = OLAPlugDLLHelper.get_function("FreeImagePath")
        return func(self.OLAObject, path)

    def FreeImageAll(self) -> int:
        """释放所有已加载的图像资源

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 调用后所有已加载的图像数据指针将失效
        """
        func = OLAPlugDLLHelper.get_function("FreeImageAll")
        return func(self.OLAObject)

    def LoadImage(self, path: str) -> int:
        """加载图片文件到内存

        Args:
            path: 图片文件路径

        Returns:
            返回图像句柄，失败返回0

        Notes:
            1. 加载后的图像可用于后续的图像匹配等操作
        """
        func = OLAPlugDLLHelper.get_function("LoadImage")
        return func(self.OLAObject, path)

    def LoadImageFromBmpData(self, data: int, dataSize: int) -> int:
        """从BMP数据加载图像

        Args:
            data: BMP格式的数据指针
            dataSize: 数据字节长度

        Returns:
            返回图像句柄，失败返回0

        Notes:
            1. 数据必须包含完整的BMP文件头
        """
        func = OLAPlugDLLHelper.get_function("LoadImageFromBmpData")
        return func(self.OLAObject, data, dataSize)

    def LoadImageFromRGBData(self, width: int, height: int, scan0: int, stride: int) -> int:
        """从RGB数据加载图像

        Args:
            width: 图像宽度
            height: 图像高度
            scan0: 像素数据首地址（BGR顺序）
            stride: 每行字节跨度

        Returns:
            返回图像句柄，失败返回0

        Notes:
            1. 数据为连续的BGR三通道数据，每行字节对齐到4字节边界
        """
        func = OLAPlugDLLHelper.get_function("LoadImageFromRGBData")
        return func(self.OLAObject, width, height, scan0, stride)

    def FreeImagePtr(self, screenPtr: int) -> int:
        """释放由GetImageData等接口返回的图像数据指针

        Args:
            screenPtr: 图像句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FreeImagePtr")
        return func(self.OLAObject, screenPtr)

    def MatchWindowsFromPtr(self, x1: int, y1: int, x2: int, y2: int, templ: int, matchVal: float, _type: int, angle: float, scale: float) -> dict:
        """在绑定窗口中查找指定窗口图像（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchWindowsFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, matchVal, _type, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchImageFromPtr(self, source: int, templ: int, matchVal: float, _type: int, angle: float, scale: float) -> dict:
        """在指定图片中查找指定图像（使用内存数据）

        Args:
            source: OLAImage对象的地址
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchImageFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, matchVal, _type, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchImageFromPtrAll(self, source: int, templ: int, matchVal: float, _type: int, angle: float, scale: float) -> List[dict]:
        """在指定图片中查找指定图像的所有匹配位置（使用内存数据）

        Args:
            source: OLAImage对象的地址
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            返回所有匹配结果字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchImageFromPtrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, matchVal, _type, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def MatchWindowsFromPtrAll(self, x1: int, y1: int, x2: int, y2: int, templ: int, matchVal: float, _type: int, angle: float, scale: float) -> List[dict]:
        """在绑定窗口中查找指定窗口图像的所有匹配位置（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            返回所有匹配点结果的字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchWindowsFromPtrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, matchVal, _type, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def MatchWindowsFromPath(self, x1: int, y1: int, x2: int, y2: int, templ: str, matchVal: float, _type: int, angle: float, scale: float) -> dict:
        """在绑定窗口中查找指定窗口图像（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: 模板图片的路径，可以是多个图片,比如"test.bmp|test2.bmp|test3.bmp"
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchWindowsFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, matchVal, _type, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchWindowsFromPathAll(self, x1: int, y1: int, x2: int, y2: int, templ: str, matchVal: float, _type: int, angle: float, scale: float) -> List[dict]:
        """在绑定窗口中查找指定窗口图像的所有匹配位置（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: 模板图片的路径，可以是多个图片,比如"test.bmp|test2.bmp|test3.bmp"
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            返回所有匹配结果的字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MatchWindowsFromPathAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, matchVal, _type, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def MatchWindowsThresholdFromPtr(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], templ: int, matchVal: float, angle: float, scale: float) -> dict:
        """在绑定窗口中使用阈值匹配查找指定窗口图像（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel。
            templ: 窗口模板图句柄
            matchVal: 相似度，如0.85，最大为1
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            匹配结果
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("MatchWindowsThresholdFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, templ, matchVal, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchWindowsThresholdFromPtrAll(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], templ: int, matchVal: float, angle: float, scale: float) -> List[dict]:
        """在绑定窗口中使用阈值匹配查找指定窗口图像的所有匹配位置（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel。
            templ: 窗口模板图句柄
            matchVal: 相似度，如0.85，最大为1
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("MatchWindowsThresholdFromPtrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, templ, matchVal, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def MatchWindowsThresholdFromPath(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], templ: str, matchVal: float, angle: float, scale: float) -> dict:
        """在绑定窗口中使用阈值匹配查找指定窗口图像（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel。
            templ: 图像文件路径
            matchVal: 相似度，如0.85，最大为1
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            匹配结果
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("MatchWindowsThresholdFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, templ, matchVal, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def MatchWindowsThresholdFromPathAll(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], templ: str, matchVal: float, angle: float, scale: float) -> List[dict]:
        """在绑定窗口中使用阈值匹配查找指定窗口图像的所有匹配位置（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel。
            templ: 图像文件路径
            matchVal: 相似度，如0.85，最大为1
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放

        Returns:
            

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("MatchWindowsThresholdFromPathAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, templ, matchVal, angle, scale))
        if result == "":
            return []
        return json.loads(result)

    def ShowMatchWindow(self, flag: int) -> int:
        """显示/隐藏匹配结果可视化或调试窗口

        Args:
            flag: 显示标志（0 关闭，1 打开）

        Returns:
            操作结果，0 失败，1 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ShowMatchWindow")
        return func(self.OLAObject, flag)

    def CalculateSSIM(self, image1: int, image2: int) -> float:
        """计算两幅图像的结构相似性指数（SSIM）

        Args:
            image1: 第一幅图像句柄
            image2: 第二幅图像句柄

        Returns:
            SSIM值（0~1），越接近1越相似

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CalculateSSIM")
        return func(self.OLAObject, image1, image2)

    def CalculateHistograms(self, image1: int, image2: int) -> float:
        """计算两幅图像直方图的相似度

        Args:
            image1: 图像1句柄
            image2: 图像2句柄

        Returns:
            直方图相似度（0~1）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CalculateHistograms")
        return func(self.OLAObject, image1, image2)

    def CalculateMSE(self, image1: int, image2: int) -> float:
        """计算两幅图像的均方误差（MSE）

        Args:
            image1: 第一幅图像句柄
            image2: 第二幅图像句柄

        Returns:
            MSE值，越小越相似

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CalculateMSE")
        return func(self.OLAObject, image1, image2)

    def SaveImageFromPtr(self, ptr: int, path: str) -> int:
        """将内存图像保存为文件

        Args:
            ptr: 图像句柄
            path: 输出文件路径，支持bmp/gif/jpg/jpeg/png

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SaveImageFromPtr")
        return func(self.OLAObject, ptr, path)

    def ReSize(self, ptr: int, width: int, height: int) -> int:
        """调整图像大小

        Args:
            ptr: 原始图像句柄
            width: 目标宽度
            height: 目标高度

        Returns:
            新图像句柄，失败返回0

        Notes:
            1. 使用双线性插值进行缩放
        """
        func = OLAPlugDLLHelper.get_function("ReSize")
        return func(self.OLAObject, ptr, width, height)

    def FindColor(self, x1: int, y1: int, x2: int, y2: int, color1: str, color2: str, _dir: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在绑定窗口中查找指定颜色

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            color1: 要查找的颜色值（BGR格式）
            color2: 要查找的颜色值（BGR格式）
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左
            x: 返回找到的颜色点X坐标
            y: 返回找到的颜色点Y坐标

        Returns:
            返回元组: (查找结果, 返回找到的颜色点X坐标, 返回找到的颜色点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindColor")
        return func(self.OLAObject, x1, y1, x2, y2, color1, color2, _dir, x, y)

    def FindColorList(self, x1: int, y1: int, x2: int, y2: int, color1: str, color2: str) -> List[dict]:
        """在绑定窗口中查找指定颜色列表

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            color1: 颜色起始范围，颜色格式 RRGGBB
            color2: 颜色结束范围，颜色格式 RRGGBB

        Returns:
            查找结果返回所有匹配点坐标的字符串，格式为"["x":10,"y":20],"[x":30,"y":40]"；未找到返回空字符串指针，需调用FreeStringPtr释放内存

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindColorList")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, color1, color2))
        if result == "":
            return []
        return json.loads(result)

    def FindColorEx(self, x1: int, y1: int, x2: int, y2: int, colorJson: str, _dir: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在绑定窗口中查找指定颜色

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色范围定义（JSON）
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左
            x: 返回找到的颜色点X坐标
            y: 返回找到的颜色点Y坐标

        Returns:
            返回元组: (查找结果, 返回找到的颜色点X坐标, 返回找到的颜色点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindColorEx")
        return func(self.OLAObject, x1, y1, x2, y2, colorJson, _dir, x, y)

    def FindColorListEx(self, x1: int, y1: int, x2: int, y2: int, colorJson: str) -> List[dict]:
        """在绑定窗口中查找指定颜色列表

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色范围定义（JSON）

        Returns:
            查找结果返回所有匹配点坐标的字符串，格式为"["x":10,"y":20],"[x":30,"y":40]"；未找到返回空字符串指针，需调用FreeStringPtr释放内存

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindColorListEx")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson))
        if result == "":
            return []
        return json.loads(result)

    def CmpMultiColor(self, pointJson: Union[str, List[dict]], sim: float) -> int:
        """在绑定窗口中对比多色点

        Args:
            pointJson: 点阵颜色列表，支持JSON格式或简化字符串格式，格式说明见 点阵颜色列表格式说明- PointColorListFormat
            sim: 相似度阈值，范围0-1.0，默认1.0

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("CmpMultiColor")
        return func(self.OLAObject, pointJson, sim)

    def CmpMultiColorPtr(self, image: int, pointJson: Union[str, List[dict]], sim: float) -> int:
        """在指定图片中对比多色点

        Args:
            image: 图像句柄
            pointJson: 点阵颜色列表，支持JSON格式或简化字符串格式，格式说明见 点阵颜色列表格式说明- PointColorListFormat
            sim: 相似度阈值，范围0-1.0，默认1.0

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("CmpMultiColorPtr")
        return func(self.OLAObject, image, pointJson, sim)

    def FindMultiColor(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], pointJson: Union[str, List[dict]], sim: float, _dir: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在绑定窗口中查找多色点

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel
            pointJson: 点阵颜色列表，支持JSON格式或简化字符串格式，格式说明见 点阵颜色列表格式说明- PointColorListFormat
            sim: 相似度阈值，范围0-1.0，默认1.0
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左
            x: 返回找到的颜色点X坐标
            y: 返回找到的颜色点Y坐标

        Returns:
            返回元组: (查找结果, 返回找到的颜色点X坐标, 返回找到的颜色点Y坐标)
            查找结果:
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("FindMultiColor")
        return func(self.OLAObject, x1, y1, x2, y2, colorJson, pointJson, sim, _dir, x, y)

    def FindMultiColorList(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]], pointJson: Union[str, List[dict]], sim: float) -> List[dict]:
        """在绑定窗口中查找多色点列表

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel
            pointJson: 点阵颜色列表，支持JSON格式或简化字符串格式，格式说明见 点阵颜色列表格式说明 -PointColorListFormat
            sim: 相似度阈值，范围0-1.0，默认1.0

        Returns:
            返回识别到的坐标点列表的JSON字符串

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("FindMultiColorList")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorJson, pointJson, sim))
        if result == "":
            return []
        return json.loads(result)

    def FindMultiColorFromPtr(self, ptr: int, colorJson: Union[str, List[dict]], pointJson: Union[str, List[dict]], sim: float, _dir: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在内存图像中查找多色点

        Args:
            ptr: 图像句柄
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel
            pointJson: 点阵颜色列表，支持JSON格式或简化字符串格式，格式说明见 点阵颜色列表格式说明 -PointColorListFormat
            sim: 相似度阈值，范围0-1.0，默认1.0
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左
            x: 返回找到的颜色点X坐标
            y: 返回找到的颜色点Y坐标

        Returns:
            返回元组: (查找结果, 返回找到的颜色点X坐标, 返回找到的颜色点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("FindMultiColorFromPtr")
        return func(self.OLAObject, ptr, colorJson, pointJson, sim, _dir, x, y)

    def FindMultiColorListFromPtr(self, ptr: int, colorJson: Union[str, List[dict]], pointJson: Union[str, List[dict]], sim: float) -> List[dict]:
        """在内存图像中查找多色点列表

        Args:
            ptr: 图像句柄
            colorJson: 颜色模型配置字符串，用于限定图像匹配中的颜色范围，格式说明见 颜色模型说明 -ColorModel
            pointJson: 点阵颜色列表，支持JSON格式或简化字符串格式，格式说明见 点阵颜色列表格式说明 -PointColorListFormat
            sim: 相似度阈值，范围0-1.0，默认1.0

        Returns:
            返回识别到的坐标点列表的JSON字符串

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("FindMultiColorListFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr, colorJson, pointJson, sim))
        if result == "":
            return []
        return json.loads(result)

    def GetImageSize(self, ptr: int, width: int = None, height: int = None) -> Tuple[int, int, int]:
        """获取图像的宽度和高度

        Args:
            ptr: 图像句柄
            width: 返回图像宽度
            height: 返回图像高度

        Returns:
            返回元组: (获取结果, 返回图像宽度, 返回图像高度)
            获取结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetImageSize")
        return func(self.OLAObject, ptr, width, height)

    def FindColorBlock(self, x1: int, y1: int, x2: int, y2: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在绑定窗口中查找指定颜色的连续区域（色块）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            x: 返回色块中心点X坐标
            y: 返回色块中心点Y坐标

        Returns:
            返回元组: (查找结果, 返回色块中心点X坐标, 返回色块中心点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlock")
        return func(self.OLAObject, x1, y1, x2, y2, colorList, count, width, height, x, y)

    def FindColorBlockPtr(self, ptr: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在内存图像中查找指定颜色的连续区域（色块）

        Args:
            ptr: 图像句柄
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            x: 返回色块中心点X坐标
            y: 返回色块中心点Y坐标

        Returns:
            返回元组: (查找结果, 返回色块中心点X坐标, 返回色块中心点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockPtr")
        return func(self.OLAObject, ptr, colorList, count, width, height, x, y)

    def FindColorBlockList(self, x1: int, y1: int, x2: int, y2: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, _type: int) -> List[dict]:
        """在绑定窗口中查找指定颜色的所有连续区域（色块列表）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            _type: 查找类型，可选值:
                0: 不重复
                1: 重复

        Returns:
            

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockList")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorList, count, width, height, _type))
        if result == "":
            return []
        return json.loads(result)

    def FindColorBlockListPtr(self, ptr: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, _type: int) -> List[dict]:
        """在内存图像中查找指定颜色的所有连续区域（色块列表）

        Args:
            ptr: 图像句柄
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            _type: 查找类型，可选值:
                0: 不重复
                1: 重复

        Returns:
            

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockListPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr, colorList, count, width, height, _type))
        if result == "":
            return []
        return json.loads(result)

    def FindColorBlockEx(self, x1: int, y1: int, x2: int, y2: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, _dir: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在绑定窗口中查找指定颜色的连续区域（色块）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            _dir: 查找方向，可选值:
                0:: 从左到右,从上到下
                1:: 从左到右,从下到上
                2:: 从右到左,从上到下
                3:: 从右到左,从下到上
                4:: 从中心往外查找
                5:: 从上到下,从左到右
                6:: 从上到下,从右到左
                7:: 从下到上,从左到右
                8:: 从下到上,从右到左
            x: 返回色块中心点X坐标
            y: 返回色块中心点Y坐标

        Returns:
            返回元组: (查找结果, 返回色块中心点X坐标, 返回色块中心点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockEx")
        return func(self.OLAObject, x1, y1, x2, y2, colorList, count, width, height, _dir, x, y)

    def FindColorBlockPtrEx(self, ptr: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, _dir: int, x: int = None, y: int = None) -> Tuple[int, int, int]:
        """在内存图像中查找指定颜色的连续区域（色块）

        Args:
            ptr: 图像句柄
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            _dir: 查找方向，可选值:
                0:: 从左到右,从上到下
                1:: 从左到右,从下到上
                2:: 从右到左,从上到下
                3:: 从右到左,从下到上
                4:: 从中心往外查找
                5:: 从上到下,从左到右
                6:: 从上到下,从右到左
                7:: 从下到上,从左到右
                8:: 从下到上,从右到左
            x: 返回色块中心点X坐标
            y: 返回色块中心点Y坐标

        Returns:
            返回元组: (查找结果, 返回色块中心点X坐标, 返回色块中心点Y坐标)
            查找结果:
                0: 未找到
                1: 找到

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockPtrEx")
        return func(self.OLAObject, ptr, colorList, count, width, height, _dir, x, y)

    def FindColorBlockListEx(self, x1: int, y1: int, x2: int, y2: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, _type: int, _dir: int) -> List[dict]:
        """在绑定窗口中查找指定颜色的所有连续区域（色块列表）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            _type: 查找类型，可选值:
                0: 不重复
                1: 重复
            _dir: 查找方向，可选值:
                0:: 从左到右,从上到下
                1:: 从左到右,从下到上
                2:: 从右到左,从上到下
                3:: 从右到左,从下到上
                4:: 从中心往外查找
                5:: 从上到下,从左到右
                6:: 从上到下,从右到左
                7:: 从下到上,从左到右
                8:: 从下到上,从右到左

        Returns:
            

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockListEx")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, colorList, count, width, height, _type, _dir))
        if result == "":
            return []
        return json.loads(result)

    def FindColorBlockListPtrEx(self, ptr: int, colorList: Union[str, List[dict]], count: int, width: int, height: int, _type: int, _dir: int) -> List[dict]:
        """在内存图像中查找指定颜色的所有连续区域（色块列表）

        Args:
            ptr: 图像句柄
            colorList: 要查找的颜色值（JSON格式）
            count: 要查找的色块数量
            width: 图像宽度
            height: 图像高度
            _type: 查找类型，可选值:
                0: 不重复
                1: 重复
            _dir: 查找方向，可选值:
                0:: 从左到右,从上到下
                1:: 从左到右,从下到上
                2:: 从右到左,从上到下
                3:: 从右到左,从下到上
                4:: 从中心往外查找
                5:: 从上到下,从左到右
                6:: 从上到下,从右到左
                7:: 从下到上,从左到右
                8:: 从下到上,从右到左

        Returns:
            

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("FindColorBlockListPtrEx")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr, colorList, count, width, height, _type, _dir))
        if result == "":
            return []
        return json.loads(result)

    def GetColorNum(self, x1: int, y1: int, x2: int, y2: int, colorList: Union[str, List[dict]]) -> int:
        """统计绑定窗口指定区域内指定颜色的像素数量

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorList: 要统计的颜色值（JSON格式）

        Returns:
            返回指定颜色的像素数量

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("GetColorNum")
        return func(self.OLAObject, x1, y1, x2, y2, colorList)

    def GetColorNumPtr(self, ptr: int, colorList: Union[str, List[dict]]) -> int:
        """统计内存图像中指定颜色的像素数量

        Args:
            ptr: 图像句柄
            colorList: 要统计的颜色值（JSON格式）

        Returns:
            返回指定颜色的像素数量

        Notes:
        """
        if not isinstance(colorList, str):
            colorList = json.dumps(colorList)
        func = OLAPlugDLLHelper.get_function("GetColorNumPtr")
        return func(self.OLAObject, ptr, colorList)

    def Cropped(self, image: int, x1: int, y1: int, x2: int, y2: int) -> int:
        """对图像进行裁剪

        Args:
            image: 图像句柄
            x1: 裁剪区域左上角X坐标
            y1: 裁剪区域左上角Y坐标
            x2: 裁剪区域右下角X坐标
            y2: 裁剪区域右下角Y坐标

        Returns:
            裁剪后图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Cropped")
        return func(self.OLAObject, image, x1, y1, x2, y2)

    def GetThresholdImageFromMultiColorPtr(self, ptr: int, colorJson: Union[str, List[dict]]) -> int:
        """根据多色点生成阈值图像

        Args:
            ptr: 图像句柄
            colorJson: 颜色范围定义（JSON）

        Returns:
            返回阈值图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("GetThresholdImageFromMultiColorPtr")
        return func(self.OLAObject, ptr, colorJson)

    def GetThresholdImageFromMultiColor(self, x1: int, y1: int, x2: int, y2: int, colorJson: Union[str, List[dict]]) -> int:
        """根据多色点生成阈值图像（从屏幕区域）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            colorJson: 要统计的颜色值（JSON格式）

        Returns:
            返回阈值图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("GetThresholdImageFromMultiColor")
        return func(self.OLAObject, x1, y1, x2, y2, colorJson)

    def IsSameImage(self, ptr: int, ptr2: int) -> int:
        """判断两幅图像是否完全相同

        Args:
            ptr: 第一幅图像句柄
            ptr2: 第二幅图像句柄

        Returns:
            比较结果
                0: 不相同
                1: 相同

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("IsSameImage")
        return func(self.OLAObject, ptr, ptr2)

    def ShowImage(self, ptr: int) -> int:
        """显示图像

        Args:
            ptr: 图像句柄

        Returns:
            操作结果，0 失败，1 成功

        Notes:
            1. 在独立窗口中显示图像，用于调试和查看
        """
        func = OLAPlugDLLHelper.get_function("ShowImage")
        return func(self.OLAObject, ptr)

    def ShowImageFromFile(self, file: str) -> int:
        """显示图片

        Args:
            file: 图片文件路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ShowImageFromFile")
        return func(self.OLAObject, file)

    def SetColorsToNewColor(self, ptr: int, colorJson: Union[str, List[dict]], color: str) -> int:
        """将图像中指定颜色范围内的像素替换为新颜色

        Args:
            ptr: 图像句柄
            colorJson: 颜色范围定义（JSON）
            color: 目标颜色（BGR十六进制字符串）

        Returns:
            返回处理后的图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("SetColorsToNewColor")
        return func(self.OLAObject, ptr, colorJson, color)

    def RemoveOtherColors(self, ptr: int, colorJson: Union[str, List[dict]]) -> int:
        """保留图像中指定颜色，其余颜色变为黑色

        Args:
            ptr: 图像句柄
            colorJson: 要保留的颜色范围（JSON）

        Returns:
            返回处理后的图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        if not isinstance(colorJson, str):
            colorJson = json.dumps(colorJson)
        func = OLAPlugDLLHelper.get_function("RemoveOtherColors")
        return func(self.OLAObject, ptr, colorJson)

    def DrawRectangle(self, ptr: int, x1: int, y1: int, x2: int, y2: int, thickness: int, color: str) -> int:
        """在图像上绘制矩形

        Args:
            ptr: 图像句柄
            x1: 矩形左上角X坐标
            y1: 矩形左上角Y坐标
            x2: 矩形右下角X坐标
            y2: 矩形右下角Y坐标
            thickness: 线条粗细，负值表示填充
            color: 绘制颜色（BGR格式）

        Returns:
            返回绘制后的图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawRectangle")
        return func(self.OLAObject, ptr, x1, y1, x2, y2, thickness, color)

    def DrawCircle(self, ptr: int, x: int, y: int, radius: int, thickness: int, color: str) -> int:
        """在图像上绘制圆形

        Args:
            ptr: 图像句柄
            x: 圆心X坐标
            y: 圆心Y坐标
            radius: 半径
            thickness: 线条粗细，负值表示填充
            color: 绘制颜色（BGR格式）

        Returns:
            返回绘制后的图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DrawCircle")
        return func(self.OLAObject, ptr, x, y, radius, thickness, color)

    def DrawFillPoly(self, ptr: int, pointJson: Union[str, List[dict]], color: str) -> int:
        """在图像上绘制填充多边形

        Args:
            ptr: 图像句柄
            pointJson: 多边形顶点坐标（JSON），如[{"x":10,"y":10}]
            color: 填充颜色（BGR格式）

        Returns:
            返回绘制后的图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        if not isinstance(pointJson, str):
            pointJson = json.dumps(pointJson)
        func = OLAPlugDLLHelper.get_function("DrawFillPoly")
        return func(self.OLAObject, ptr, pointJson, color)

    def DecodeQRCode(self, ptr: int) -> str:
        """从图像中解码二维码

        Args:
            ptr: 图像句柄

        Returns:
            返回解码的二维码内容字符串，需调用FreeStringPtr释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DecodeQRCode")
        return self.PtrToStringUTF8(func(self.OLAObject, ptr))

    def CreateQRCode(self, _str: str, pixelsPerModule: int) -> int:
        """生成二维码图像

        Args:
            _str: 要编码的文本内容
            pixelsPerModule: 模块像素大小

        Returns:
            返回二维码图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateQRCode")
        return func(self.OLAObject, _str, pixelsPerModule)

    def CreateQRCodeEx(self, _str: str, pixelsPerModule: int, version: int, correction_level: int, mode: int, structure_number: int) -> int:
        """高级生成二维码图像

        Args:
            _str: 要编码的文本内容
            pixelsPerModule: 模块像素大小
            version: 版本（1-40，0表示自动）
            correction_level: 纠错等级（0 L，1 M，2 Q，3 H）
            mode: 编码模式
            structure_number: 结构编号

        Returns:
            返回二维码图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateQRCodeEx")
        return func(self.OLAObject, _str, pixelsPerModule, version, correction_level, mode, structure_number)

    def MatchAnimationFromPtr(self, x1: int, y1: int, x2: int, y2: int, templ: int, matchVal: float, _type: int, angle: float, scale: float, delay: int, time: int, threadCount: int) -> dict:
        """在动画图像序列中查找匹配帧（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: 动画模板/序列句柄
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放
            delay: 动画帧间隔，单位毫秒
            time: 总识别时间，单位毫秒
            threadCount: 用于查找的线程数

        Returns:
            匹配结果

        Notes:
            1. 线程数需要根据delay帧率自行调整，过小会导致识别时间到期未识别完，过大会导致CPU占用过大
            2. 当x1, y1, x2, y2都传0时，将搜索整个窗口客户区
            3. 识别结果最长等待时间为time + 1000ms
            4. 匹配类型的选择：
            5. 灰度匹配速度最快，但精度较低
            6. 彩色匹配精度较高，但速度较慢
            7. 透明匹配适用于带透明通道的图片
            8. 线程数的选择：
            9. 建议根据动画帧率和CPU核心数来设置
            10. 一般建议设置为CPU核心数的1-2倍
            11. 角度参数影响匹配时间和精度：
            12. 角度越小，匹配次数越多，时间越长
            13. 角度为0时速度最快，但可能错过旋转的目标
            14. 缩放比例应与窗口实际缩放比例一致
            15. DLL调用返回的字符串指针需要调用 FreeStringPtr 释放内存
            16. 返回的坐标是相对于绑定窗口客户区的坐标
        """
        func = OLAPlugDLLHelper.get_function("MatchAnimationFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, matchVal, _type, angle, scale, delay, time, threadCount))
        if result == "":
            return {}
        return json.loads(result)

    def MatchAnimationFromPath(self, x1: int, y1: int, x2: int, y2: int, templ: str, matchVal: float, _type: int, angle: float, scale: float, delay: int, time: int, threadCount: int) -> dict:
        """在动画图像序列中查找匹配帧（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: 模板图片的路径，可以是多个图片,比如"test.bmp|test2.bmp|test3.bmp"
            matchVal: 相似度，如0.85，最大为1
            _type: 匹配类型，可选值:
                1: 灰度匹配，速度快
                2: 彩色匹配
                3: 透明匹配
                4: 透透明彩色权重匹配
                5: 普通彩色匹配
            angle: 旋转角度，每次匹配后旋转指定角度继续进行匹配,直到匹配成功,角度越小匹配次数越多时间越长。0为不旋转速度最快
            scale: 窗口缩放比例，默认为1 可以通过GetScaleFromWindows接口读取当前窗口缩放
            delay: 动画帧间隔，单位毫秒
            time: 总识别时间，单位毫秒
            threadCount: 用于查找的线程数

        Returns:
            匹配结果

        Notes:
            1. 线程数需要根据delay帧率自行调整，过小会导致识别时间到期未识别完，过大会导致CPU占用过大
        """
        func = OLAPlugDLLHelper.get_function("MatchAnimationFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, matchVal, _type, angle, scale, delay, time, threadCount))
        if result == "":
            return {}
        return json.loads(result)

    def RemoveImageDiff(self, image1: int, image2: int) -> int:
        """移除两幅图像之间的差异部分

        Args:
            image1: 第一幅图像句柄
            image2: 第二幅图像句柄

        Returns:
            返回差异移除后的图像句柄，失败返回0

        Notes:
            1. 将两幅图像的相同部分保留，不同部分变为黑色
        """
        func = OLAPlugDLLHelper.get_function("RemoveImageDiff")
        return func(self.OLAObject, image1, image2)

    def GetImageBmpData(self, imgPtr: int, data: int = None, size: int = None) -> Tuple[int, int, int]:
        """获取图像的BMP格式数据

        Args:
            imgPtr: OLAImage对象的地址
            data: 返回图片的数据指针
            size: 返回图片的数据长度

        Returns:
            返回元组: (操作结果, 返回图片的数据指针, 返回图片的数据长度)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetImageBmpData")
        return func(self.OLAObject, imgPtr, data, size)

    def GetImagePngData(self, imgPtr: int, data: int = None, size: int = None) -> Tuple[int, int, int]:
        """获取图像的PNG格式数据

        Args:
            imgPtr: OLAImage对象的地址
            data: 返回图片的数据指针
            size: 返回图片的数据长度

        Returns:
            返回元组: (操作结果, 返回图片的数据指针, 返回图片的数据长度)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetImagePngData")
        return func(self.OLAObject, imgPtr, data, size)

    def FreeImageData(self, screenPtr: int) -> int:
        """释放由GetImageData等接口返回的图像数据指针

        Args:
            screenPtr: 图像数据指针

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FreeImageData")
        return func(self.OLAObject, screenPtr)

    def ScalePixels(self, ptr: int, pixelsPerModule: int) -> int:
        """对图像像素进行缩放处理

        Args:
            ptr: 图像句柄
            pixelsPerModule: 像素缩放系数

        Returns:
            处理后图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ScalePixels")
        return func(self.OLAObject, ptr, pixelsPerModule)

    def CreateImage(self, width: int, height: int, color: str) -> int:
        """创建图片

        Args:
            width: 图像宽度
            height: 图像高度
            color: 初始填充颜色（BGR格式）

        Returns:
            返回新图像数据指针，需调用FreeImageData释放内存；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateImage")
        return func(self.OLAObject, width, height, color)

    def SetPixel(self, image: int, x: int, y: int, color: str) -> int:
        """设置指定像素颜色

        Args:
            image: 图像句柄
            x: 指定点X坐标
            y: 指定点Y坐标
            color: 要设置的颜色值（BGR格式）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetPixel")
        return func(self.OLAObject, image, x, y, color)

    def SetPixelList(self, image: int, points: Union[str, List[dict]], color: str) -> int:
        """批量设置图像中多个像素点的颜色

        Args:
            image: 图像句柄
            points: 坐标点数组（JSON），如[{"x":10,"y":10}]
            color: 颜色（BGR十六进制字符串）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        if not isinstance(points, str):
            points = json.dumps(points)
        func = OLAPlugDLLHelper.get_function("SetPixelList")
        return func(self.OLAObject, image, points, color)

    def ConcatImage(self, image1: int, image2: int, gap: int, color: str, _dir: int) -> int:
        """拼接两张图像

        Args:
            image1: 图像1句柄
            image2: 图像2句柄
            gap: 图像间距（像素）
            color: 间距填充颜色（BGR十六进制字符串）
            _dir: 拼接方向（0 水平，1 垂直）

        Returns:
            新图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ConcatImage")
        return func(self.OLAObject, image1, image2, gap, color, _dir)

    def CoverImage(self, image1: int, image2: int, x: int, y: int, alpha: float) -> int:
        """单张图像覆盖的增强版（支持 Alpha 羽化、并行计算）

        Args:
            image1: 前景图句柄（支持四通道Alpha）
            image2: 背景图句柄
            x: 覆盖位置x坐标
            y: 覆盖位置y坐标
            alpha: 全局透明度系数 (0~1)

        Returns:
            混合后的图像

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CoverImage")
        return func(self.OLAObject, image1, image2, x, y, alpha)

    def RotateImage(self, image: int, angle: float) -> int:
        """按角度旋转图像

        Args:
            image: 图像句柄
            angle: 旋转角度（度）

        Returns:
            新图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RotateImage")
        return func(self.OLAObject, image, angle)

    def ImageToBase64(self, image: int) -> str:
        """将图像编码为Base64字符串

        Args:
            image: 图像句柄

        Returns:
            Base64字符串指针，需调用FreeStringPtr释放

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImageToBase64")
        return self.PtrToStringUTF8(func(self.OLAObject, image))

    def Base64ToImage(self, base64: str) -> int:
        """将Base64字符串解码为图像

        Args:
            base64: Base64字符串

        Returns:
            图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Base64ToImage")
        return func(self.OLAObject, base64)

    def Hex2ARGB(self, hex: str, a: int = None, r: int = None, g: int = None, b: int = None) -> Tuple[int, int, int, int, int]:
        """十六进制颜色解析为ARGB

        Args:
            hex: 十六进制颜色（如#AARRGGBB或#RRGGBB）
            a: 返回Alpha（输出）
            r: 返回Red（输出）
            g: 返回Green（输出）
            b: 返回Blue（输出）

        Returns:
            返回元组: (操作结果, 返回Alpha（输出）, 返回Red（输出）, 返回Green（输出）, 返回Blue（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Hex2ARGB")
        return func(self.OLAObject, hex, a, r, g, b)

    def Hex2RGB(self, hex: str, r: int = None, g: int = None, b: int = None) -> Tuple[int, int, int, int]:
        """十六进制颜色解析为RGB

        Args:
            hex: 十六进制颜色（如#RRGGBB）
            r: 返回Red（输出）
            g: 返回Green（输出）
            b: 返回Blue（输出）

        Returns:
            返回元组: (操作结果, 返回Red（输出）, 返回Green（输出）, 返回Blue（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Hex2RGB")
        return func(self.OLAObject, hex, r, g, b)

    def ARGB2Hex(self, a: int, r: int, g: int, b: int) -> str:
        """将ARGB转换为十六进制颜色字符串

        Args:
            a: Alpha分量
            r: Red分量
            g: Green分量
            b: Blue分量

        Returns:
            十六进制颜色字符串指针，需调用FreeStringPtr释放

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ARGB2Hex")
        return self.PtrToStringUTF8(func(self.OLAObject, a, r, g, b))

    def RGB2Hex(self, r: int, g: int, b: int) -> str:
        """将RGB颜色转换为十六进制字符串

        Args:
            r: 红色值
            g: 绿色值
            b: 蓝色值

        Returns:
            十六进制字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RGB2Hex")
        return self.PtrToStringUTF8(func(self.OLAObject, r, g, b))

    def Hex2HSV(self, hex: str) -> str:
        """将十六进制颜色转换为HSV颜色

        Args:
            hex: 十六进制颜色

        Returns:
            HSV颜色

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Hex2HSV")
        return self.PtrToStringUTF8(func(self.OLAObject, hex))

    def RGB2HSV(self, r: int, g: int, b: int) -> str:
        """将RGB颜色转换为HSV颜色

        Args:
            r: 红色值
            g: 绿色值
            b: 蓝色值

        Returns:
            HSV颜色

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RGB2HSV")
        return self.PtrToStringUTF8(func(self.OLAObject, r, g, b))

    def CmpColor(self, x1: int, y1: int, colorStart: str, colorEnd: str) -> int:
        """判断屏幕坐标点颜色是否在指定范围

        Args:
            x1: X坐标
            y1: Y坐标
            colorStart: 起始颜色（含）
            colorEnd: 结束颜色（含）

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CmpColor")
        return func(self.OLAObject, x1, y1, colorStart, colorEnd)

    def CmpColorPtr(self, ptr: int, x: int, y: int, colorStart: str, colorEnd: str) -> int:
        """判断图像坐标点颜色是否在指定范围

        Args:
            ptr: 图像句柄
            x: X坐标
            y: Y坐标
            colorStart: 起始颜色（含）
            colorEnd: 结束颜色（含）

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CmpColorPtr")
        return func(self.OLAObject, ptr, x, y, colorStart, colorEnd)

    def CmpColorEx(self, x1: int, y1: int, colorJson: str) -> int:
        """判断屏幕坐标点颜色是否在指定范围

        Args:
            x1: X坐标
            y1: Y坐标
            colorJson: 颜色（JSON）

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CmpColorEx")
        return func(self.OLAObject, x1, y1, colorJson)

    def CmpColorPtrEx(self, ptr: int, x: int, y: int, colorJson: str) -> int:
        """判断图像坐标点颜色是否在指定范围

        Args:
            ptr: 图像句柄
            x: X坐标
            y: Y坐标
            colorJson: 颜色（JSON）

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CmpColorPtrEx")
        return func(self.OLAObject, ptr, x, y, colorJson)

    def CmpColorHexEx(self, hex: str, colorJson: str) -> int:
        """判断十六进制颜色是否在指定范围

        Args:
            hex: 颜色（十六进制）
            colorJson: 颜色（JSON）

        Returns:
            操作结果
                0: 否
                1: 是

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CmpColorHexEx")
        return func(self.OLAObject, hex, colorJson)

    def CmpColorHex(self, hex: str, colorStart: str, colorEnd: str) -> int:
        """判断十六进制颜色是否在指定范围

        Args:
            hex: 颜色（十六进制）
            colorStart: 起始颜色（含）
            colorEnd: 结束颜色（含）

        Returns:
            操作结果
                0: 失败，未找到符合条件的颜色点
                1: 成功，找到符合条件的颜色点

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CmpColorHex")
        return func(self.OLAObject, hex, colorStart, colorEnd)

    def GetConnectedComponents(self, ptr: int, points: Union[str, List[dict]], tolerance: int) -> int:
        """基于种子点获取连通域

        Args:
            ptr: 图像句柄
            points: 种子点数组（JSON）
            tolerance: 容差阈值

        Returns:
            连通域点数组字符串指针（JSON），需调用FreeStringPtr释放

        Notes:
        """
        if not isinstance(points, str):
            points = json.dumps(points)
        func = OLAPlugDLLHelper.get_function("GetConnectedComponents")
        return func(self.OLAObject, ptr, points, tolerance)

    def DetectPointerDirection(self, ptr: int, x: int, y: int) -> float:
        """基于几何与边缘特征检测指针（针状/箭头）方向

        Args:
            ptr: 图像句柄
            x: 参考点X坐标
            y: 参考点Y坐标

        Returns:
            方向角（度）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DetectPointerDirection")
        return func(self.OLAObject, ptr, x, y)

    def DetectPointerDirectionByFeatures(self, ptr: int, templatePtr: int, x: int, y: int, useTemplate: bool) -> float:
        """基于特征与模板的指针方向检测

        Args:
            ptr: 图像句柄
            templatePtr: 模板图句柄（可选）
            x: 参考点X坐标
            y: 参考点Y坐标
            useTemplate: 是否启用模板匹配

        Returns:
            方向角（度）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("DetectPointerDirectionByFeatures")
        return func(self.OLAObject, ptr, templatePtr, x, y, useTemplate)

    def FastMatch(self, ptr: int, templatePtr: int, matchVal: float, _type: int, angle: float, scale: float) -> dict:
        """快速模板匹配

        Args:
            ptr: 源图句柄
            templatePtr: 模板图句柄
            matchVal: 匹配阈值（0~1）
            _type: 匹配类型
            angle: 旋转角度（度）
            scale: 缩放比例

        Returns:
            匹配结果（结构体/指针，失败返回0）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FastMatch")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr, templatePtr, matchVal, _type, angle, scale))
        if result == "":
            return {}
        return json.loads(result)

    def FastROI(self, ptr: int) -> int:
        """快速ROI,返回不为0的最大区域图像

        Args:
            ptr: 图像句柄

        Returns:
            返回ROI区域子图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FastROI")
        return func(self.OLAObject, ptr)

    def GetROIRegion(self, ptr: int, x1: int = None, y1: int = None, x2: int = None, y2: int = None) -> Tuple[int, int, int, int, int]:
        """获取ROI区域

        Args:
            ptr: 图像句柄
            x1: 返回区域左上角X坐标（输出）
            y1: 返回区域左上角Y坐标（输出）
            x2: 返回区域右下角X坐标（输出）
            y2: 返回区域右下角Y坐标（输出）

        Returns:
            返回元组: (操作结果, 返回区域左上角X坐标（输出）, 返回区域左上角Y坐标（输出）, 返回区域右下角X坐标（输出）, 返回区域右下角Y坐标（输出）)
            操作结果:
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetROIRegion")
        return func(self.OLAObject, ptr, x1, y1, x2, y2)

    def GetForegroundPoints(self, ptr: int) -> List[dict]:
        """获取前景点

        Args:
            ptr: 图像句柄

        Returns:
            前景点数组字符串指针（JSON，如[{"x":10,"y":10}]]），需调用FreeStringPtr释放

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetForegroundPoints")
        result = self.PtrToStringUTF8(func(self.OLAObject, ptr))
        if result == "":
            return []
        return json.loads(result)

    def ConvertColor(self, ptr: int, _type: int) -> int:
        """转换颜色

        Args:
            ptr: 图像句柄
            _type: 0转为灰度 ,1.BGRA-RGBA,2.BGRA-BGR,3.BGRA-HSVA,4.BGRA-HSV

        Returns:
            返回转换后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ConvertColor")
        return func(self.OLAObject, ptr, _type)

    def Threshold(self, ptr: int, thresh: float, maxVal: float, _type: int) -> int:
        """阈值化

        Args:
            ptr: 图像句柄
            thresh: 阈值
            maxVal: 最大值
            _type: 0.二值化,1.反二值化,2.截断,3.阈值化,4.反阈值化,5.阈值化OTSU,6.反阈值化OTSU

        Returns:
            返回阈值化后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Threshold")
        return func(self.OLAObject, ptr, thresh, maxVal, _type)

    def RemoveIslands(self, ptr: int, minArea: int) -> int:
        """去除孤岛

        Args:
            ptr: 图像句柄
            minArea: 最小面积

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RemoveIslands")
        return func(self.OLAObject, ptr, minArea)

    def MorphGradient(self, ptr: int, kernelSize: int) -> int:
        """形态学梯度

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MorphGradient")
        return func(self.OLAObject, ptr, kernelSize)

    def MorphTophat(self, ptr: int, kernelSize: int) -> int:
        """形态学顶帽

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MorphTophat")
        return func(self.OLAObject, ptr, kernelSize)

    def MorphBlackhat(self, ptr: int, kernelSize: int) -> int:
        """形态学黑帽

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MorphBlackhat")
        return func(self.OLAObject, ptr, kernelSize)

    def Dilation(self, ptr: int, kernelSize: int) -> int:
        """膨胀

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Dilation")
        return func(self.OLAObject, ptr, kernelSize)

    def Erosion(self, ptr: int, kernelSize: int) -> int:
        """腐蚀

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Erosion")
        return func(self.OLAObject, ptr, kernelSize)

    def GaussianBlur(self, ptr: int, kernelSize: int) -> int:
        """高斯模糊

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GaussianBlur")
        return func(self.OLAObject, ptr, kernelSize)

    def Sharpen(self, ptr: int) -> int:
        """图像锐化

        Args:
            ptr: 图像句柄

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Sharpen")
        return func(self.OLAObject, ptr)

    def CannyEdge(self, ptr: int, kernelSize: int) -> int:
        """Canny边缘检测

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回边缘图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CannyEdge")
        return func(self.OLAObject, ptr, kernelSize)

    def Flip(self, ptr: int, flipCode: int) -> int:
        """翻转图像

        Args:
            ptr: 图像指针
            flipCode: 翻转代码，可选值:
                0: X轴
                1: Y轴
                2: 同时翻转

        Returns:
            返回翻转后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Flip")
        return func(self.OLAObject, ptr, flipCode)

    def MorphOpen(self, ptr: int, kernelSize: int) -> int:
        """形态学开运算

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MorphOpen")
        return func(self.OLAObject, ptr, kernelSize)

    def MorphClose(self, ptr: int, kernelSize: int) -> int:
        """形态学闭运算

        Args:
            ptr: 图像指针，由图像处理函数返回
            kernelSize: 形态学核的大小，通常为奇数（3、5、7等）

        Returns:
            返回处理后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("MorphClose")
        return func(self.OLAObject, ptr, kernelSize)

    def Skeletonize(self, ptr: int) -> int:
        """骨架化

        Args:
            ptr: 图像句柄

        Returns:
            返回骨架化后的图像句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("Skeletonize")
        return func(self.OLAObject, ptr)

    def ImageStitchFromPath(self, path: str, trajectory: int = None) -> Tuple[int, int]:
        """从路径拼接图片

        Args:
            path: 图片目录或通配路径
            trajectory: 返回轨迹数据指针（输出，可为0）

        Returns:
            返回元组: (返回拼接后的图像句柄，失败返回0, 返回轨迹数据指针（输出，可为0）)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImageStitchFromPath")
        return func(self.OLAObject, path, trajectory)

    def ImageStitchCreate(self) -> int:
        """创建拼接图片实例

        Returns:
            返回拼接实例句柄，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImageStitchCreate")
        return func(self.OLAObject)

    def ImageStitchAppend(self, imageStitch: int, image: int) -> int:
        """拼接图片

        Args:
            imageStitch: 拼接实例句柄
            image: 图像句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImageStitchAppend")
        return func(self.OLAObject, imageStitch, image)

    def ImageStitchGetResult(self, imageStitch: int, trajectory: int = None) -> Tuple[int, int]:
        """获取拼接图片结果

        Args:
            imageStitch: 拼接实例句柄
            trajectory: 输出参数，可为0；返回轨迹数据的字符串指针，需使用 FreeStringPtr 释放

        Returns:
            返回元组: (返回拼接后的图像句柄，失败返回0, 输出参数，可为0；返回轨迹数据的字符串指针，需使用 FreeStringPtr 释放)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImageStitchGetResult")
        return func(self.OLAObject, imageStitch, trajectory)

    def ImageStitchFree(self, imageStitch: int) -> int:
        """释放拼接图片实例

        Args:
            imageStitch: 拼接实例句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ImageStitchFree")
        return func(self.OLAObject, imageStitch)

    def BitPacking(self, image: int) -> str:
        """压缩二值化图像成字符串

        Args:
            image: 拼接实例句柄

        Returns:
            压缩结果字符串

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("BitPacking")
        return self.PtrToStringUTF8(func(self.OLAObject, image))

    def BitUnpacking(self, imageStr: str) -> int:
        """解压缩字符串成二值化图像

        Args:
            imageStr: BitPacking压缩结果

        Returns:
            返回图像句柄,失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("BitUnpacking")
        return func(self.OLAObject, imageStr)

    def SetImageCache(self, enable: int) -> int:
        """设置图片缓存开关

        Args:
            enable: 是否启用图片缓存，可选值:
                0: 关闭
                1: 开启

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SetImageCache")
        return func(enable)

    def FindImageFromPtr(self, source: int, templ: int, deltaColor: str, matchVal: float, _dir: int) -> dict:
        """在指定图片中查找指定图像（使用内存数据）

        Args:
            source: OLAImage对象的地址
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindImageFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, deltaColor, matchVal, _dir))
        if result == "":
            return {}
        return json.loads(result)

    def FindImageFromPtrAll(self, source: int, templ: int, deltaColor: str, matchVal: float) -> List[dict]:
        """在指定图片中查找指定图像的所有匹配位置（使用内存数据）

        Args:
            source: OLAImage对象的地址
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1

        Returns:
            返回所有匹配结果字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindImageFromPtrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, deltaColor, matchVal))
        if result == "":
            return []
        return json.loads(result)

    def FindImageFromPath(self, source: str, templ: str, deltaColor: str, matchVal: float, _dir: int) -> dict:
        """在指定图片中查找指定图像（使用文件路径）

        Args:
            source: 源图片的路径
            templ: 模板图片的路径，可以是多个图片，比如”test.bmp|test2.bmp|test3.bmp”
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindImageFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, deltaColor, matchVal, _dir))
        if result == "":
            return {}
        return json.loads(result)

    def FindImageFromPathAll(self, source: str, templ: str, deltaColor: str, matchVal: float) -> List[dict]:
        """在指定图片中查找指定图像的所有匹配位置（使用文件路径）

        Args:
            source: 源图片的路径
            templ: 模板图片的路径，可以是多个图片，比如”test.bmp|test2.bmp|test3.bmp”
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1

        Returns:
            返回所有匹配结果字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindImageFromPathAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, source, templ, deltaColor, matchVal))
        if result == "":
            return []
        return json.loads(result)

    def FindWindowsFromPtr(self, x1: int, y1: int, x2: int, y2: int, templ: int, deltaColor: str, matchVal: float, _dir: int) -> dict:
        """在绑定窗口中查找指定图像（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindWindowsFromPtr")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, deltaColor, matchVal, _dir))
        if result == "":
            return {}
        return json.loads(result)

    def FindWindowsFromPtrAll(self, x1: int, y1: int, x2: int, y2: int, templ: int, deltaColor: str, matchVal: float) -> List[dict]:
        """在绑定窗口中查找指定图像的所有匹配位置（使用内存数据）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: OLAImage对象的地址,由LoadImage 等接口生成
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1

        Returns:
            返回所有匹配结果字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindWindowsFromPtrAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, deltaColor, matchVal))
        if result == "":
            return []
        return json.loads(result)

    def FindWindowsFromPath(self, x1: int, y1: int, x2: int, y2: int, templ: str, deltaColor: str, matchVal: float, _dir: int) -> dict:
        """在绑定窗口中查找指定图像（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: 模板图片的路径，可以是多个图片，比如”test.bmp|test2.bmp|test3.bmp”
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1
            _dir: 查找方向，可选值:
                0: 从左到右,从上到下
                1: 从左到右,从下到上
                2: 从右到左,从上到下
                3: 从右到左,从下到上
                4: 从中心往外查找
                5: 从上到下,从左到右
                6: 从上到下,从右到左
                7: 从下到上,从左到右
                8: 从下到上,从右到左

        Returns:
            匹配结果

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindWindowsFromPath")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, deltaColor, matchVal, _dir))
        if result == "":
            return {}
        return json.loads(result)

    def FindWindowsFromPathAll(self, x1: int, y1: int, x2: int, y2: int, templ: str, deltaColor: str, matchVal: float) -> List[dict]:
        """在绑定窗口中查找指定图像的所有匹配位置（使用文件路径）

        Args:
            x1: 搜索区域左上角X坐标
            y1: 搜索区域左上角Y坐标
            x2: 搜索区域右下角X坐标
            y2: 搜索区域右下角Y坐标
            templ: 模板图片的路径，可以是多个图片，比如”test.bmp|test2.bmp|test3.bmp”
            deltaColor: 颜色差值，格式为"RRGGBB"，如"101010"
            matchVal: 相似度，如0.85，最大为1

        Returns:
            返回所有匹配结果字符串

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindWindowsFromPathAll")
        result = self.PtrToStringUTF8(func(self.OLAObject, x1, y1, x2, y2, templ, deltaColor, matchVal))
        if result == "":
            return []
        return json.loads(result)

    def RegistryOpenKey(self, rootKey: int, subKey: str) -> int:
        """打开已有注册表键

        Args:
            rootKey: 根键类型，见 OlaRegistryRootKey
            subKey: 子键路径，例如 "Software\\Microsoft\\Windows"

        Returns:
            注册表键句柄，失败返回 0

        Notes:
            1. 仅在键已存在时返回有效句柄
            2. 使用完成后必须调用 RegistryCloseKey 释放句柄
        """
        func = OLAPlugDLLHelper.get_function("RegistryOpenKey")
        return func(self.OLAObject, rootKey, subKey)

    def RegistryCreateKey(self, rootKey: int, subKey: str) -> int:
        """创建（如不存在则创建）并打开注册表键

        Args:
            rootKey: 根键类型，见 OlaRegistryRootKey
            subKey: 子键路径，例如 "Software\\OLAPlug"

        Returns:
            注册表键句柄，失败返回 0

        Notes:
            1. 如果键已存在，则直接打开已有键
            2. 使用完成后必须调用 RegistryCloseKey 释放句柄
        """
        func = OLAPlugDLLHelper.get_function("RegistryCreateKey")
        return func(self.OLAObject, rootKey, subKey)

    def RegistryCloseKey(self, key: int) -> int:
        """关闭注册表键句柄

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 关闭后句柄失效，不可再使用
        """
        func = OLAPlugDLLHelper.get_function("RegistryCloseKey")
        return func(self.OLAObject, key)

    def RegistryKeyExists(self, rootKey: int, subKey: str) -> int:
        """判断指定注册表键是否存在

        Args:
            rootKey: 根键类型，见 OlaRegistryRootKey
            subKey: 子键路径

        Returns:
            查询结果
                0: 表示不存在
                1: 表示存在

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistryKeyExists")
        return func(self.OLAObject, rootKey, subKey)

    def RegistryDeleteKey(self, rootKey: int, subKey: str, recursive: int) -> int:
        """删除指定注册表键

        Args:
            rootKey: 根键类型，见 OlaRegistryRootKey
            subKey: 子键路径
            recursive: 是否递归删除子键，可选值:
                0: 表示仅删除当前键
                1: 表示递归删除

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 建议谨慎使用递归删除，避免误删系统关键配置
        """
        func = OLAPlugDLLHelper.get_function("RegistryDeleteKey")
        return func(self.OLAObject, rootKey, subKey, recursive)

    def RegistrySetString(self, key: int, valueName: str, value: str) -> int:
        """设置字符串类型的注册表值（REG_SZ）

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称，空字符串表示默认值
            value: 字符串值内容

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistrySetString")
        return func(self.OLAObject, key, valueName, value)

    def RegistryGetString(self, key: int, valueName: str) -> str:
        """读取字符串类型的注册表值（REG_SZ/REG_EXPAND_SZ）

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称，空字符串表示默认值

        Returns:
            字符串内容的句柄，失败或不存在时返回 0

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetString")
        return self.PtrToStringUTF8(func(self.OLAObject, key, valueName))

    def RegistrySetDword(self, key: int, valueName: str, value: int) -> int:
        """设置 32 位整型注册表值（REG_DWORD）

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称
            value: 要写入的 32 位整型值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistrySetDword")
        return func(self.OLAObject, key, valueName, value)

    def RegistryGetDword(self, key: int, valueName: str) -> int:
        """读取 32 位整型注册表值（REG_DWORD）

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称

        Returns:
            读取到的数值；如果值不存在或类型不匹配，则返回 0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetDword")
        return func(self.OLAObject, key, valueName)

    def RegistrySetQword(self, key: int, valueName: str, value: int) -> int:
        """设置 64 位整型注册表值（REG_QWORD）

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称
            value: 要写入的 64 位整型值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistrySetQword")
        return func(self.OLAObject, key, valueName, value)

    def RegistryGetQword(self, key: int, valueName: str) -> int:
        """读取 64 位整型注册表值（REG_QWORD）

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称

        Returns:
            读取到的数值；如果值不存在或类型不匹配，则返回 0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetQword")
        return func(self.OLAObject, key, valueName)

    def RegistryDeleteValue(self, key: int, valueName: str) -> int:
        """删除指定名称的注册表值

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回
            valueName: 值名称

        Returns:
            操作结果
                0: 失败
                1: 表示成功或值不存在

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistryDeleteValue")
        return func(self.OLAObject, key, valueName)

    def RegistryEnumSubKeys(self, key: int) -> str:
        """枚举当前键下的所有子键名称

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回

        Returns:
            包含所有子键名称的 JSON 数组字符串句柄，例如 ["SubKey1","SubKey2"]

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryEnumSubKeys")
        return self.PtrToStringUTF8(func(self.OLAObject, key))

    def RegistryEnumValues(self, key: int) -> str:
        """枚举当前键下的所有值名称

        Args:
            key: 注册表键句柄，由 RegistryOpenKey 或 RegistryCreateKey 返回

        Returns:
            包含所有值名称的 JSON 数组字符串句柄，例如 ["Value1","Value2"]

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryEnumValues")
        return self.PtrToStringUTF8(func(self.OLAObject, key))

    def RegistrySetEnvironmentVariable(self, name: str, value: str, systemWide: int) -> int:
        """设置环境变量，内部基于注册表与系统 API 实现

        Args:
            name: 环境变量名称
            value: 环境变量值
            systemWide: 是否为系统级环境变量，可选值:
                0: 表示当前用户
                1: 表示系统级

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistrySetEnvironmentVariable")
        return func(self.OLAObject, name, value, systemWide)

    def RegistryGetEnvironmentVariable(self, name: str, systemWide: int) -> str:
        """获取环境变量的值

        Args:
            name: 环境变量名称
            systemWide: 是否从系统级环境变量读取，可选值:
                0: 表示当前用户
                1: 表示系统级

        Returns:
            环境变量值的字符串句柄，如果不存在则返回 0

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetEnvironmentVariable")
        return self.PtrToStringUTF8(func(self.OLAObject, name, systemWide))

    def RegistryGetUserRegistryPath(self) -> str:
        """获取用户配置相关的注册表路径

        Returns:
            注册表路径字符串句柄，例如 "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserShell Folders"

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetUserRegistryPath")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def RegistryGetSystemRegistryPath(self) -> str:
        """获取系统配置相关的注册表路径

        Returns:
            注册表路径字符串句柄，例如 "Software\\Microsoft\\Windows\\CurrentVersion"

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetSystemRegistryPath")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def RegistryBackupToFile(self, rootKey: int, subKey: str, filePath: str) -> int:
        """备份注册表键到文件

        Args:
            rootKey: 根键类型，见 OlaRegistryRootKey
            subKey: 子键路径
            filePath: 备份文件路径（.reg 格式）

        Returns:
            操作结果
                0: 失败
                1: 成功 * @note 文件将以标准 .reg 格式保存，可以使用 regedit 导入

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistryBackupToFile")
        return func(self.OLAObject, rootKey, subKey, filePath)

    def RegistryRestoreFromFile(self, filePath: str) -> int:
        """从文件恢复注册表键

        Args:
            filePath: 备份文件路径（.reg 格式）

        Returns:
            操作结果
                0: 失败
                1: 成功 * @note 文件必须是标准 .reg 格式

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("RegistryRestoreFromFile")
        return func(self.OLAObject, filePath)

    def RegistryCompareKeys(self, rootKey1: int, subKey1: str, rootKey2: int, subKey2: str) -> str:
        """比较两个注册表键

        Args:
            rootKey1: 第一个根键类型
            subKey1: 第一个子键路径
            rootKey2: 第二个根键类型
            subKey2: 第二个子键路径

        Returns:
            JSON 字符串句柄，包含比较结果：{"equal": true/false, "differences": [...]}

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryCompareKeys")
        return self.PtrToStringUTF8(func(self.OLAObject, rootKey1, subKey1, rootKey2, subKey2))

    def RegistrySearchKeys(self, rootKey: int, searchPath: str, searchPattern: str, recursive: int) -> str:
        """搜索注册表键

        Args:
            rootKey: 根键类型
            searchPath: 搜索起始路径
            searchPattern: 搜索模式（支持通配符 * 和 ?）
            recursive: 是否递归搜索，可选值:
                0: 表示仅搜索当前层级
                1: 表示递归

        Returns:
            JSON 数组字符串句柄，包含匹配的键路径，例如 ["path1","path2"]

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistrySearchKeys")
        return self.PtrToStringUTF8(func(self.OLAObject, rootKey, searchPath, searchPattern, recursive))

    def RegistryGetInstalledSoftware(self) -> str:
        """获取已安装软件列表

        Returns:
            JSON 数组字符串句柄，包含软件信息，每项包含 name、version、publisher、installDate 等字段

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
            2. 该函数会同时扫描 32 位和 64 位软件列表
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetInstalledSoftware")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def RegistryGetWindowsVersion(self) -> str:
        """获取 Windows 版本信息

        Returns:
            JSON 对象字符串句柄，包含 Windows版本信息：productName、currentVersion、currentBuild、releaseId 等

        Notes:
            1. 返回的字符串句柄需使用 FreeStringPtr 释放
        """
        func = OLAPlugDLLHelper.get_function("RegistryGetWindowsVersion")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def CreateDatabase(self, dbName: str, password: str) -> int:
        """创建数据库连接

        Args:
            dbName: 数据库文件路径
            password: 数据库密码

        Returns:
            数据库对象，若打开失败，返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CreateDatabase")
        return func(self.OLAObject, dbName, password)

    def OpenDatabase(self, dbName: str, password: str) -> int:
        """打开数据库连接

        Args:
            dbName: 数据库文件路径
            password: 数据库密码

        Returns:
            数据库对象，若打开失败，返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("OpenDatabase")
        return func(self.OLAObject, dbName, password)

    def OpenMemoryDatabase(self, address: int, size: int, password: str) -> int:
        """打开内存数据库连接

        Args:
            address: 数据库内存地址
            size: 数据库内存大小
            password: 数据库密码

        Returns:
            数据库连接句柄，如果打开失败则返回 0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("OpenMemoryDatabase")
        return func(self.OLAObject, address, size, password)

    def GetDatabaseError(self, db: int) -> str:
        """获取数据库操作的错误信息

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成

        Returns:
            错误信息字符串的指针

        Notes:
            1. 当数据库操作（如 ExecuteSql, ExecuteScalar 等）失败时，调用此函数可获取详细的错误描述
            2. 返回的字符串指针指向的内存由系统管理，调用者无需手动释放
            3. 此函数通常在数据库操作返回错误码后立即调用，以获取当前的错误状态
        """
        func = OLAPlugDLLHelper.get_function("GetDatabaseError")
        return self.PtrToStringUTF8(func(self.OLAObject, db))

    def CloseDatabase(self, db: int) -> int:
        """关闭数据库连接

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于关闭由 OpenDatabase 接口打开的数据库连接
            2. 关闭连接后，传入的数据库句柄将失效，不能再用于其他数据库操作
            3. 即使关闭操作失败，也应认为该连接已不可用，并丢弃句柄
            4. 为防止资源泄漏，每个成功打开的数据库连接都应调用此接口进行关闭
        """
        func = OLAPlugDLLHelper.get_function("CloseDatabase")
        return func(self.OLAObject, db)

    def GetAllTableNames(self, db: int) -> str:
        """获取数据库中所有表的名称

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成

        Returns:
            包含所有表名的JSON数组字符串指针，例如：["table1", "table2", "table3"]

        Notes:
            1. 该函数查询数据库的系统表，获取所有用户定义表的名称列表
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 如果数据库中没有表，将返回一个空的JSON数组 "[]"
            4. 此操作不会修改数据库内容，是只读操作
        """
        func = OLAPlugDLLHelper.get_function("GetAllTableNames")
        return self.PtrToStringUTF8(func(self.OLAObject, db))

    def GetTableInfo(self, db: int, tableName: str) -> str:
        """获取指定表的列信息

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            tableName: 表名称

        Returns:
            包含列信息的JSON数组字符串指针，例如：[{"name": "id", "type": "INTEGER"}, {"name":"name", "type": "TEXT"}]

        Notes:
            1. 该函数查询指定表的结构，返回其所有列的名称和数据类型
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 如果指定的表不存在，函数将返回 NULL 或一个表示错误的指针
            4. 数据类型通常为数据库原生类型，如 INTEGER, TEXT, REAL, BLOB 等
        """
        func = OLAPlugDLLHelper.get_function("GetTableInfo")
        return self.PtrToStringUTF8(func(self.OLAObject, db, tableName))

    def GetTableInfoDetail(self, db: int, tableName: str) -> str:
        """获取指定表的详细列信息

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            tableName: 表名称

        Returns:
            

        Notes:
            1. 与 GetTableInfo 相比，此函数提供更详细的元数据信息
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 主键信息（pk）和非空约束（notnull）对于理解表结构非常重要
            4. 此信息可用于动态生成SQL语句或进行数据验证
        """
        func = OLAPlugDLLHelper.get_function("GetTableInfoDetail")
        return self.PtrToStringUTF8(func(self.OLAObject, db, tableName))

    def ExecuteSql(self, db: int, sql: str) -> int:
        """执行一条SQL语句（非查询类）

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            sql: 要执行的SQL语句

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于执行 INSERT, UPDATE, DELETE, CREATE TABLE 等修改数据库内容的SQL语句
            2. 对于 INSERT 语句，如果表有自增主键，新插入行的主键值可以通过其他接口获取
            3. 执行成功表示SQL语句被正确解析并执行，但不保证有数据行被实际修改
            4. 如果SQL语句语法错误或违反约束，将返回 0，可通过 GetDatabaseError 获取错误信息
        """
        func = OLAPlugDLLHelper.get_function("ExecuteSql")
        return func(self.OLAObject, db, sql)

    def ExecuteScalar(self, db: int, sql: str) -> int:
        """执行一条返回单个值的SQL查询

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            sql: 要执行的SQL查询语句

        Returns:
            查询结果的字符串指针，如果查询失败或无结果则返回0，结果以字符串形式返回，调用者需根据预期类型进行转换

        Notes:
            1. 用于执行如 SELECT COUNT(*) FROM table 或 SELECT MAX(id) FROM table 这类返回单一值的查询
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 如果查询返回多行或多列，此函数的行为是未定义的，应使用 ExecuteReader
        """
        func = OLAPlugDLLHelper.get_function("ExecuteScalar")
        return func(self.OLAObject, db, sql)

    def ExecuteReader(self, db: int, sql: str) -> int:
        """执行一条SQL查询并返回结果集

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            sql: 要执行的SQL查询语句

        Returns:
            结果集句柄，如果查询失败则返回 0

        Notes:
            1. 用于执行 SELECT 语句，返回一个可遍历的结果集
            2. 成功执行后，返回一个非零的结果集句柄，用于后续的 Read, GetDataCount 等操作
            3. 在使用完结果集后，必须调用 Finalize 接口释放资源
            4. 如果SQL语句不是查询语句，行为是未定义的，应使用 ExecuteSql
        """
        func = OLAPlugDLLHelper.get_function("ExecuteReader")
        return func(self.OLAObject, db, sql)

    def Read(self, stmt: int) -> int:
        """读取结果集的下一行数据

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成

        Returns:
            操作结果
                -1: 发生错误返回
                0: 没有更多数据返回
                1: 成功读取到下一行返回

        Notes:
            1. 用于遍历由 ExecuteReader 生成的结果集
            2. 调用此函数后，结果集的当前位置会移动到下一行
            3. 在首次调用 Read 前，结果集不指向任何有效数据行
            4. 返回 1 表示成功读取了一行，此时可以使用 GetXXXByColumnName 或 GetXXX 系列函数获取该行数据
        """
        func = OLAPlugDLLHelper.get_function("Read")
        return func(self.OLAObject, stmt)

    def GetDataCount(self, stmt: int) -> int:
        """获取结果集中数据行的总数

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成

        Returns:
            数据行的总数

        Notes:
            1. 该函数返回结果集中包含的总行数
            2. 对于大型结果集，此操作可能需要遍历整个结果集，性能开销较大
            3. 某些数据库驱动可能不支持直接获取总行数，此时可能返回 -1 或其他错误值
            4. 在调用 Read 遍历结果集前后调用此函数，返回值应相同
        """
        func = OLAPlugDLLHelper.get_function("GetDataCount")
        return func(self.OLAObject, stmt)

    def GetColumnCount(self, stmt: int) -> int:
        """获取结果集中列的总数

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成

        Returns:
            列的总数

        Notes:
            1. 该函数返回结果集包含的列（字段）的数量
            2. 此值在结果集的生命周期内是固定的，不会改变
            3. 在首次调用 Read 前或后调用此函数均可，结果相同
            4. 获取列数后，可以通过 GetColumnName, GetColumnType 等函数获取每列的元信息
        """
        func = OLAPlugDLLHelper.get_function("GetColumnCount")
        return func(self.OLAObject, stmt)

    def GetColumnName(self, stmt: int, iCol: int) -> str:
        """根据列索引获取列名

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            iCol: 列的索引，从 0 开始

        Returns:
            列名的字符串指针

        Notes:
            1. 用于获取结果集中指定位置列的名称
            2. 索引从 0 开始，最大值为 GetColumnCount(reader) - 1
            3. 如果 columnIndex 超出范围，行为是未定义的，可能返回 NULL 或错误指针
            4. 返回的字符串指针由系统管理，调用者无需手动释放内存
        """
        func = OLAPlugDLLHelper.get_function("GetColumnName")
        return self.PtrToStringUTF8(func(self.OLAObject, stmt, iCol))

    def GetColumnIndex(self, stmt: int, columnName: str) -> int:
        """根据列索引获取列的索引（冗余函数，通常直接使用 columnIndex）

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            columnName: 列的名称

        Returns:
            列的索引，如果列不存在则返回 -1

        Notes:
            1. 用于根据列名查找其在结果集中的位置（索引）
            2. 索引从 0 开始
            3. 如果结果集中存在同名列，此函数的行为可能不确定，通常返回第一个匹配的索引
            4. 此函数对于通过列名访问数据非常有用，可以避免硬编码列索引
        """
        func = OLAPlugDLLHelper.get_function("GetColumnIndex")
        return func(self.OLAObject, stmt, columnName)

    def GetColumnType(self, stmt: int, iCol: int) -> int:
        """根据列索引获取列的数据类型

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            iCol: 列的索引，从 0 开始

        Returns:
            数据类型的字符串表示

        Notes:
            1. 用于获取结果集中指定列的数据类型
            2. 类型通常为 INTEGER, TEXT, REAL, BLOB 等
            3. 返回的字符串指针由系统管理，调用者无需手动释放内存
            4. 此信息可用于在获取数据前进行类型检查或转换
        """
        func = OLAPlugDLLHelper.get_function("GetColumnType")
        return func(self.OLAObject, stmt, iCol)

    def Finalize(self, stmt: int) -> int:
        """释放结果集资源

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于关闭和释放由 ExecuteReader 生成的结果集占用的资源
            2. 在完成对结果集的所有操作（如 Read, GetData 等）后，必须调用此函数
            3. 即使在遍历结果集前发生错误，也应调用 Finalize 来清理资源
            4. 调用此函数后，传入的 reader 句柄将失效，不能再使用
        """
        func = OLAPlugDLLHelper.get_function("Finalize")
        return func(self.OLAObject, stmt)

    def GetDouble(self, stmt: int, iCol: int) -> float:
        """根据列索引获取当前行指定列的 double 值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            iCol: 列的索引，从 0 开始

        Returns:
            列的 double 值

        Notes:
            1. 用于从当前数据行中提取指定列的数值，并转换为 double 类型
            2. 如果列的数据类型不是数值类型，系统会尝试进行转换
            3. 如果转换失败或数据为 NULL，返回值可能是 0.0 或其他默认值
            4. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetDouble")
        return func(self.OLAObject, stmt, iCol)

    def GetInt32(self, stmt: int, iCol: int) -> int:
        """根据列索引获取当前行指定列的 int32 值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            iCol: 列的索引，从 0 开始

        Returns:
            列的 int32 值

        Notes:
            1. 用于从当前数据行中提取指定列的数值，并转换为 32 位整数类型
            2. 如果列的数据类型不是整数类型，系统会尝试进行转换
            3. 如果转换失败、数据为 NULL 或数值超出 int32 范围，行为是未定义的
            4. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetInt32")
        return func(self.OLAObject, stmt, iCol)

    def GetInt64(self, stmt: int, iCol: int) -> int:
        """根据列索引获取当前行指定列的 int64 值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            iCol: 列的索引，从 0 开始

        Returns:
            列的 int64 值

        Notes:
            1. 用于从当前数据行中提取指定列的数值，并转换为 64 位整数类型
            2. 适用于处理可能超出 32 位范围的大整数
            3. 如果列的数据类型不是整数类型，系统会尝试进行转换
            4. 如果转换失败、数据为 NULL 或数值超出 int64 范围，行为是未定义的
            5. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetInt64")
        return func(self.OLAObject, stmt, iCol)

    def GetString(self, stmt: int, iCol: int) -> str:
        """根据列索引获取当前行指定列的字符串值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            iCol: 列的索引，从 0 开始

        Returns:
            字符串值的指针

        Notes:
            1. 用于从当前数据行中提取指定列的文本数据
            2. 返回的字符串指针指向的数据由结果集管理，其生命周期与结果集相同
            3. 在调用 Finalize 释放结果集后，该指针将失效
            4. 如果列的数据类型不是文本类型，系统会将其转换为字符串
            5. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetString")
        return self.PtrToStringUTF8(func(self.OLAObject, stmt, iCol))

    def GetDoubleByColumnName(self, stmt: int, columnName: str) -> float:
        """None

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            columnName: 列的名称

        Returns:
            列的 double 值

        Notes:
            1. 功能与 GetDouble 相同，但通过列名而非索引来访问数据
            2. 内部通常先调用 GetColumnIndex 获取索引，再调用 GetDouble
            3. 使用列名访问数据可以提高代码的可读性和可维护性，避免因列顺序改变而引发错误
            4. 如果列名不存在，行为是未定义的，可能返回 0.0 或其他错误值
            5. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetDoubleByColumnName")
        return func(self.OLAObject, stmt, columnName)

    def GetInt32ByColumnName(self, stmt: int, columnName: str) -> int:
        """根据列名获取当前行指定列的 int32 值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            columnName: 列的名称

        Returns:
            列的 int32 值

        Notes:
            1. 功能与 GetInt32 相同，但通过列名而非索引来访问数据
            2. 使用列名可以避免硬编码列索引，使代码更灵活
            3. 如果列名不存在，行为是未定义的，可能返回 0 或其他错误值
            4. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetInt32ByColumnName")
        return func(self.OLAObject, stmt, columnName)

    def GetInt64ByColumnName(self, stmt: int, columnName: str) -> int:
        """根据列名获取当前行指定列的 int64 值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            columnName: 列的名称

        Returns:
            列的 int64 值

        Notes:
            1. 功能与 GetInt64 相同，但通过列名而非索引来访问数据
            2. 适用于通过列名访问大整数类型的数据
            3. 如果列名不存在，行为是未定义的，可能返回 0 或其他错误值
            4. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetInt64ByColumnName")
        return func(self.OLAObject, stmt, columnName)

    def GetStringByColumnName(self, stmt: int, columnName: str) -> str:
        """根据列名获取当前行指定列的字符串值

        Args:
            stmt: 结果集句柄，由 ExecuteReader 接口生成
            columnName: 列的名称

        Returns:
            字符串值的指针

        Notes:
            1. 功能与 GetString 相同，但通过列名而非索引来访问数据
            2. 返回的字符串指针生命周期与结果集相同
            3. 这是访问结果集数据最常用和最安全的方式之一，因为它不依赖于列的物理顺序
            4. 如果列名不存在，行为是未定义的，可能返回 NULL 或其他错误指针
            5. 调用此函数前必须确保已经通过 Read 成功读取到一行有效数据
        """
        func = OLAPlugDLLHelper.get_function("GetStringByColumnName")
        return self.PtrToStringUTF8(func(self.OLAObject, stmt, columnName))

    def InitOlaDatabase(self, db: int) -> int:
        """初始化ola相关数据库,包括olg_config,ola_image表

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于在打开的数据库上创建OLA系统所需的表和索引
            2. 此操作是幂等的，如果数据库已初始化，则不会重复创建表
            3. 必须在使用任何依赖OLA数据库结构的接口前调用此函数
            4. 初始化失败通常是因为数据库文件不可写或磁盘空间不足
        """
        func = OLAPlugDLLHelper.get_function("InitOlaDatabase")
        return func(self.OLAObject, db)

    def InitOlaImageFromDir(self, db: int, _dir: str, cover: int) -> int:
        """从指定目录初始化OLA图像数据

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            _dir: 图像文件所在的目录路径
            cover: 是否覆盖已存在的数据

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于批量导入指定目录下的所有图像文件到OLA数据库
            2. cover 参数控制是否覆盖数据库中已存在的同名图像数据
            3. 支持的图像格式通常包括 BMP, PNG, JPG 等常见格式
            4. 此操作可能耗时较长，取决于目录中文件的数量和大小
        """
        func = OLAPlugDLLHelper.get_function("InitOlaImageFromDir")
        return func(self.OLAObject, db, _dir, cover)

    def RemoveOlaImageFromDir(self, db: int, _dir: str) -> int:
        """移除指定文件夹下所有图片数据

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            _dir: 包含要移除图像的目录路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于批量删除数据库中与指定目录关联的所有OLA图像数据
            2. 此操作会删除所有在该目录下导入或与该目录路径匹配的图像记录
            3. 删除操作是永久性的，无法恢复
            4. 在执行此操作前，请确保不再需要这些图像数据，且没有其他功能依赖于它们
        """
        func = OLAPlugDLLHelper.get_function("RemoveOlaImageFromDir")
        return func(self.OLAObject, db, _dir)

    def ExportOlaImageDir(self, db: int, _dir: str, exportDir: str) -> int:
        """将OLA图像数据从数据库导出到指定目录

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            _dir: 包含要移除图像的目录路径
            exportDir: 导出的目标目录路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于将数据库中存储的所有OLA图像数据导出为文件
            2. 导出的文件将保存在 exportDir 指定的目录中
            3. 确保目标目录存在且有写入权限
            4. 此操作可用于备份图像数据或在不同系统间迁移数据
        """
        func = OLAPlugDLLHelper.get_function("ExportOlaImageDir")
        return func(self.OLAObject, db, _dir, exportDir)

    def ImportOlaImage(self, db: int, _dir: str, fileName: str, cover: int) -> int:
        """从文件导入单个OLA图像数据

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            _dir: 图像文件所在的目录路径
            fileName: 要导入的图像文件名
            cover: 是否覆盖已存在的图像数据

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于将单个图像文件导入到OLA数据库中，并指定其在库中的名称
            2. imagePath 必须指向一个有效的图像文件
            3. name 是该图像在数据库中的唯一标识符，后续操作将使用此名称
            4. cover 参数决定是否替换数据库中已存在的同名图像
        """
        func = OLAPlugDLLHelper.get_function("ImportOlaImage")
        return func(self.OLAObject, db, _dir, fileName, cover)

    def GetOlaImage(self, db: int, _dir: str, fileName: str) -> int:
        """从数据库中获取指定名称的OLA图像数据

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            _dir: 图片目录路径
            fileName: 图片文件名

        Returns:
            图像数据的指针，如果未找到则返回 0

        Notes:
            1. 该函数用于从OLA数据库中获取指定目录和文件名的图像数据，适用于从数据库中检索图像的场景。
            2. 如果图像不存在或操作失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息。
            3. 确保目录路径和文件名正确，且图像数据存在于数据库中，否则可能导致获取失败。
            4. 使用完返回的图像对象指针后，应妥善处理资源，避免内存泄漏。
        """
        func = OLAPlugDLLHelper.get_function("GetOlaImage")
        return func(self.OLAObject, db, _dir, fileName)

    def RemoveOlaImage(self, db: int, _dir: str, fileName: str) -> int:
        """从数据库中移除指定名称的OLA图像数据

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            _dir: 图像文件在数据库中的目录路径
            fileName: 图片文件名

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数用于从OLA数据库中移除指定目录和文件名的图像数据，适用于删除单个图像数据的场景。
            2. 如果移除失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息。
            3. 确保目录路径和文件名正确，且图像数据存在于数据库中，否则可能导致移除失败。
        """
        func = OLAPlugDLLHelper.get_function("RemoveOlaImage")
        return func(self.OLAObject, db, _dir, fileName)

    def SetDbConfig(self, db: int, key: str, value: str) -> int:
        """设置数据库配置项

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            key: 配置项的键名
            value: 配置项的值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于在数据库中存储键值对形式的配置信息
            2. 配置信息通常用于保存应用程序的设置或状态
            3. 如果键已存在，此操作将更新其值
            4. 配置项的存储是持久化的，即使关闭数据库后依然存在
        """
        func = OLAPlugDLLHelper.get_function("SetDbConfig")
        return func(self.OLAObject, db, key, value)

    def GetDbConfig(self, db: int, key: str) -> str:
        """获取数据库配置项的值

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            key: 配置项的键名

        Returns:
            配置项的值字符串指针，如果键不存在则返回 0

        Notes:
            1. 用于从数据库中读取指定键的配置信息
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 如果指定的键在数据库中不存在，函数返回 0
            4. 获取配置项是应用程序读取持久化设置的标准方式
        """
        func = OLAPlugDLLHelper.get_function("GetDbConfig")
        return self.PtrToStringUTF8(func(self.OLAObject, db, key))

    def RemoveDbConfig(self, db: int, key: str) -> int:
        """从数据库中移除指定的配置项

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            key: 配置项的键名

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于删除数据库中存储的特定配置项
            2. 删除后，再次调用 GetDbConfig 将无法获取该键的值
            3. 如果指定的键不存在，函数可能返回成功或失败，具体取决于实现
            4. 此操作不会影响其他配置项
        """
        func = OLAPlugDLLHelper.get_function("RemoveDbConfig")
        return func(self.OLAObject, db, key)

    def SetDbConfigEx(self, key: str, value: str) -> int:
        """设置带作用域的数据库配置项

        Args:
            key: 配置项的键名
            value: 配置项的值

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 与 SetDbConfig 类似，但增加了作用域（scope）参数
            2. 作用域可用于对配置项进行分类或隔离，例如按模块、用户或环境划分
            3. 相同的键名在不同作用域下可以存储不同的值
            4. 此函数提供了更灵活的配置管理能力
        """
        func = OLAPlugDLLHelper.get_function("SetDbConfigEx")
        return func(self.OLAObject, key, value)

    def GetDbConfigEx(self, key: str) -> str:
        """获取带作用域的数据库配置项的值

        Args:
            key: 配置项的键名

        Returns:
            配置项的值字符串指针，如果键不存在则返回 0

        Notes:
            1. 用于读取在特定作用域下存储的配置信息
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 必须同时提供正确的作用域和键名才能获取到值
            4. 如果指定的作用域和键的组合不存在，函数返回 0
        """
        func = OLAPlugDLLHelper.get_function("GetDbConfigEx")
        return self.PtrToStringUTF8(func(self.OLAObject, key))

    def RemoveDbConfigEx(self, key: str) -> int:
        """从数据库中移除带作用域的配置项

        Args:
            key: 配置项的键名

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于删除在特定作用域下存储的配置项
            2. 必须同时指定正确的作用域和键名才能成功删除
            3. 此操作只影响指定作用域下的特定键，不会影响其他作用域或无作用域的同名键
            4. 删除后，该作用域下的该键将不再存在
        """
        func = OLAPlugDLLHelper.get_function("RemoveDbConfigEx")
        return func(self.OLAObject, key)

    def InitDictFromDir(self, db: int, dict_name: str, dict_path: str, cover: int) -> int:
        """从指定目录中加载字库文件，并将其初始化到OLA数据库中

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 字库名称
            dict_path: 字库图片文件夹路径
            cover: 是否覆盖已存在的图像数据

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数用于从指定目录中加载字库图片文件，并将其初始化到OLA数据库中。适用于批量导入字库的场景
            2. cover 参数用于控制是否覆盖已存在的图像数据。设置为 1 时，会覆盖现有数据；设置为 0时，会跳过已存在的图像
            3. 如果初始化失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息
            4. 确保目录路径正确，且图像文件格式受支持，否则可能导致初始化失败
        """
        func = OLAPlugDLLHelper.get_function("InitDictFromDir")
        return func(self.OLAObject, db, dict_name, dict_path, cover)

    def InitDictFromTxt(self, db: int, dict_name: str, dict_path: str, cover: int) -> int:
        """

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 字库名称
            dict_path: 文本字库路径,如C:\\dicts\\mydict.txt
            cover: None

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数用于从txt字库文件中加载字库信息，并将其初始化到OLA数据库中。适用于批量导入字库的场景
            2. cover 参数用于控制是否覆盖已存在的图像数据。设置为 1 时，会覆盖现有数据；设置为 0时，会跳过已存在的图像。
            3. 如果初始化失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息
            4. 确保文本路径正确，且文本文件格式受支持，否则可能导致初始化失败
        """
        func = OLAPlugDLLHelper.get_function("InitDictFromTxt")
        return func(self.OLAObject, db, dict_name, dict_path, cover)

    def ImportDictWord(self, db: int, dict_name: str, pic_file_name: str, cover: int) -> int:
        """向指定字库中导入单个文字的图像

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 字库名称
            pic_file_name: 要导入的图像文件名
            cover: 是否覆盖已存在的图像数据，可选值:
                0: 不覆盖
                1: 覆盖

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数用于将指定目录中的字库图像文件导入到OLA数据库中，适用于单个字库图像文件的导入场景。
            2. cover 参数用于控制是否覆盖已存在的图像数据。设置为 1 时，会覆盖现有数据；设置为 0时，会跳过已存在的图像。
            3. 如果导入失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息。
            4. 确保目录路径和文件名正确，且图像文件格式受支持，否则可能导致导入失败。
        """
        func = OLAPlugDLLHelper.get_function("ImportDictWord")
        return func(self.OLAObject, db, dict_name, pic_file_name, cover)

    def ExportDict(self, db: int, dict_name: str, export_dir: str) -> int:
        """将OLA数据库中的图像数据导出到指定目录

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 字库名称
            export_dir: 导出路径

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数用于将OLA数据库中的图像数据导出到指定目录，适用于批量导出字库图像数据的场景
            2. 如果导出失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息
            3. 确保目录路径正确，且图像数据存在于数据库中，否则可能导致导出失败
            4. 导出的图像文件将保存在 exportDir 指定的目录中，确保目标目录有足够的存储空间
        """
        func = OLAPlugDLLHelper.get_function("ExportDict")
        return func(self.OLAObject, db, dict_name, export_dir)

    def RemoveDict(self, db: int, dict_name: str) -> int:
        """从数据库中移除整个字库

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 要移除的字库名称

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于删除数据库中存储的整个字库及其所有图像数据
            2. 此操作是永久性的，会删除该字库下的所有字符图像
            3. 删除后，任何使用该字库的识别操作都将失败
            4. 在执行此操作前应确保没有其他进程或功能依赖于该字库
        """
        func = OLAPlugDLLHelper.get_function("RemoveDict")
        return func(self.OLAObject, db, dict_name)

    def RemoveDictWord(self, db: int, dict_name: str, word: str) -> int:
        """移除词典词条

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 字库名称
            word: 要移除的文字

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 用于从字库中删除特定字符的图像数据
            2. 此操作只影响指定字库中的指定字符，不会影响字库中的其他字符
            3. 删除后，OCR识别将无法再识别该字符
            4. 此接口适用于维护和更新字库，移除不再需要或错误的字符
        """
        func = OLAPlugDLLHelper.get_function("RemoveDictWord")
        return func(self.OLAObject, db, dict_name, word)

    def GetDictImage(self, db: int, dict_name: str, word: str, gap: int, _dir: int) -> int:
        """读取字库图片

        Args:
            db: 数据库连接句柄，由 OpenDatabase 接口生成
            dict_name: 字库名称
            word: 要读取的文字
            gap: 文字间隔，单位为像素
            _dir: 拼接方向，可选值:
                0: 水平拼接
                1: 垂直拼接

        Returns:
            图像对象的指针。如果操作失败，返回 0

        Notes:
            1. 该函数用于从OLA数据库中获取指定字典名称和文字的图像数据，适用于从数据库中查找指定文字的场景
            2. 如果图像不存在或操作失败，函数将返回 0。可以通过 GetDatabaseError 函数获取详细的错误信息
            3. 确保字典名称和文字正确，且图像数据存在于数据库中，否则可能导致获取失败
            4. 使用完返回的图像对象指针后，应妥善处理资源，避免内存泄漏
        """
        func = OLAPlugDLLHelper.get_function("GetDictImage")
        return func(self.OLAObject, db, dict_name, word, gap, _dir)

    def OpenVideo(self, videoPath: str) -> int:
        """打开视频文件

        Args:
            videoPath: 视频文件路径（支持本地文件和网络流）

        Returns:
            视频句柄，失败返回0

        Notes:
            1. 返回的句柄用于后续的视频操作，使用完毕后需调用CloseVideo释放
        """
        func = OLAPlugDLLHelper.get_function("OpenVideo")
        return func(self.OLAObject, videoPath)

    def OpenCamera(self, deviceIndex: int) -> int:
        """打开摄像头设备

        Args:
            deviceIndex: 摄像头设备索引（默认0）

        Returns:
            视频句柄，失败返回0

        Notes:
            1. 返回的句柄用于后续的视频操作，使用完毕后需调用CloseVideo释放
        """
        func = OLAPlugDLLHelper.get_function("OpenCamera")
        return func(self.OLAObject, deviceIndex)

    def CloseVideo(self, videoHandle: int) -> int:
        """关闭视频并释放资源

        Args:
            videoHandle: 视频句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CloseVideo")
        return func(self.OLAObject, videoHandle)

    def IsVideoOpened(self, videoHandle: int) -> int:
        """检查视频是否已打开

        Args:
            videoHandle: 视频句柄

        Returns:
            检查结果
                0: 未打开
                1: 已打开

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("IsVideoOpened")
        return func(self.OLAObject, videoHandle)

    def GetVideoInfo(self, videoHandle: int) -> str:
        """获取视频基本信息（JSON格式）

        Args:
            videoHandle: 视频句柄

        Returns:
            返回包含视频信息的JSON字符串指针，需调用FreeStringPtr释放；失败返回0

        Notes:
            1. JSON包含：width, height, fps, totalFrames, duration, codecName, fileSize
        """
        func = OLAPlugDLLHelper.get_function("GetVideoInfo")
        return self.PtrToStringUTF8(func(self.OLAObject, videoHandle))

    def GetVideoWidth(self, videoHandle: int) -> int:
        """获取视频宽度

        Args:
            videoHandle: 视频句柄

        Returns:
            视频宽度（像素），失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetVideoWidth")
        return func(self.OLAObject, videoHandle)

    def GetVideoHeight(self, videoHandle: int) -> int:
        """获取视频高度

        Args:
            videoHandle: 视频句柄

        Returns:
            视频高度（像素），失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetVideoHeight")
        return func(self.OLAObject, videoHandle)

    def GetVideoFPS(self, videoHandle: int) -> float:
        """获取视频帧率

        Args:
            videoHandle: 视频句柄

        Returns:
            视频帧率（FPS），失败返回0.0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetVideoFPS")
        return func(self.OLAObject, videoHandle)

    def GetVideoTotalFrames(self, videoHandle: int) -> int:
        """获取视频总帧数

        Args:
            videoHandle: 视频句柄

        Returns:
            视频总帧数，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetVideoTotalFrames")
        return func(self.OLAObject, videoHandle)

    def GetVideoDuration(self, videoHandle: int) -> float:
        """获取视频时长

        Args:
            videoHandle: 视频句柄

        Returns:
            视频时长（秒），失败返回0.0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetVideoDuration")
        return func(self.OLAObject, videoHandle)

    def GetCurrentFrameIndex(self, videoHandle: int) -> int:
        """获取当前帧位置

        Args:
            videoHandle: 视频句柄

        Returns:
            当前帧索引，失败返回-1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetCurrentFrameIndex")
        return func(self.OLAObject, videoHandle)

    def GetCurrentTimestamp(self, videoHandle: int) -> float:
        """获取当前时间戳

        Args:
            videoHandle: 视频句柄

        Returns:
            当前时间戳（秒），失败返回0.0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetCurrentTimestamp")
        return func(self.OLAObject, videoHandle)

    def ReadNextFrame(self, videoHandle: int) -> int:
        """读取下一帧

        Args:
            videoHandle: 视频句柄

        Returns:
            图像句柄（BGRA格式），失败返回0

        Notes:
            1. 返回的图像句柄由内部管理，不需要手动释放
        """
        func = OLAPlugDLLHelper.get_function("ReadNextFrame")
        return func(self.OLAObject, videoHandle)

    def ReadFrameAtIndex(self, videoHandle: int, frameIndex: int) -> int:
        """读取指定索引的帧

        Args:
            videoHandle: 视频句柄
            frameIndex: 帧索引（从0开始）

        Returns:
            图像句柄（BGRA格式），失败返回0

        Notes:
            1. 返回的图像句柄由内部管理，不需要手动释放
        """
        func = OLAPlugDLLHelper.get_function("ReadFrameAtIndex")
        return func(self.OLAObject, videoHandle, frameIndex)

    def ReadFrameAtTime(self, videoHandle: int, timestamp: float) -> int:
        """读取指定时间戳的帧

        Args:
            videoHandle: 视频句柄
            timestamp: 时间戳（秒）

        Returns:
            图像句柄（BGRA格式），失败返回0

        Notes:
            1. 返回的图像句柄由内部管理，不需要手动释放
        """
        func = OLAPlugDLLHelper.get_function("ReadFrameAtTime")
        return func(self.OLAObject, videoHandle, timestamp)

    def ReadCurrentFrame(self, videoHandle: int) -> int:
        """读取当前帧（不移动位置）

        Args:
            videoHandle: 视频句柄

        Returns:
            图像句柄（BGRA格式），失败返回0

        Notes:
            1. 返回的图像句柄由内部管理，不需要手动释放
        """
        func = OLAPlugDLLHelper.get_function("ReadCurrentFrame")
        return func(self.OLAObject, videoHandle)

    def SeekToFrame(self, videoHandle: int, frameIndex: int) -> int:
        """跳转到指定帧

        Args:
            videoHandle: 视频句柄
            frameIndex: 目标帧索引

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SeekToFrame")
        return func(self.OLAObject, videoHandle, frameIndex)

    def SeekToTime(self, videoHandle: int, timestamp: float) -> int:
        """跳转到指定时间

        Args:
            videoHandle: 视频句柄
            timestamp: 目标时间戳（秒）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SeekToTime")
        return func(self.OLAObject, videoHandle, timestamp)

    def SeekToBeginning(self, videoHandle: int) -> int:
        """跳转到视频开头

        Args:
            videoHandle: 视频句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SeekToBeginning")
        return func(self.OLAObject, videoHandle)

    def SeekToEnd(self, videoHandle: int) -> int:
        """跳转到视频结尾

        Args:
            videoHandle: 视频句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SeekToEnd")
        return func(self.OLAObject, videoHandle)

    def ExtractFramesToFiles(self, videoHandle: int, startFrame: int, endFrame: int, step: int, outputDir: str, imageFormat: str, jpegQuality: int) -> int:
        """批量提取视频帧并保存为文件

        Args:
            videoHandle: 视频句柄
            startFrame: 起始帧索引
            endFrame: 结束帧索引（-1表示到视频末尾）
            step: 帧间隔（1表示每帧都提取）
            outputDir: 输出目录
            imageFormat: 图像格式（"png"、"jpg"等）
            jpegQuality: JPEG质量（0-100）

        Returns:
            返回提取的帧数，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ExtractFramesToFiles")
        return func(self.OLAObject, videoHandle, startFrame, endFrame, step, outputDir, imageFormat, jpegQuality)

    def ExtractFramesByInterval(self, videoHandle: int, intervalSeconds: float, outputDir: str, imageFormat: str) -> int:
        """按时间间隔提取帧并保存为文件

        Args:
            videoHandle: 视频句柄
            intervalSeconds: 时间间隔（秒）
            outputDir: 输出目录
            imageFormat: 图像格式（"png"、"jpg"等）

        Returns:
            返回提取的帧数，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ExtractFramesByInterval")
        return func(self.OLAObject, videoHandle, intervalSeconds, outputDir, imageFormat)

    def ExtractKeyFrames(self, videoHandle: int, threshold: float, maxFrames: int, outputDir: str, imageFormat: str) -> int:
        """提取关键帧（基于场景变化检测）

        Args:
            videoHandle: 视频句柄
            threshold: 场景变化阈值（0-1）
            maxFrames: 最大提取帧数（0表示不限制）
            outputDir: 输出目录
            imageFormat: 图像格式（"png"、"jpg"等）

        Returns:
            返回提取的关键帧数，失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ExtractKeyFrames")
        return func(self.OLAObject, videoHandle, threshold, maxFrames, outputDir, imageFormat)

    def SaveCurrentFrame(self, videoHandle: int, outputPath: str, quality: int) -> int:
        """保存当前帧为图片文件

        Args:
            videoHandle: 视频句柄
            outputPath: 输出文件路径
            quality: 图片质量（对于JPEG，范围0-100）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SaveCurrentFrame")
        return func(self.OLAObject, videoHandle, outputPath, quality)

    def SaveFrameAtIndex(self, videoHandle: int, frameIndex: int, outputPath: str, quality: int) -> int:
        """保存指定帧为图片文件

        Args:
            videoHandle: 视频句柄
            frameIndex: 帧索引
            outputPath: 输出文件路径
            quality: 图片质量（对于JPEG，范围0-100）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("SaveFrameAtIndex")
        return func(self.OLAObject, videoHandle, frameIndex, outputPath, quality)

    def FrameToBase64(self, videoHandle: int, format: str) -> str:
        """将当前帧转换为Base64字符串

        Args:
            videoHandle: 视频句柄
            format: 图片格式（"png"、"jpg"等）

        Returns:
            返回Base64编码的图片数据字符串指针，需调用FreeStringPtr释放；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FrameToBase64")
        return self.PtrToStringUTF8(func(self.OLAObject, videoHandle, format))

    def CalculateFrameSimilarity(self, frame1: int, frame2: int) -> float:
        """计算两帧之间的相似度

        Args:
            frame1: 第一帧图像句柄
            frame2: 第二帧图像句柄

        Returns:
            相似度（0-1，1表示完全相同）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CalculateFrameSimilarity")
        return func(self.OLAObject, frame1, frame2)

    def GetVideoInfoFromPath(self, videoPath: str) -> str:
        """快速获取视频文件信息（无需打开整个视频）

        Args:
            videoPath: 视频文件路径

        Returns:
            返回包含视频信息的JSON字符串指针，需调用FreeStringPtr释放；失败返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetVideoInfoFromPath")
        return self.PtrToStringUTF8(func(self.OLAObject, videoPath))

    def IsValidVideoFile(self, videoPath: str) -> int:
        """检查视频文件是否有效

        Args:
            videoPath: 视频文件路径

        Returns:
            检查结果
                0: 无效
                1: 有效

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("IsValidVideoFile")
        return func(self.OLAObject, videoPath)

    def ExtractSingleFrame(self, videoPath: str, frameIndex: int) -> int:
        """快速提取单帧（无需保持视频打开状态）

        Args:
            videoPath: 视频文件路径
            frameIndex: 帧索引

        Returns:
            图像句柄（BGRA格式），失败返回0

        Notes:
            1. 返回的图像句柄需调用FreeImagePtr释放
        """
        func = OLAPlugDLLHelper.get_function("ExtractSingleFrame")
        return func(self.OLAObject, videoPath, frameIndex)

    def ExtractThumbnail(self, videoPath: str) -> int:
        """快速提取视频第一帧（常用于缩略图）

        Args:
            videoPath: 视频文件路径

        Returns:
            图像句柄（BGRA格式），失败返回0

        Notes:
            1. 返回的图像句柄需调用FreeImagePtr释放
        """
        func = OLAPlugDLLHelper.get_function("ExtractThumbnail")
        return func(self.OLAObject, videoPath)

    def ConvertVideo(self, inputPath: str, outputPath: str, codec: str, fps: float) -> int:
        """转换视频格式

        Args:
            inputPath: 输入视频路径
            outputPath: 输出视频路径
            codec: 编解码器（"H264", "XVID", "MJPG"等）
            fps: 输出帧率（-1表示使用原始帧率）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ConvertVideo")
        return func(self.OLAObject, inputPath, outputPath, codec, fps)

    def ResizeVideo(self, inputPath: str, outputPath: str, width: int, height: int) -> int:
        """调整视频尺寸

        Args:
            inputPath: 输入视频路径
            outputPath: 输出视频路径
            width: 目标宽度
            height: 目标高度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ResizeVideo")
        return func(self.OLAObject, inputPath, outputPath, width, height)

    def TrimVideo(self, inputPath: str, outputPath: str, startTime: float, endTime: float) -> int:
        """剪切视频片段

        Args:
            inputPath: 输入视频路径
            outputPath: 输出视频路径
            startTime: 起始时间（秒）
            endTime: 结束时间（秒）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("TrimVideo")
        return func(self.OLAObject, inputPath, outputPath, startTime, endTime)

    def CreateVideoFromImages(self, imageDir: str, outputPath: str, fps: float, codec: str) -> int:
        """从图片序列创建视频

        Args:
            imageDir: 图片目录路径
            outputPath: 输出视频路径
            fps: 帧率
            codec: 编解码器（"H264"等）

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 图片文件名应按字母顺序排列
        """
        func = OLAPlugDLLHelper.get_function("CreateVideoFromImages")
        return func(self.OLAObject, imageDir, outputPath, fps, codec)

    def DetectSceneChanges(self, videoPath: str, threshold: float) -> str:
        """检测视频中的场景变化点

        Args:
            videoPath: 视频文件路径
            threshold: 场景变化阈值（0-1）

        Returns:
            返回场景变化帧索引的JSON数组字符串，需调用FreeStringPtr释放；失败返回0

        Notes:
            1. JSON格式：[0, 123, 456, ...]
        """
        func = OLAPlugDLLHelper.get_function("DetectSceneChanges")
        return self.PtrToStringUTF8(func(self.OLAObject, videoPath, threshold))

    def CalculateAverageBrightness(self, videoPath: str) -> float:
        """计算视频平均亮度

        Args:
            videoPath: 视频文件路径

        Returns:
            平均亮度（0-255），失败返回-1

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("CalculateAverageBrightness")
        return func(self.OLAObject, videoPath)

    def DetectMotion(self, videoPath: str, threshold: float) -> str:
        """检测视频中的运动

        Args:
            videoPath: 视频文件路径
            threshold: 运动检测阈值（建议值：30.0）

        Returns:
            返回包含运动的帧索引的JSON数组字符串，需调用FreeStringPtr释放；失败返回0

        Notes:
            1. JSON格式：[10, 25, 67, ...]
        """
        func = OLAPlugDLLHelper.get_function("DetectMotion")
        return self.PtrToStringUTF8(func(self.OLAObject, videoPath, threshold))

    def SetWindowState(self, hwnd: int, state: int) -> int:
        """设置窗口的状态（如显示、隐藏、最小化、最大化等）

        Args:
            hwnd: 窗口句柄
            state: 窗口状态标志，窗口状态标志，可选值如下，可选值:
                0: 关闭指定窗口（发送WM_CLOSE消息）
                1: 激活指定窗口（设为前台窗口）
                2: 最小化指定窗口，但不激活
                3: 最小化指定窗口，并释放内存（适用于长期最小化）
                4: 最大化指定窗口，同时激活窗口
                5: 恢复指定窗口到正常大小，但不激活
                6: 隐藏指定窗口（窗口不可见但仍在运行）
                7: 显示指定窗口（使隐藏的窗口重新可见）
                8: 置顶指定窗口（窗口始终保持在最前）
                9: 取消置顶指定窗口（恢复正常Z序）
                10: 禁止指定窗口（使窗口无法接收输入）
                11: 取消禁止指定窗口（恢复窗口输入功能）
                12: 恢复并激活指定窗口（从最小化状态）
                13: 强制结束窗口所在进程（谨慎使用）
                14: 闪烁指定的窗口（吸引用户注意）
                15: 使指定的窗口获取输入焦点

        Returns:
            操作结果
                0: 设置失败（可能原因：无效的窗口句柄、无效的状态标志、窗口已被销毁等）
                1: 设置成功

        Notes:
            1. 在使用强制结束进程（flag=13）时要特别谨慎，确保已保存相关数据
            2. 某些状态组合可能会相互影响，建议按照逻辑顺序设置
            3. 窗口状态的改变可能会触发窗口的相关事件和回调
            4. 部分状态设置可能会受到系统或应用程序的安全策略限制
        """
        func = OLAPlugDLLHelper.get_function("SetWindowState")
        return func(self.OLAObject, hwnd, state)

    def FindWindow(self, class_name: str, title: str) -> int:
        """根据窗口标题或类名查找窗口

        Args:
            class_name: 窗口类名，支持模糊匹配。如果为空字符串，则匹配所有类名。
            title: 窗口标题，支持模糊匹配。如果为空字符串，则匹配所有标题。

        Returns:
            返回找到的窗口句柄，如果未找到匹配的窗口，返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("FindWindow")
        return func(self.OLAObject, class_name, title)

    def GetClipboard(self) -> int:
        """获取系统剪贴板的文本内容

        Returns:
            剪贴板文本的指针，如果失败或剪贴板无文本则返回 0

        Notes:
            1. 该函数打开剪贴板，获取 CF_TEXT 格式的文本内容并返回
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 在调用此函数前，应确保剪贴板中包含文本数据
            4. 如果剪贴板被其他程序占用，函数可能失败
        """
        func = OLAPlugDLLHelper.get_function("GetClipboard")
        return func(self.OLAObject)

    def SetClipboard(self, text: str) -> int:
        """设置系统剪贴板的文本内容

        Args:
            text: 要设置的文本内容

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数将指定的文本字符串放入系统剪贴板
            2. 执行后，文本内容可被其他应用程序粘贴使用
            3. 函数会自动打开和关闭剪贴板
            4. 如果剪贴板被其他程序长时间占用，设置可能会失败
        """
        func = OLAPlugDLLHelper.get_function("SetClipboard")
        return func(self.OLAObject, text)

    def SendPaste(self, hwnd: int) -> int:
        """向指定窗口发送粘贴命令（模拟 Ctrl+V）

        Args:
            hwnd: 目标窗口的句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数向指定窗口发送 WM_PASTE 消息，触发其粘贴操作
            2. 目标窗口必须是可接收文本输入的控件（如编辑框）
            3. 执行前通常需要先调用 SetClipboard 将文本放入剪贴板
            4. 此操作是发送消息，不保证目标窗口一定会执行粘贴
        """
        func = OLAPlugDLLHelper.get_function("SendPaste")
        return func(self.OLAObject, hwnd)

    def GetWindow(self, hwnd: int, flag: int) -> int:
        """获取给定窗口相关的窗口句柄，如父窗口、子窗口、相邻窗口等

        Args:
            hwnd: 窗口句柄
            flag: 指定要获取的窗口类型，可选值:
                0: 获取父窗口
                1: 获取第一个子窗口
                2: 获取First窗口
                3: 获取Last窗口
                4: 获取下一个窗口
                5: 获取上一个窗口
                6: 获取拥有者窗口
                7: 获取顶层窗口

        Returns:
            返回指定类型的窗口句柄

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetWindow")
        return func(self.OLAObject, hwnd, flag)

    def GetWindowTitle(self, hwnd: int) -> str:
        """获取指定窗口的标题文本

        Args:
            hwnd: 窗口句柄

        Returns:
            窗口标题字符串的指针，如果失败则返回 0

        Notes:
            1. 该函数获取窗口标题栏上显示的文本
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 对于没有标题栏的窗口，返回的可能是空字符串或窗口名称
            4. 如果窗口句柄无效或不可访问，函数将失败
        """
        func = OLAPlugDLLHelper.get_function("GetWindowTitle")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd))

    def GetWindowClass(self, hwnd: int) -> str:
        """获取指定窗口的类名

        Args:
            hwnd: 窗口句柄

        Returns:
            窗口类名字符串的指针，如果失败则返回 0

        Notes:
            1. 窗口类名是在创建窗口时注册的，标识了窗口的基本类型和行为
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 例如，记事本主窗口的类名通常是 "Notepad"
            4. 类名对于窗口识别和自动化操作非常重要
        """
        func = OLAPlugDLLHelper.get_function("GetWindowClass")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd))

    def GetWindowRect(self, hwnd: int, x1: int = None, y1: int = None, x2: int = None, y2: int = None) -> Tuple[int, int, int, int, int]:
        """获取指定窗口的矩形区域（相对于屏幕）

        Args:
            hwnd: 窗口句柄
            x1: 返回窗口左上角的X坐标
            y1: 返回窗口左上角的Y坐标
            x2: 返回窗口右下角的X坐标
            y2: 返回窗口右下角的Y坐标

        Returns:
            返回元组: (操作结果, 返回窗口左上角的X坐标, 返回窗口左上角的Y坐标, 返回窗口右下角的X坐标, 返回窗口右下角的Y坐标)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. 窗口必须处于可见状态，否则获取可能失败
            2. 返回的坐标是相对于屏幕左上角的绝对坐标
            3. 返回的区域包括窗口的非客户区（标题栏、边框等）
            4. 如果只需要获取客户区域，请使用 GetClientRect 函数
            5. 对于多显示器系统，坐标值可能为负数，这表示窗口位于主显示器左侧或上方的显示器上
        """
        func = OLAPlugDLLHelper.get_function("GetWindowRect")
        return func(self.OLAObject, hwnd, x1, y1, x2, y2)

    def GetWindowProcessPath(self, hwnd: int) -> str:
        """获取指定窗口对应进程的可执行文件路径

        Args:
            hwnd: 窗口句柄

        Returns:
            进程路径字符串的指针，如果失败则返回 0

        Notes:
            1. 该函数通过窗口句柄获取其所属进程的完整路径
            2. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            3. 路径格式如 "C:\\Windows\\notepad.exe"
            4. 在某些权限受限或系统保护的进程中，获取路径可能会失败
        """
        func = OLAPlugDLLHelper.get_function("GetWindowProcessPath")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd))

    def GetWindowState(self, hwnd: int, flag: int) -> int:
        """获取指定窗口的当前状态

        Args:
            hwnd: 窗口句柄
            flag: 要检查的窗口状态，可选值:
                0: 判断窗口是否存在（检查句柄的有效性）
                1: 判断窗口是否处于激活状态（是否为前台窗口）
                2: 判断窗口是否可见（是否显示在屏幕上）
                3: 判断窗口是否最小化（是否处于最小化状态）
                4: 判断窗口是否最大化（是否处于最大化状态）
                5: 判断窗口是否置顶（是否总在最前）
                6: 判断窗口是否无响应（是否处于"未响应"状态）
                7: 判断窗口是否可用（是否能接收用户输入）

        Returns:
            操作结果
                0: 指定的状态条件不满足（或窗口句柄无效）
                1: 指定的状态条件满足

        Notes:
            1. 在检查窗口状态前，建议先使用flag=0确认窗口是否存在
            2. 某些状态可能会同时存在（如窗口可以同时是可见的和置顶的）
            3. 窗口的"无响应"状态检查可能需要一定时间
            4. 对于系统窗口或特权窗口，某些状态可能无法正确获取
        """
        func = OLAPlugDLLHelper.get_function("GetWindowState")
        return func(self.OLAObject, hwnd, flag)

    def GetForegroundWindow(self) -> int:
        """获取当前处于活动状态（最前端）的窗口句柄

        Returns:
            前台窗口的句柄，如果没有前台窗口则返回 0

        Notes:
            1. 该函数返回当前用户正在交互的窗口
            2. 此窗口通常位于所有其他窗口之上
            3. 获取的句柄可用于对前台窗口进行操作
            4. 在多显示器或特定系统设置下，前台窗口可能为空
        """
        func = OLAPlugDLLHelper.get_function("GetForegroundWindow")
        return func(self.OLAObject)

    def GetWindowProcessId(self, hwnd: int) -> int:
        """获取指定窗口所属进程的ID

        Args:
            hwnd: 窗口句柄

        Returns:
            进程ID，如果失败则返回 0

        Notes:
            1. 每个进程在系统中都有一个唯一的标识符（PID）
            2. 获取进程ID可用于进一步的进程管理操作，如终止进程
            3. 此函数是连接窗口管理和进程管理的桥梁
            4. 如果窗口属于系统进程或权限受限，获取PID可能会失败
        """
        func = OLAPlugDLLHelper.get_function("GetWindowProcessId")
        return func(self.OLAObject, hwnd)

    def GetClientSize(self, hwnd: int, width: int = None, height: int = None) -> Tuple[int, int, int]:
        """获取指定窗口客户区的大小

        Args:
            hwnd: 窗口句柄
            width: 指向接收客户区宽度的变量
            height: 指向接收客户区高度的变量

        Returns:
            返回元组: (操作结果, 指向接收客户区宽度的变量, 指向接收客户区高度的变量)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. 客户区是窗口中用于显示内容的区域，不包括标题栏、边框和滚动条
            2. 获取的尺寸常用于绘制操作或调整内部控件布局
            3. 坐标相对于窗口客户区的左上角(0,0)
            4. 此函数对于UI自动化和截图定位至关重要
        """
        func = OLAPlugDLLHelper.get_function("GetClientSize")
        return func(self.OLAObject, hwnd, width, height)

    def GetMousePointWindow(self) -> int:
        """获取鼠标光标所在位置的窗口句柄

        Returns:
            鼠标光标下最顶层窗口的句柄，如果失败则返回 0

        Notes:
            1. 该函数返回当前鼠标指针位置处的窗口句柄
            2. 返回的是包含鼠标光标的最顶层窗口，不一定是活动窗口
            3. 常用于实现“点击取色”或“窗口信息抓取”等功能
            4. 在鼠标位于桌面或无窗口区域时，行为可能未定义
        """
        func = OLAPlugDLLHelper.get_function("GetMousePointWindow")
        return func(self.OLAObject)

    def GetSpecialWindow(self, flag: int) -> int:
        """获取特殊系统窗口的句柄

        Args:
            flag: 特殊窗口的标识符

        Returns:
            特定系统窗口的句柄，如果失败则返回 0

        Notes:
            1. 用于获取如桌面窗口、任务栏、开始按钮等系统级窗口的句柄
            2. flag 参数指定要获取的窗口类型，如 0-桌面, 1-任务栏等
            3. 这些窗口句柄可用于系统级的界面操作或信息获取
            4. 不同系统版本下，特殊窗口的句柄和行为可能有所不同
        """
        func = OLAPlugDLLHelper.get_function("GetSpecialWindow")
        return func(self.OLAObject, flag)

    def GetClientRect(self, hwnd: int, x1: int = None, y1: int = None, x2: int = None, y2: int = None) -> Tuple[int, int, int, int, int]:
        """获取指定窗口客户区的矩形区域

        Args:
            hwnd: 窗口句柄
            x1: 返回客户区左上角的X坐标，总是0
            y1: 返回客户区左上角的Y坐标，总是0
            x2: 返回客户区右下角的X坐标，即客户区宽度
            y2: 返回客户区右下角的Y坐标，即客户区高度

        Returns:
            返回元组: (操作结果, 返回客户区左上角的X坐标，总是0, 返回客户区左上角的Y坐标，总是0, 返回客户区右下角的X坐标，即客户区宽度, 返回客户区右下角的Y坐标，即客户区高度)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. 窗口必须处于可见状态，否则获取可能失败
            2. 返回的坐标是相对于客户区左上角的相对坐标，(x1,y1)总是(0,0)
            3. (x2,y2)表示客户区的宽度和高度，而不是屏幕坐标
            4. 如果需要获取包含非客户区的窗口区域，请使用 GetWindowRect 函数
            5. 如果需要将客户区坐标转换为屏幕坐标，请使用 ClientToScreen 函数与 GetWindowRect
        """
        func = OLAPlugDLLHelper.get_function("GetClientRect")
        return func(self.OLAObject, hwnd, x1, y1, x2, y2)

    def SetWindowText(self, hwnd: int, title: str) -> int:
        """设置指定窗口的标题文本

        Args:
            hwnd: 窗口句柄
            title: 要设置的新标题

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数会改变窗口标题栏上显示的文本
            2. 新标题会立即反映在UI上
            3. 并非所有窗口都允许修改标题，某些系统窗口或受保护的应用可能忽略此操作
            4. 修改标题可能会影响基于标题的窗口查找逻辑
        """
        func = OLAPlugDLLHelper.get_function("SetWindowText")
        return func(self.OLAObject, hwnd, title)

    def SetWindowSize(self, hwnd: int, width: int, height: int) -> int:
        """设置指定窗口的大小和位置

        Args:
            hwnd: 窗口句柄
            width: 窗口的目标宽度（像素），包括边框，必须大于0
            height: 窗口的目标高度（像素），包括标题栏和边框，必须大于0

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数可以同时改变窗口的位置和大小
            2. 坐标是相对于屏幕的绝对坐标
            3. flags 参数可控制是否重绘窗口、是否发送消息等
            4. 此操作相当于直接调用 Windows API 的 MoveWindow
        """
        func = OLAPlugDLLHelper.get_function("SetWindowSize")
        return func(self.OLAObject, hwnd, width, height)

    def SetClientSize(self, hwnd: int, width: int, height: int) -> int:
        """设置指定窗口客户区的大小

        Args:
            hwnd: 窗口句柄
            width: 客户区的新宽度
            height: 客户区的新高度

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 与 SetWindowSize 不同，此函数设置的是客户区尺寸
            2. 系统会根据客户区大小自动调整窗口的整体大小以包含边框和标题栏
            3. 常用于确保窗口内容区域达到指定尺寸
            4. 设置后，窗口的总体尺寸会大于或等于指定的客户区尺寸
        """
        func = OLAPlugDLLHelper.get_function("SetClientSize")
        return func(self.OLAObject, hwnd, width, height)

    def SetWindowTransparent(self, hwnd: int, alpha: int) -> int:
        """设置窗口的透明度

        Args:
            hwnd: 窗口句柄
            alpha: 透明度值，范围 0-255，0为完全透明，255为完全不透明

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数通过设置窗口的分层属性来实现透明效果
            2. 窗口必须支持分层属性（WS_EX_LAYERED）才能设置透明度
            3. 透明度影响整个窗口，包括标题栏和边框
            4. 此功能常用于制作半透明界面或浮动工具窗口
        """
        func = OLAPlugDLLHelper.get_function("SetWindowTransparent")
        return func(self.OLAObject, hwnd, alpha)

    def FindWindowEx(self, parent: int, class_name: str, title: str) -> int:
        """在父窗口内查找子窗口

        Args:
            parent: 父窗口句柄，为 0 时查找所有顶层窗口
            class_name: 要查找的子窗口类名
            title: 要查找的子窗口标题

        Returns:
            找到的子窗口句柄，未找到则返回 0

        Notes:
            1. 该函数用于枚举和查找特定的子窗口
            2. hwndChildAfter 用于从指定位置开始查找，为 NULL 时查找第一个匹配窗口
            3. 支持类名和标题的模糊匹配
            4. 是实现复杂UI自动化（如操作对话框中的按钮）的关键函数
        """
        func = OLAPlugDLLHelper.get_function("FindWindowEx")
        return func(self.OLAObject, parent, class_name, title)

    def FindWindowByProcess(self, process_name: str, class_name: str, title: str) -> int:
        """根据进程名称、窗口类名和标题查找可见窗口。此函数提供了一种灵活的方式来定位特定进程的窗口

        Args:
            process_name: 进程名称（如"notepad.exe"），精确匹配但不区分大小写
            class_name: 窗口类名，支持模糊匹配。如果为空字符串("")，则匹配所有类名
            title: 窗口标题，支持模糊匹配。如果为空字符串("")，则匹配所有标题

        Returns:
            返回找到的窗口句柄，未找到则返回 0

        Notes:
            1. 进程名称必须包含扩展名（如".exe"），且不区分大小写
            2. 类名和标题支持模糊匹配，可以只包含部分文本
            3. 空字符串参数会匹配任意值，可用于通配搜索
            4. 如果有多个匹配的窗口，函数返回第一个找到的窗口
            5. 建议使用更具体的搜索条件以提高查找准确性
            6. 某些系统进程的窗口可能无法被找到
            7. 进程必须具有可见的主窗口才能被找到
            8. 可以结合 GetWindowState 验证找到的窗口
        """
        func = OLAPlugDLLHelper.get_function("FindWindowByProcess")
        return func(self.OLAObject, process_name, class_name, title)

    def MoveWindow(self, hwnd: int, x: int, y: int) -> int:
        """移动指定窗口到新的位置

        Args:
            hwnd: 窗口句柄
            x: 窗口左上角的新x坐标
            y: 窗口左上角的新y坐标

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数只改变窗口的位置，不改变其大小
            2. 坐标是相对于屏幕的绝对坐标
            3. 移动操作会触发窗口的 WM_WINDOWPOSCHANGING/CHANGED 消息
            4. 此函数是 SetWindowSize 的一个特例（只改变位置）
        """
        func = OLAPlugDLLHelper.get_function("MoveWindow")
        return func(self.OLAObject, hwnd, x, y)

    def GetScaleFromWindows(self, hwnd: int) -> float:
        """获取Windows系统的DPI缩放比例

        Args:
            hwnd: None

        Returns:
            DPI缩放比例，例如 1.0, 1.25, 1.5, 2.0 等

        Notes:
            1. 该函数查询系统当前的显示缩放设置
            2. 在高DPI显示器上，此值通常大于 1.0
            3. 获取的缩放比例对于正确计算屏幕坐标和尺寸至关重要
            4. 避免在高DPI屏幕上出现界面模糊或定位不准的问题
        """
        func = OLAPlugDLLHelper.get_function("GetScaleFromWindows")
        return func(self.OLAObject, hwnd)

    def GetWindowDpiAwarenessScale(self, hwnd: int) -> float:
        """获取指定窗口的DPI感知缩放比例

        Args:
            hwnd: 窗口句柄

        Returns:
            窗口的DPI缩放比例

        Notes:
            1. 与 GetScaleFromWindows 不同，此函数获取的是特定窗口的感知缩放
            2. 不同窗口可能具有不同的DPI感知模式（如未感知、系统感知、每监视器感知）
            3. 返回的比例更精确地反映了该窗口在当前显示环境下的实际缩放
            4. 对于需要高精度坐标的自动化操作，应使用此函数获取的比例
        """
        func = OLAPlugDLLHelper.get_function("GetWindowDpiAwarenessScale")
        return func(self.OLAObject, hwnd)

    def EnumProcess(self, name: str) -> str:
        """枚举系统中所有正在运行的进程

        Args:
            name: 进程名

        Returns:
            

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
            2. 进程ID列表中的进程按启动时间排序，越早启动的进程排在越前面
            3. 某些系统进程可能无法被枚举，这取决于当前用户的权限
            4. 建议在使用此函数前，先使用 GetProcessInfo 函数获取进程的详细信息
            5. 如果需要查找特定窗口的进程，可以使用 GetWindowProcessId 函数
        """
        func = OLAPlugDLLHelper.get_function("EnumProcess")
        return self.PtrToStringUTF8(func(self.OLAObject, name))

    def EnumWindow(self, parent: int, title: str, className: str, _filter: int) -> str:
        """枚举指定父窗口下的所有子窗口

        Args:
            parent: 父窗口句柄，获取的窗口必须是该窗口的子窗口。当为0时获取桌面的子窗口
            title: 窗口标题，支持模糊匹配。如果为空字符串，则不匹配标题
            className: 窗口类名，支持模糊匹配。如果为空字符串，则不匹配类名
            _filter: 过滤条件，可以组合使用（值相加），可选值:
                1: 匹配窗口标题（参数title有效）
                2: 匹配窗口类名（参数class_name有效）
                4: 只匹配第一个进程的窗口
                8: 匹配顶级窗口（所有者窗口为0）
                16: 匹配可见窗口

        Returns:
            所有匹配的窗口句柄字符串，格式为"hwnd1,hwnd2,hwnd3"，如果没有找到匹配的窗口，返回空字符串

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
            2. 过滤条件可以组合使用，例如：1+8+16 表示匹配标题、顶级窗口和可见窗口
            3. 某些窗口可能无法被枚举，这取决于当前用户的权限和窗口的状态
            4. 建议在使用此函数前，先使用 GetWindowTitle 和 GetWindowClass 函数获取窗口信息
            5. 如果需要查找特定进程的窗口，可以使用 EnumWindowByProcess 函数
        """
        func = OLAPlugDLLHelper.get_function("EnumWindow")
        return self.PtrToStringUTF8(func(self.OLAObject, parent, title, className, _filter))

    def EnumWindowByProcess(self, process_name: str, title: str, class_name: str, _filter: int) -> str:
        """根据进程名称枚举其创建的所有窗口

        Args:
            process_name: 进程映像名，如"svchost.exe"。此参数精确匹配但不区分大小写
            title: 窗口标题，支持模糊匹配。如果为空字符串，则不匹配标题
            class_name: None
            _filter: 过滤条件，可以组合使用（值相加），可选值:
                1: 匹配窗口标题（参数title有效）
                2: 匹配窗口类名（参数class_name有效）
                4: 只匹配第一个进程的窗口
                8: 匹配顶级窗口（所有者窗口为0）
                16: 匹配可见窗口

        Returns:
            返回所有匹配的窗口句柄字符串，格式为"hwnd1,hwnd2,hwnd3"

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("EnumWindowByProcess")
        return self.PtrToStringUTF8(func(self.OLAObject, process_name, title, class_name, _filter))

    def EnumWindowByProcessId(self, pid: int, title: str, class_name: str, _filter: int) -> str:
        """根据进程ID枚举其创建的所有窗口

        Args:
            pid: 进程ID。可以通过 GetWindowProcessId 函数获取
            title: 窗口标题，支持模糊匹配。如果为空字符串，则不匹配标题
            class_name: None
            _filter: 过滤条件，可以组合使用（值相加），可选值:
                1: 匹配窗口标题（参数title有效）
                2: 匹配窗口类名（参数class_name有效）
                4: 只匹配第一个进程的窗口
                8: 匹配顶级窗口（所有者窗口为0）
                16: 匹配可见窗口

        Returns:
            返回所有匹配的窗口句柄字符串，格式为"hwnd1,hwnd2,hwnd3"

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
            2. 过滤条件可以组合使用，例如：1+8+16 表示匹配标题、顶级窗口和可见窗口
            3. 如果指定了进程ID为0，将枚举所有进程的窗口
            4. 建议在使用此函数前，先使用 GetWindowProcessId 函数获取正确的进程ID
            5. 如果需要查找特定进程的所有窗口，可以使用 EnumWindowByProcess 函数
        """
        func = OLAPlugDLLHelper.get_function("EnumWindowByProcessId")
        return self.PtrToStringUTF8(func(self.OLAObject, pid, title, class_name, _filter))

    def EnumWindowSuper(self, spec1: str, flag1: int, type1: int, spec2: str, flag2: int, type2: int, sort: int) -> str:
        """高级窗口查找，支持多种条件和模糊匹配

        Args:
            spec1: 查找串1，内容取决于flag1的值
            flag1: 查找串1的类型，可选值，可选值:
                0: 标题
                1: 程序名字（如notepad）
                2: 类名
                3: 程序路径（不含盘符，如\windows\system32）
                4: 父句柄（十进制字符串）
                5: 父窗口标题
                6: 父窗口类名
                7: 顶级窗口句柄（十进制字符串）
                8: 顶级窗口标题
                9: 顶级窗口类名
            type1: 查找串1的匹配方式，可选值:
                0: 精确匹配
                1: 模糊匹配
            spec2: 查找串2，内容取决于flag2的值
            flag2: 查找串2的类型，可选值，可选值:
                0: 标题
                1: 程序名字（如notepad）
                2: 类名
                3: 程序路径（不含盘符，如\windows\system32）
                4: 父句柄（十进制字符串）
                5: 父窗口标题
                6: 父窗口类名
                7: 顶级窗口句柄（十进制字符串）
                8: 顶级窗口标题
                9: 顶级窗口类名
            type2: 查找串2的匹配方式，可选值:
                0: 精确匹配
                1: 模糊匹配
            sort: 排序方式，可选值:
                0: 不排序
                1: 按窗口打开顺序排序

        Returns:
            返回所有匹配的窗口句柄字符串,格式"hwnd1,hwnd2,hwnd3"

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("EnumWindowSuper")
        return self.PtrToStringUTF8(func(self.OLAObject, spec1, flag1, type1, spec2, flag2, type2, sort))

    def GetPointWindow(self, x: int, y: int) -> int:
        """获取指定屏幕坐标点下的窗口句柄

        Args:
            x: 屏幕坐标x
            y: 屏幕坐标y

        Returns:
            该坐标点下最顶层窗口的句柄，如果失败则返回 0

        Notes:
            1. 该函数返回覆盖指定屏幕坐标的窗口
            2. 与 GetMousePointWindow 类似，但可以指定任意坐标点
            3. 常用于基于坐标的UI自动化或信息查询
            4. 如果坐标点位于多个窗口重叠区域，返回最顶层的窗口
        """
        func = OLAPlugDLLHelper.get_function("GetPointWindow")
        return func(self.OLAObject, x, y)

    def GetProcessInfo(self, pid: int) -> str:
        """获取指定进程的详细信息

        Args:
            pid: 进程ID

        Returns:
            返回格式为"进程名|进程路径|CPU占用率|内存占用量"，CPU占用率以百分比表示，内存占用量以字节为单位

        Notes:
            1. DLL调用返回字符串指针地址，需要调用 FreeStringPtr 接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("GetProcessInfo")
        return self.PtrToStringUTF8(func(self.OLAObject, pid))

    def ShowTaskBarIcon(self, hwnd: int, show: int) -> int:
        """显示或隐藏系统任务栏上的程序图标

        Args:
            hwnd: 窗口句柄
            show: 是否显示任务栏图标，可选值:
                0: 隐藏图标
                1: 显示图标

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("ShowTaskBarIcon")
        return func(self.OLAObject, hwnd, show)

    def FindWindowByProcessId(self, process_id: int, className: str, title: str) -> int:
        """根据进程ID查找其创建的窗口

        Args:
            process_id: 进程ID
            className: 窗口类名，支持模糊匹配。如果为空字符串("")，则匹配所有类名
            title: 窗口标题，支持模糊匹配。如果为空字符串("")，则匹配所有标题

        Returns:
            找到的窗口句柄，未找到则返回 0

        Notes:
            1. 进程ID必须是当前运行的有效进程ID
            2. 类名和标题支持模糊匹配，可以只包含部分文本
            3. 空字符串参数会匹配任意值，可用于通配搜索
            4. 如果有多个匹配的窗口，函数返回第一个找到的窗口
            5. 建议先验证进程ID是否有效再进行查找
            6. 某些系统进程的窗口可能因权限问题无法被找到
            7. 进程必须具有可见的窗口才能被找到
            8. 可以结合 GetWindowState 和 SetWindowState 进行窗口操作
        """
        func = OLAPlugDLLHelper.get_function("FindWindowByProcessId")
        return func(self.OLAObject, process_id, className, title)

    def GetWindowThreadId(self, hwnd: int) -> int:
        """获取指定窗口所属线程的ID

        Args:
            hwnd: 窗口句柄

        Returns:
            线程ID，如果失败则返回 0

        Notes:
            1. 每个窗口由一个特定的线程创建和管理
            2. 线程ID可用于线程级别的操作或调试
            3. 了解窗口的创建线程有助于分析程序结构和消息循环
            4. 某些系统窗口的线程ID可能无法获取
        """
        func = OLAPlugDLLHelper.get_function("GetWindowThreadId")
        return func(self.OLAObject, hwnd)

    def FindWindowSuper(self, spec1: str, flag1: int, type1: int, spec2: str, flag2: int, type2: int) -> int:
        """高级窗口查找，功能与 EnumWindowSuper 类似

        Args:
            spec1: 查找串1，内容取决于flag1的值
            flag1: 查找串1的类型，可选值，可选值:
                0: 标题
                1: 程序名字（如notepad）
                2: 类名
                3: 程序路径（不含盘符，如\windows\system32）
                4: 父句柄（十进制字符串）
                5: 父窗口标题
                6: 父窗口类名
                7: 顶级窗口句柄（十进制字符串）
                8: 顶级窗口标题
                9: 顶级窗口类名
            type1: 查找串1的匹配方式，可选值:
                0: 精确匹配
                1: 模糊匹配
            spec2: 查找串2，内容取决于flag2的值
            flag2: 查找串2的类型，可选值，可选值:
                0: 标题
                1: 程序名字（如notepad）
                2: 类名
                3: 程序路径（不含盘符，如\windows\system32）
                4: 父句柄（十进制字符串）
                5: 父窗口标题
                6: 父窗口类名
                7: 顶级窗口句柄（十进制字符串）
                8: 顶级窗口标题
                9: 顶级窗口类名
            type2: 查找串2的匹配方式

        Returns:
            找到的窗口句柄，未找到则返回 0

        Notes:
            1. 两个条件必须同时满足才会返回窗口句柄
            2. 模糊匹配时，只要窗口属性包含指定的字符串即可匹配成功
            3. 程序路径匹配时不区分大小写，且不需要包含盘符
            4. 建议在使用此函数前，先使用 GetWindowTitle、GetWindowClass 等函数获取窗口信息
            5. 如果需要查找多个符合条件的窗口，可以使用 EnumWindowSuper 函数
        """
        func = OLAPlugDLLHelper.get_function("FindWindowSuper")
        return func(self.OLAObject, spec1, flag1, type1, spec2, flag2, type2)

    def ClientToScreen(self, hwnd: int, x: int, y: int) -> int:
        """将客户区坐标转换为屏幕绝对坐标

        Args:
            hwnd: 窗口句柄
            x: 指向客户区x坐标的变量，转换后存储屏幕x坐标
            y: 指向客户区y坐标的变量，转换后存储屏幕y坐标

        Returns:
            返回元组: (操作结果, 指向客户区x坐标的变量，转换后存储屏幕x坐标, 指向客户区y坐标的变量，转换后存储屏幕y坐标)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. 该函数用于坐标系转换，将相对于窗口客户区的坐标转为全局屏幕坐标
            2. 常用于将鼠标点击位置或控件位置映射到屏幕
            3. 转换考虑了窗口的位置、DPI缩放和多显示器布局
            4. 是实现精确UI自动化的基础
        """
        func = OLAPlugDLLHelper.get_function("ClientToScreen")
        return func(self.OLAObject, hwnd, x, y)

    def ScreenToClient(self, hwnd: int, x: int, y: int) -> int:
        """将屏幕绝对坐标转换为客户区坐标

        Args:
            hwnd: 窗口句柄
            x: 指向屏幕x坐标的变量，转换后存储客户区x坐标
            y: 指向屏幕y坐标的变量，转换后存储客户区y坐标

        Returns:
            返回元组: (操作结果, 指向屏幕x坐标的变量，转换后存储客户区x坐标, 指向屏幕y坐标的变量，转换后存储客户区y坐标)
            操作结果:
                0: 失败
                1: 成功

        Notes:
            1. 与 ClientToScreen 相反，将全局屏幕坐标转为相对于指定窗口客户区的坐标
            2. 常用于判断屏幕上的某个点是否在窗口客户区内
            3. 转换同样考虑了窗口位置、DPI和显示器设置
            4. 对于坐标计算和事件处理非常有用
        """
        func = OLAPlugDLLHelper.get_function("ScreenToClient")
        return func(self.OLAObject, hwnd, x, y)

    def GetForegroundFocus(self) -> int:
        """获取当前前台窗口中具有输入焦点的控件句柄

        Returns:
            具有焦点的控件句柄，如果失败则返回 0

        Notes:
            1. 该函数返回当前活动窗口中正在接收键盘输入的子窗口（如编辑框）
            2. 对于实现自动化输入操作（如 SendPaste）非常关键
            3. 只有可接收输入的控件（如文本框）才会获得焦点
            4. 如果前台窗口没有焦点控件或为桌面，返回值可能为 0
        """
        func = OLAPlugDLLHelper.get_function("GetForegroundFocus")
        return func(self.OLAObject)

    def SetWindowDisplay(self, hwnd: int, affinity: int) -> int:
        """设置窗口的显示状态（可见性）

        Args:
            hwnd: 窗口句柄
            affinity: 1-显示窗口, 0-隐藏窗口

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数直接控制窗口的可见性，类似于 SetWindowState(SW_SHOW/SW_HIDE)
            2. 隐藏窗口后，它将从屏幕上消失，但仍在进程中运行
            3. 显示隐藏的窗口可以使其重新出现
            4. 操作不会改变窗口的最小化或最大化状态
        """
        func = OLAPlugDLLHelper.get_function("SetWindowDisplay")
        return func(self.OLAObject, hwnd, affinity)

    def IsDisplayDead(self, x1: int, y1: int, x2: int, y2: int, time: int) -> int:
        """检查指定窗口是否处于“假死”状态

        Args:
            x1: 查找区域的左上角X坐标
            y1: 查找区域的左上角Y坐标
            x2: 查找区域的右下角X坐标
            y2: 查找区域的右下角Y坐标
            time: 识别间隔，单位毫秒

        Returns:
            状态
                0: 正常
                1: 卡屏

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("IsDisplayDead")
        return func(self.OLAObject, x1, y1, x2, y2, time)

    def GetWindowsFps(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """获取指定窗口的刷新帧率（FPS）

        Args:
            x1: 查找区域的左上角X坐标
            y1: 查找区域的左上角Y坐标
            x2: 查找区域的右下角X坐标
            y2: 查找区域的右下角Y坐标

        Returns:
            窗口的近似帧率，如 60, 30, 0（静态）等

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetWindowsFps")
        return func(self.OLAObject, x1, y1, x2, y2)

    def TerminateProcess(self, pid: int) -> int:
        """终止进程

        Args:
            pid: 进程ID

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数强制结束指定ID的进程
            2. 终止后，进程及其所有资源将被系统回收
            3. 未保存的数据将会丢失
            4. 需要足够的权限才能终止某些系统或受保护的进程
        """
        func = OLAPlugDLLHelper.get_function("TerminateProcess")
        return func(self.OLAObject, pid)

    def TerminateProcessTree(self, pid: int) -> int:
        """终止进程树

        Args:
            pid: 进程ID

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数不仅终止指定进程，还递归终止其创建的所有子进程
            2. 用于彻底清理一个程序及其后台服务
            3. 操作非常强力，可能导致相关联的多个程序关闭
            4. 需要谨慎使用，避免误杀重要系统进程
        """
        func = OLAPlugDLLHelper.get_function("TerminateProcessTree")
        return func(self.OLAObject, pid)

    def GetCommandLine(self, hwnd: int) -> str:
        """获取窗口命令行

        Args:
            hwnd: 窗口句柄

        Returns:
            命令行(二进制字符串的指针)

        Notes:
            1. 该函数返回创建进程时使用的完整命令行参数
            2. 包含可执行文件路径和所有传递的参数
            3. 返回的字符串指针需要调用 FreeStringPtr 接口释放内存
            4. 对于分析程序启动配置或调试非常有用
        """
        func = OLAPlugDLLHelper.get_function("GetCommandLine")
        return self.PtrToStringUTF8(func(self.OLAObject, hwnd))

    def CheckFontSmooth(self) -> int:
        """检查字体平滑

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 字体平滑可使屏幕上的文字边缘更平滑，提高可读性
            2. 此设置影响所有应用程序的文本渲染
            3. 检查结果可用于调整自动化脚本的截图或OCR策略
            4. 在某些低分辨率或远程桌面场景下，此功能可能被关闭
        """
        func = OLAPlugDLLHelper.get_function("CheckFontSmooth")
        return func(self.OLAObject)

    def SetFontSmooth(self, enable: int) -> int:
        """设置字体平滑

        Args:
            enable: 是否启用

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 该函数修改系统的全局字体渲染设置
            2. 更改后，新创建的窗口将使用新的设置
            3. 可能需要重启应用程序甚至系统才能完全生效
            4. 滥用此功能可能影响用户体验，应谨慎使用
        """
        func = OLAPlugDLLHelper.get_function("SetFontSmooth")
        return func(self.OLAObject, enable)

    def EnableDebugPrivilege(self) -> int:
        """启用调试权限

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
            1. 调试权限（SeDebugPrivilege）允许进程调试或操作其他进程
            2. 此权限对于调用 TerminateProcess, EnumProcess 等函数通常是必需的
            3. 通常需要管理员权限才能成功启用
            4. 在进程启动后尽早调用此函数以确保后续操作的权限
        """
        func = OLAPlugDLLHelper.get_function("EnableDebugPrivilege")
        return func(self.OLAObject)

    def SystemStart(self, applicationName: str, commandLine: str) -> int:
        """系统启动

        Args:
            applicationName: 应用程序名称
            commandLine: 命令行

        Returns:
            成功返回子进程ID,失败返回0

        Notes:
            1. flag 参数指定具体操作，如 0-关机, 1-重启, 2-注销, 3-睡眠等
            2. 执行此操作需要相应的系统权限（通常为管理员）
            3. 操作是不可逆的，执行前应提示用户保存数据
            4. 常用于系统维护脚本或远程管理工具
        """
        func = OLAPlugDLLHelper.get_function("SystemStart")
        return func(self.OLAObject, applicationName, commandLine)

    def CreateChildProcess(self, applicationName: str, commandLine: str, currentDirectory: str, showType: int, parentProcessId: int) -> int:
        """创建子进程

        Args:
            applicationName: 进程路径，如C:\windows\system32\notepad.exe
            commandLine: 命令行参数一定要包含进程路径，如aa bb cc
            currentDirectory: 启动目录, 可空
            showType: 显示方式，如果省略本参数,默认为“普通激活”方式.，可选值:
                1: 隐藏窗口
                2: 普通激活
                3: 最小化激活
                4: 最大化激活
                5: 普通不激活
                6: 最小化不激活
            parentProcessId: 父进程ID, 整数型,支持系统进程的ID，只要是调试权限能Open的进程，如service.exe、csrss.exe、explorer.exe

        Returns:
            成功返回子进程ID,失败返回0

        Notes:
            1. 该函数启动一个新的可执行程序作为当前进程的子进程
            2. cmdLine 包含可执行文件路径和参数
            3. showCmd 控制新进程主窗口的初始显示状态
            4. 成功时，新进程的ID通过 processId 参数返回
        """
        func = OLAPlugDLLHelper.get_function("CreateChildProcess")
        return func(self.OLAObject, applicationName, commandLine, currentDirectory, showType, parentProcessId)

    def GetProcessIconImage(self, pid: int, targetWidth: int, targetHeight: int) -> int:
        """获取进程图标

        Args:
            pid: 进程ID
            targetWidth: 目标宽度
            targetHeight: 目标高度

        Returns:
            进程图标

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("GetProcessIconImage")
        return func(self.OLAObject, pid, targetWidth, targetHeight)

    def XmlCreateDocument(self) -> int:
        """创建空的XML文档

        Returns:
            返回新创建的XML文档句柄，失败时返回0

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlCreateDocument")
        return func()

    def XmlParse(self, _str: str, err: int = None) -> Tuple[int, int]:
        """解析XML字符串

        Args:
            _str: 要解析的XML字符串
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回解析后的XML文档句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlParse")
        return func(_str, err)

    def XmlParseFile(self, filepath: str, err: int = None) -> Tuple[int, int]:
        """从文件加载并解析XML

        Args:
            filepath: XML文件路径
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回解析后的XML文档句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlParseFile")
        return func(filepath, err)

    def XmlToString(self, doc: int, compact: int, err: int = None) -> Tuple[str, int]:
        """将XML文档序列化为字符串

        Args:
            doc: XML文档句柄
            compact: 是否紧凑输出，0表示格式化，1表示紧凑
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回XML字符串，需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlToString")
        return self.PtrToStringUTF8(func(doc, compact, err))

    def XmlSaveToFile(self, doc: int, filepath: str, compact: int, err: int = None) -> Tuple[int, int]:
        """将XML文档保存到文件

        Args:
            doc: XML文档句柄
            filepath: 保存的文件路径
            compact: 是否紧凑输出，0表示格式化，1表示紧凑
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果，1表示成功，0表示失败, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSaveToFile")
        return func(doc, filepath, compact, err)

    def XmlFree(self, doc: int) -> int:
        """释放XML文档

        Args:
            doc: 要释放的XML文档句柄

        Returns:
            操作结果
                0: 失败
                1: 成功

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlFree")
        return func(doc)

    def XmlGetRootElement(self, doc: int, err: int = None) -> Tuple[int, int]:
        """获取XML文档的根元素

        Args:
            doc: XML文档句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回根元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetRootElement")
        return func(doc, err)

    def XmlCreateElement(self, doc: int, name: str, err: int = None) -> Tuple[int, int]:
        """创建新的XML元素

        Args:
            doc: XML文档句柄
            name: 元素名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlCreateElement")
        return func(doc, name, err)

    def XmlInsertRootElement(self, doc: int, element: int, err: int = None) -> Tuple[int, int]:
        """设置文档的根元素

        Args:
            doc: XML文档句柄
            element: 要设置为根元素的元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlInsertRootElement")
        return func(doc, element, err)

    def XmlAppendChild(self, parent: int, child: int, err: int = None) -> Tuple[int, int]:
        """向元素添加子元素

        Args:
            parent: 父元素句柄
            child: 子元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlAppendChild")
        return func(parent, child, err)

    def XmlGetFirstChild(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的第一个子元素

        Args:
            element: 父元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回子元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetFirstChild")
        return func(element, err)

    def XmlGetNextSibling(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的下一个兄弟元素

        Args:
            element: 当前元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回兄弟元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetNextSibling")
        return func(element, err)

    def XmlFindElement(self, parent: int, name: str, err: int = None) -> Tuple[int, int]:
        """根据名称查找子元素

        Args:
            parent: 父元素句柄
            name: 要查找的元素名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回找到的元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlFindElement")
        return func(parent, name, err)

    def XmlGetElementName(self, element: int, err: int = None) -> Tuple[str, int]:
        """获取元素的名称

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回元素名称字符串，需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetElementName")
        return self.PtrToStringUTF8(func(element, err))

    def XmlGetElementText(self, element: int, err: int = None) -> Tuple[str, int]:
        """获取元素的文本内容

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回文本内容字符串，需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetElementText")
        return self.PtrToStringUTF8(func(element, err))

    def XmlSetElementText(self, element: int, text: str, err: int = None) -> Tuple[int, int]:
        """设置元素的文本内容

        Args:
            element: 元素句柄
            text: 要设置的文本内容
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetElementText")
        return func(element, text, err)

    def XmlRemoveChild(self, parent: int, child: int, err: int = None) -> Tuple[int, int]:
        """删除子元素

        Args:
            parent: 父元素句柄
            child: 要删除的子元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlRemoveChild")
        return func(parent, child, err)

    def XmlInsertBefore(self, parent: int, newChild: int, refChild: int, err: int = None) -> Tuple[int, int]:
        """在指定子元素之前插入新元素

        Args:
            parent: 父元素句柄
            newChild: 要插入的新元素句柄
            refChild: 参考子元素句柄，新元素将插入到它之前
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlInsertBefore")
        return func(parent, newChild, refChild, err)

    def XmlInsertAfter(self, parent: int, newChild: int, refChild: int, err: int = None) -> Tuple[int, int]:
        """在指定子元素之后插入新元素

        Args:
            parent: 父元素句柄
            newChild: 要插入的新元素句柄
            refChild: 参考子元素句柄，新元素将插入到它之后
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlInsertAfter")
        return func(parent, newChild, refChild, err)

    def XmlGetParent(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的父元素

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回父元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetParent")
        return func(element, err)

    def XmlGetPreviousSibling(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的前一个兄弟元素

        Args:
            element: 当前元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回前一个兄弟元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetPreviousSibling")
        return func(element, err)

    def XmlGetLastChild(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的最后一个子元素

        Args:
            element: 父元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回最后一个子元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetLastChild")
        return func(element, err)

    def XmlCloneElement(self, doc: int, element: int, err: int = None) -> Tuple[int, int]:
        """深度克隆元素（包括所有子元素和属性）

        Args:
            doc: XML文档句柄
            element: 要克隆的元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回克隆的元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlCloneElement")
        return func(doc, element, err)

    def XmlHasChildren(self, element: int, err: int = None) -> Tuple[int, int]:
        """检查元素是否有子元素

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回1表示有子元素，0表示没有, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlHasChildren")
        return func(element, err)

    def XmlGetAttribute(self, element: int, name: str, err: int = None) -> Tuple[str, int]:
        """获取元素的属性值

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回属性值字符串，需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttribute")
        return self.PtrToStringUTF8(func(element, name, err))

    def XmlSetAttribute(self, element: int, name: str, value: str, err: int = None) -> Tuple[int, int]:
        """设置元素的属性

        Args:
            element: 元素句柄
            name: 属性名称
            value: 属性值
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetAttribute")
        return func(element, name, value, err)

    def XmlGetAttributeInt(self, element: int, name: str, err: int = None) -> Tuple[int, int]:
        """获取元素的整数类型属性值

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回整数值，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttributeInt")
        return func(element, name, err)

    def XmlSetAttributeInt(self, element: int, name: str, value: int, err: int = None) -> Tuple[int, int]:
        """设置元素的整数类型属性

        Args:
            element: 元素句柄
            name: 属性名称
            value: 整数值
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetAttributeInt")
        return func(element, name, value, err)

    def XmlGetAttributeDouble(self, element: int, name: str, err: int = None) -> Tuple[float, int]:
        """获取元素的浮点数类型属性值

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回浮点数值，失败时返回0.0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttributeDouble")
        return func(element, name, err)

    def XmlSetAttributeDouble(self, element: int, name: str, value: float, err: int = None) -> Tuple[int, int]:
        """设置元素的浮点数类型属性

        Args:
            element: 元素句柄
            name: 属性名称
            value: 浮点数值
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetAttributeDouble")
        return func(element, name, value, err)

    def XmlGetAttributeBool(self, element: int, name: str, err: int = None) -> Tuple[int, int]:
        """获取元素的布尔类型属性值

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回布尔值，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttributeBool")
        return func(element, name, err)

    def XmlSetAttributeBool(self, element: int, name: str, value: int, err: int = None) -> Tuple[int, int]:
        """设置元素的布尔类型属性

        Args:
            element: 元素句柄
            name: 属性名称
            value: 布尔值（0表示false，非0表示true）
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetAttributeBool")
        return func(element, name, value, err)

    def XmlGetAttributeInt64(self, element: int, name: str, err: int = None) -> Tuple[int, int]:
        """获取元素的64位整数类型属性值

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回64位整数值，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttributeInt64")
        return func(element, name, err)

    def XmlSetAttributeInt64(self, element: int, name: str, value: int, err: int = None) -> Tuple[int, int]:
        """设置元素的64位整数类型属性

        Args:
            element: 元素句柄
            name: 属性名称
            value: 64位整数值
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetAttributeInt64")
        return func(element, name, value, err)

    def XmlHasAttribute(self, element: int, name: str, err: int = None) -> Tuple[int, int]:
        """检查元素是否有指定属性

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回1表示存在，0表示不存在, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlHasAttribute")
        return func(element, name, err)

    def XmlDeleteAttribute(self, element: int, name: str, err: int = None) -> Tuple[int, int]:
        """删除元素的属性

        Args:
            element: 元素句柄
            name: 属性名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlDeleteAttribute")
        return func(element, name, err)

    def XmlGetAttributeNames(self, element: int, err: int = None) -> Tuple[str, int]:
        """获取元素的所有属性名称

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回属性名称数组（以|分隔），需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttributeNames")
        return self.PtrToStringUTF8(func(element, err))

    def XmlGetAttributeCount(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的属性数量

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回属性数量，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetAttributeCount")
        return func(element, err)

    def XmlSetCDATA(self, doc: int, element: int, content: str, err: int = None) -> Tuple[int, int]:
        """创建CDATA节点并添加到元素

        Args:
            doc: XML文档句柄
            element: 元素句柄
            content: CDATA内容
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetCDATA")
        return func(doc, element, content, err)

    def XmlAddComment(self, doc: int, element: int, comment: str, err: int = None) -> Tuple[int, int]:
        """创建注释节点并添加到元素

        Args:
            doc: XML文档句柄
            element: 元素句柄
            comment: 注释内容
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlAddComment")
        return func(doc, element, comment, err)

    def XmlSetDeclaration(self, doc: int, version: str, encoding: str, standalone: int, err: int = None) -> Tuple[int, int]:
        """创建XML声明

        Args:
            doc: XML文档句柄
            version: XML版本（如"1.0"）
            encoding: 编码（如"UTF-8"）
            standalone: 是否独立（0或1）
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlSetDeclaration")
        return func(doc, version, encoding, standalone, err)

    def XmlQueryElement(self, doc: int, path: str, err: int = None) -> Tuple[int, int]:
        """使用路径查询元素

        Args:
            doc: XML文档句柄
            path: 查询路径（如 "root/child/item"）
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回找到的元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlQueryElement")
        return func(doc, path, err)

    def XmlGetChildCount(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的子元素数量

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回子元素数量，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetChildCount")
        return func(element, err)

    def XmlGetChildCountByName(self, parent: int, name: str, err: int = None) -> Tuple[int, int]:
        """根据名称获取所有匹配的子元素数量

        Args:
            parent: 父元素句柄
            name: 元素名称
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回匹配的子元素数量，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetChildCountByName")
        return func(parent, name, err)

    def XmlGetChildByIndex(self, parent: int, index: int, err: int = None) -> Tuple[int, int]:
        """根据索引获取子元素

        Args:
            parent: 父元素句柄
            index: 子元素索引（从0开始）
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回子元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetChildByIndex")
        return func(parent, index, err)

    def XmlGetChildByNameAndIndex(self, parent: int, name: str, index: int, err: int = None) -> Tuple[int, int]:
        """根据名称和索引获取子元素

        Args:
            parent: 父元素句柄
            name: 元素名称
            index: 在同名元素中的索引（从0开始）
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回子元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetChildByNameAndIndex")
        return func(parent, name, index, err)

    def XmlFindElementByAttribute(self, parent: int, elementName: str, attrName: str, attrValue: str, err: int = None) -> Tuple[int, int]:
        """查找具有指定属性值的子元素

        Args:
            parent: 父元素句柄
            elementName: 元素名称（可为NULL表示任意元素）
            attrName: 属性名称
            attrValue: 属性值
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回找到的元素句柄，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlFindElementByAttribute")
        return func(parent, elementName, attrName, attrValue, err)

    def XmlGetElementDepth(self, element: int, err: int = None) -> Tuple[int, int]:
        """获取元素的深度（从根元素开始计数）

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回元素深度，根元素为0，失败时返回-1, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetElementDepth")
        return func(element, err)

    def XmlGetElementPath(self, element: int, err: int = None) -> Tuple[str, int]:
        """获取元素的完整路径

        Args:
            element: 元素句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回路径字符串（如"/root/child/item"），需调用FreeStringPtr释放，失败时返回0, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetElementPath")
        return self.PtrToStringUTF8(func(element, err))

    def XmlCompareElements(self, element1: int, element2: int, deep: int, err: int = None) -> Tuple[int, int]:
        """比较两个元素是否相同（比较名称、属性和文本内容）

        Args:
            element1: 第一个元素句柄
            element2: 第二个元素句柄
            deep: 是否深度比较（包括所有子元素）
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回1表示相同，0表示不同, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlCompareElements")
        return func(element1, element2, deep, err)

    def XmlMergeDocuments(self, targetDoc: int, sourceDoc: int, err: int = None) -> Tuple[int, int]:
        """合并两个XML文档

        Args:
            targetDoc: 目标文档句柄
            sourceDoc: 源文档句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回操作结果错误码, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlMergeDocuments")
        return func(targetDoc, sourceDoc, err)

    def XmlValidate(self, doc: int, err: int = None) -> Tuple[int, int]:
        """验证XML文档格式是否正确

        Args:
            doc: XML文档句柄
            err: 错误码输出参数，可为0，可选值:
                0: 操作成功
                1: 无效的句柄
                2: XML解析失败
                3: 类型不匹配
                4: 元素不存在
                5: 属性不存在
                6: 未知错误

        Returns:
            返回元组: (返回1表示有效，0表示无效, 错误码输出参数，可为0)

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlValidate")
        return func(doc, err)

    def XmlGetObjectCount(self) -> int:
        """获取当前管理的XML对象数量（调试用）

        Returns:
            返回当前管理的XML对象数量

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlGetObjectCount")
        return func()

    def XmlCleanupAll(self) -> int:
        """清理所有XML对象（调试用）

        Returns:
            None

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("XmlCleanupAll")
        return func()

    def YoloLoadModel(self, modelPath: str, outputPath: str, names_label: str, password: str, modelType: int, inferenceType: int, inferenceDevice: int) -> int:
        """加载模型

        Args:
            modelPath: 模型路径
            outputPath: None
            names_label: None
            password: 密码（可选，传NULL表示无密码）
            modelType: 模型类型0.TensorRT 1.ONNX(保留未开放) 2.pt(保留未开放)
            inferenceType: 推理类型0.Detect物体检测 1.Classify图像分类 2.Segment实例分割 3.Pose姿态估计 4.Obb旋转框检测5.KeyPoint关键点检测 6.Text文字识别 7.OCR文字识别 8.车牌识别 9.人脸识别 10.手势识别11.动作识别 12.行为识别 13.运动识别 14.轨迹识别 15.轨迹预测 16.轨迹跟踪note: 5-16未开放服务
            inferenceDevice: 推理设备0.GPU0 1.GPU1 2.GPU2 3.GPU3 以此类推，默认使用GPU0若无GPU设备，则无法使用，CPU版本后续推出

        Returns:
            模型句柄（失败返回0）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("YoloLoadModel")
        return func(self.OLAObject, modelPath, outputPath, names_label, password, modelType, inferenceType, inferenceDevice)

    def YoloReleaseModel(self, modelHandle: int) -> int:
        """释放模型

        Args:
            modelHandle: 模型句柄

        Returns:
            释放结果

        Notes:
            1. 0 失败, 1 成功
        """
        func = OLAPlugDLLHelper.get_function("YoloReleaseModel")
        return func(self.OLAObject, modelHandle)

    def YoloLoadModelMemory(self, memoryAddr: int, size: int, modelType: int, inferenceType: int, inferenceDevice: int) -> int:
        """从内存加载模型

        Args:
            memoryAddr: 内存地址
            size: 内存大小
            modelType: 模型类型0.TensorRT 1.ONNX(保留未开放) 2.pt(保留未开放)
            inferenceType: 推理类型0.Detect物体检测 1.Classify图像分类 2.Segment实例分割 3.Pose姿态估计 4.Obb旋转框检测5.KeyPoint关键点检测 6.Text文字识别 7.OCR文字识别 8.车牌识别 9.人脸识别 10.手势识别11.动作识别 12.行为识别 13.运动识别 14.轨迹识别 15.轨迹预测 16.轨迹跟踪note: 5-16未开放服务
            inferenceDevice: 推理设备0.GPU0 1.GPU1 2.GPU2 3.GPU3 以此类推，默认使用GPU0若无GPU设备，则无法使用，CPU版本后续推出

        Returns:
            模型句柄（失败返回0）

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("YoloLoadModelMemory")
        return func(self.OLAObject, memoryAddr, size, modelType, inferenceType, inferenceDevice)

    def YoloInfer(self, handle: int, imagePtr: int) -> str:
        """推理

        Args:
            handle: 模型句柄
            imagePtr: 图像指针

        Returns:
            JSON格式推理结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloInfer")
        return self.PtrToStringUTF8(func(self.OLAObject, handle, imagePtr))

    def YoloIsModelValid(self, modelHandle: int) -> int:
        """检查模型是否有效

        Args:
            modelHandle: 模型句柄

        Returns:
            1 有效, 0 无效

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("YoloIsModelValid")
        return func(self.OLAObject, modelHandle)

    def YoloListModels(self) -> str:
        """列出所有已加载的模型

        Returns:
            JSON格式的模型列表

        Notes:
            1. 返回格式: [{"handle": 123, "type": 5, "inferenceType": 0, "device": 1}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloListModels")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def YoloGetModelInfo(self, modelHandle: int) -> str:
        """获取模型信息

        Args:
            modelHandle: 模型句柄

        Returns:
            JSON格式的模型信息

        Notes:
            1. 返回格式: {"handle": 123, "type": 5, "inferenceType": 0, "device": 1, "inputShape": [640,640], "classes": [...]}
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloGetModelInfo")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle))

    def YoloSetModelConfig(self, modelHandle: int, configJson: str) -> int:
        """设置模型配置参数

        Args:
            modelHandle: 模型句柄
            configJson: 配置JSON

        Returns:
            1 成功, 0 失败

        Notes:
            1. 配置格式: {"confidence": 0.5, "iou": 0.45, "maxDetections": 100, "classes": ["person","car"], "inputSize": [640, 640]}
        """
        func = OLAPlugDLLHelper.get_function("YoloSetModelConfig")
        return func(self.OLAObject, modelHandle, configJson)

    def YoloGetModelConfig(self, modelHandle: int) -> str:
        """获取模型配置参数

        Args:
            modelHandle: 模型句柄

        Returns:
            JSON格式的配置信息

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloGetModelConfig")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle))

    def YoloWarmup(self, modelHandle: int, iterations: int) -> int:
        """模型预热

        Args:
            modelHandle: 模型句柄
            iterations: 预热迭代次数

        Returns:
            1 成功, 0 失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("YoloWarmup")
        return func(self.OLAObject, modelHandle, iterations)

    def YoloDetect(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int, classes: str, confidence: float, iou: float, maxDetections: int) -> str:
        """物体检测（完整参数）

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            classes: 检测类别JSON数组，如：["person", "car", "bus"]，传NULL表示检测所有类别
            confidence: 置信度阈值 (0.0-1.0)
            iou: NMS交并比阈值 (0.0-1.0)
            maxDetections: 最大检测数量

        Returns:
            JSON格式检测结果

        Notes:
            1. 返回格式: [{"class": "person", "confidence": 0.95, "bbox": [x1, y1, x2, y2]}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloDetect")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2, classes, confidence, iou, maxDetections))

    def YoloDetectSimple(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int) -> str:
        """物体检测（简化版，使用默认参数）

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标

        Returns:
            JSON格式检测结果

        Notes:
            1. 使用默认参数：confidence=0.5, iou=0.45, maxDetections=100, classes=all
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloDetectSimple")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2))

    def YoloDetectFromPtr(self, modelHandle: int, imagePtr: int, classes: str, confidence: float, iou: float, maxDetections: int) -> str:
        """从图像指针检测物体

        Args:
            modelHandle: 模型句柄
            imagePtr: 图像指针（OpenCV Mat指针）
            classes: 检测类别JSON数组，传NULL表示检测所有类别
            confidence: 置信度阈值
            iou: NMS交并比阈值
            maxDetections: 最大检测数量

        Returns:
            JSON格式检测结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloDetectFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePtr, classes, confidence, iou, maxDetections))

    def YoloDetectFromFile(self, modelHandle: int, imagePath: str, classes: str, confidence: float, iou: float, maxDetections: int) -> str:
        """从文件路径检测物体

        Args:
            modelHandle: 模型句柄
            imagePath: 图像文件路径
            classes: 检测类别JSON数组，传NULL表示检测所有类别
            confidence: 置信度阈值
            iou: NMS交并比阈值
            maxDetections: 最大检测数量

        Returns:
            JSON格式检测结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloDetectFromFile")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePath, classes, confidence, iou, maxDetections))

    def YoloDetectFromBase64(self, modelHandle: int, base64Data: str, classes: str, confidence: float, iou: float, maxDetections: int) -> str:
        """从Base64编码检测物体

        Args:
            modelHandle: 模型句柄
            base64Data: Base64编码的图像数据
            classes: 检测类别JSON数组，传NULL表示检测所有类别
            confidence: 置信度阈值
            iou: NMS交并比阈值
            maxDetections: 最大检测数量

        Returns:
            JSON格式检测结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloDetectFromBase64")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, base64Data, classes, confidence, iou, maxDetections))

    def YoloDetectBatch(self, modelHandle: int, imagesJson: str, classes: str, confidence: float, iou: float, maxDetections: int) -> str:
        """批量检测物体

        Args:
            modelHandle: 模型句柄
            imagesJson: 图像列表JSON
            classes: 检测类别JSON数组，传NULL表示检测所有类别
            confidence: 置信度阈值
            iou: NMS交并比阈值
            maxDetections: 最大检测数量

        Returns:
            JSON格式批量检测结果

        Notes:
            1. 格式: [{"type": "file", "path": "a.jpg"}, {"type": "base64", "data": "..."}, {"type":"region", "x1": 0, "y1": 0, "x2": 100, "y2": 100}]
            2. 返回格式: [{"index": 0, "results": [...]}, {"index": 1, "results": [...]}, ...]
            3. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloDetectBatch")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagesJson, classes, confidence, iou, maxDetections))

    def YoloClassify(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int, topK: int) -> str:
        """图像分类

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            topK: 返回前K个结果

        Returns:
            JSON格式分类结果

        Notes:
            1. 返回格式: [{"class": "cat", "confidence": 0.95}, {"class": "dog", "confidence": 0.03}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloClassify")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2, topK))

    def YoloClassifyFromPtr(self, modelHandle: int, imagePtr: int, topK: int) -> str:
        """从图像指针分类

        Args:
            modelHandle: 模型句柄
            imagePtr: 图像指针（OpenCV Mat指针）
            topK: 返回前K个结果

        Returns:
            JSON格式分类结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloClassifyFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePtr, topK))

    def YoloClassifyFromFile(self, modelHandle: int, imagePath: str, topK: int) -> str:
        """从文件路径分类

        Args:
            modelHandle: 模型句柄
            imagePath: 图像文件路径
            topK: 返回前K个结果

        Returns:
            JSON格式分类结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloClassifyFromFile")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePath, topK))

    def YoloSegment(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int, confidence: float, iou: float) -> str:
        """实例分割

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式分割结果

        Notes:
            1. 返回格式: [{"class": "person", "confidence": 0.95, "bbox": [x1, y1, x2, y2], "mask": [[x,y], ...]}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloSegment")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2, confidence, iou))

    def YoloSegmentFromPtr(self, modelHandle: int, imagePtr: int, confidence: float, iou: float) -> str:
        """从图像指针分割

        Args:
            modelHandle: 模型句柄
            imagePtr: 图像指针（OpenCV Mat指针）
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式分割结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloSegmentFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePtr, confidence, iou))

    def YoloPose(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int, confidence: float, iou: float) -> str:
        """姿态估计

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式姿态估计结果

        Notes:
            1. 返回格式: [{"bbox": [x1, y1, x2, y2], "keypoints": [[x, y, conf], ...], "confidence":0.95}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloPose")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2, confidence, iou))

    def YoloPoseFromPtr(self, modelHandle: int, imagePtr: int, confidence: float, iou: float) -> str:
        """从图像指针估计姿态

        Args:
            modelHandle: 模型句柄
            imagePtr: 图像指针（OpenCV Mat指针）
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式姿态估计结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloPoseFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePtr, confidence, iou))

    def YoloObb(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int, confidence: float, iou: float) -> str:
        """旋转框检测

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式旋转框检测结果

        Notes:
            1. 返回格式: [{"class": "ship", "confidence": 0.95, "obb": [cx, cy, w, h, angle]}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloObb")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2, confidence, iou))

    def YoloObbFromPtr(self, modelHandle: int, imagePtr: int, confidence: float, iou: float) -> str:
        """从图像指针检测旋转框

        Args:
            modelHandle: 模型句柄
            imagePtr: 图像指针（OpenCV Mat指针）
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式旋转框检测结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloObbFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePtr, confidence, iou))

    def YoloKeyPoint(self, modelHandle: int, x1: int, y1: int, x2: int, y2: int, confidence: float, iou: float) -> str:
        """关键点检测

        Args:
            modelHandle: 模型句柄
            x1: 左上角x坐标
            y1: 左上角y坐标
            x2: 右下角x坐标
            y2: 右下角y坐标
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式关键点检测结果

        Notes:
            1. 返回格式: [{"bbox": [x1, y1, x2, y2], "keypoints": [[x, y, conf], ...], "confidence":0.95}, ...]
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloKeyPoint")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, x1, y1, x2, y2, confidence, iou))

    def YoloKeyPointFromPtr(self, modelHandle: int, imagePtr: int, confidence: float, iou: float) -> str:
        """从图像指针检测关键点

        Args:
            modelHandle: 模型句柄
            imagePtr: 图像指针（OpenCV Mat指针）
            confidence: 置信度阈值
            iou: NMS交并比阈值

        Returns:
            JSON格式关键点检测结果

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloKeyPointFromPtr")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle, imagePtr, confidence, iou))

    def YoloGetInferenceStats(self, modelHandle: int) -> str:
        """获取推理统计信息

        Args:
            modelHandle: 模型句柄

        Returns:
            JSON格式统计信息

        Notes:
            1. 返回格式: {"totalInferences": 100, "avgTime": 25.5, "minTime": 20.1, "maxTime": 35.2,"fps": 39.2}
            2. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloGetInferenceStats")
        return self.PtrToStringUTF8(func(self.OLAObject, modelHandle))

    def YoloResetStats(self, modelHandle: int) -> int:
        """重置统计信息

        Args:
            modelHandle: 模型句柄

        Returns:
            1 成功, 0 失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("YoloResetStats")
        return func(self.OLAObject, modelHandle)

    def YoloGetLastError(self) -> str:
        """获取最后一次错误信息

        Returns:
            错误信息字符串

        Notes:
            1. DLL调用返回字符串指针地址,需要调用 FreeStringPtr接口释放内存
        """
        func = OLAPlugDLLHelper.get_function("YoloGetLastError")
        return self.PtrToStringUTF8(func(self.OLAObject))

    def YoloClearError(self) -> int:
        """清除错误信息

        Returns:
            1 成功, 0 失败

        Notes:
        """
        func = OLAPlugDLLHelper.get_function("YoloClearError")
        return func(self.OLAObject)


    def Query(self, db: int, sql: str) -> List[dict]:
        data = []  # 存储查询结果
        stmt = self.ExecuteReader(db, sql)  # 执行查询，获取语句句柄

        # 获取列名
        column_names = []
        for i in range(self.GetColumnCount(stmt)):
            column_names.append(self.GetColumnName(stmt, i))

        # 读取数据
        while self.Read(stmt):
            row = {}
            for column_name in column_names:
                i_col = self.GetColumnIndex(stmt, column_name)
                column_type = self.GetColumnType(stmt, i_col)

                # 根据列类型处理数据
                if column_type == 1:  # SQLITE_INTEGER
                    row[column_name] = self.GetInt64(stmt, i_col)
                elif column_type == 2:  # SQLITE_FLOAT
                    row[column_name] = self.GetDouble(stmt, i_col)
                elif column_type == 3:  # SQLITE_TEXT
                    row[column_name] = self.GetString(stmt, i_col)
                elif column_type == 4:  # SQLITE_BLOB
                    row[column_name] = self.GetString(stmt, i_col)  # 假设 BLOB 转为字符串
                elif column_type == 5:  # SQLITE_NULL
                    row[column_name] = None

            data.append(row)

        # 释放资源
        self.Finalize(stmt)
        return data

    def hotkey(self, *args: str, interval: float = 0.05) -> int:
        keys = [k.lower() if isinstance(k, str) else k for k in args]
        try:
            for key in keys:
                self.KeyDownChar(key)
                time.sleep(interval)
            for key in reversed(keys):
                self.KeyUpChar(key)
                time.sleep(interval)
            return 1
        except Exception as e:
            print(f"Error occurred during hotkey: {e}")
            # 可选：强制释放所有已按下的键
            for key in reversed(keys):
                self.KeyUpChar(key)
            return 0

