#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级Python反编译保护模块
专门针对Python反编译工具的深度防护
"""

import os
import sys
import time
import hashlib
import base64
import marshal
import types
import inspect
import gc
import threading
import random
from typing import Optional, List, Dict, Any

MODE_DETECT = "detect"
MODE_BLOCK = "block"
SCAN_LEVELS = ("low", "standard", "strict")

DECOMPILE_MODULES = [
    "uncompyle6", "decompyle3", "xdis", "pycdc", "unpyc",
    "pyinstxtractor", "pyinstaller_extractor", "archive_viewer",
]

FILE_MARKERS = [
    ".extracted", ".decompiled", "uncompyle6", "decompyle3",
    "pycdc", "pyinstxtractor", "pyinstaller-extractor",
]

DEBUG_MODULES = [
    "debugpy", "pydevd", "pdb", "pudb", "ipdb", "bdb", "pydbg", "winappdbg",
]

DEBUG_ENV_VARS = [
    "PYTHONINSPECT", "PYTHONBREAKPOINT", "PYCHARM_HOSTED", "PYDEV_DEBUG",
    "PYDEVD_LOAD_VALUES_ASYNC", "DEBUGPY_RUNNING",
]


def _normalize_mode(mode: Optional[str]) -> str:
    if not mode:
        return MODE_DETECT
    mode_value = str(mode).strip().lower()
    if mode_value in ("block", "strict", "enforce", "exit"):
        return MODE_BLOCK
    return MODE_DETECT


def _normalize_scan_level(scan_level: Optional[str]) -> str:
    if not scan_level:
        return "standard"
    level = str(scan_level).strip().lower()
    return level if level in SCAN_LEVELS else "standard"


def _coerce_interval(check_interval: Optional[float]) -> float:
    try:
        interval = float(check_interval)
        return 5.0 if interval < 5.0 else interval
    except Exception:
        return 30.0


def _normalize_scan_roots(scan_roots: Optional[List[str]]) -> List[str]:
    roots: List[str] = []
    if not scan_roots:
        return roots
    for root in scan_roots:
        if not root:
            continue
        normalized = os.path.abspath(str(root))
        if os.path.isdir(normalized) and normalized not in roots:
            roots.append(normalized)
    return roots


def _default_scan_roots() -> List[str]:
    roots: List[str] = []
    try:
        from utils.app_paths import get_app_root
        app_root = get_app_root()
    except Exception:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.getcwd(),
        os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else "",
        app_root,
        os.path.dirname(sys.executable) if sys.executable else "",
    ]
    for root in candidates:
        if root:
            normalized = os.path.abspath(root)
            if os.path.isdir(normalized) and normalized not in roots:
                roots.append(normalized)
    return roots


def _hash_file(path: str) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None

class AdvancedAntiDecompile:
    """高级反编译保护器"""
    
    def __init__(
        self,
        mode: Optional[str] = MODE_BLOCK,
        scan_level: Optional[str] = "standard",
        check_interval: Optional[float] = 30.0,
        enable_gc_scan: Optional[bool] = None,
        scan_roots: Optional[List[str]] = None,
    ):
        self._protection_active = False
        self._mode = _normalize_mode(mode)
        self._scan_level = _normalize_scan_level(scan_level)
        self._check_interval = _coerce_interval(check_interval)
        self._enable_gc_scan = (
            enable_gc_scan if enable_gc_scan is not None else self._scan_level == "strict"
        )
        self._scan_roots = _normalize_scan_roots(scan_roots) or _default_scan_roots()
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self._original_bytecode_hashes = {}
        self._module_file_hashes = {}
        self._last_threats: List[str] = []

        # 精确的反编译工具特征检测（避免误报）
        self._decompile_signatures = [
            b'uncompyle6', b'decompyle3', b'pycdc', b'unpyc',
            b'pyinstxtractor', b'pyinstaller-extractor'
        ]

        # 初始化保护
        self._init_protection()

    def configure(
        self,
        mode: Optional[str] = None,
        scan_level: Optional[str] = None,
        check_interval: Optional[float] = None,
        enable_gc_scan: Optional[bool] = None,
        scan_roots: Optional[List[str]] = None,
    ):
        """更新保护配置（运行中可安全调用）"""
        if mode is not None:
            self._mode = _normalize_mode(mode)
        if scan_level is not None:
            self._scan_level = _normalize_scan_level(scan_level)
        if check_interval is not None:
            self._check_interval = _coerce_interval(check_interval)
        if scan_level is not None and enable_gc_scan is None:
            self._enable_gc_scan = self._scan_level == "strict"
        if enable_gc_scan is not None:
            self._enable_gc_scan = bool(enable_gc_scan)
        if scan_roots is not None:
            roots = _normalize_scan_roots(scan_roots)
            self._scan_roots = roots or self._scan_roots or _default_scan_roots()

        self._start_monitoring()

    
    def _init_protection(self):
        """初始化保护机制"""
        try:
            # 记录关键函数的原始字节码哈希
            self._record_original_bytecode()
            
            # 启动监控线程
            self._start_monitoring()
            
            # 设置异常钩子
            self._setup_exception_hooks()
            
        except Exception:
            pass  # 静默失败，不暴露保护机制

    def _iter_protected_callables(self) -> List[tuple]:
        items = []
        current_module = sys.modules.get(__name__)
        if not current_module:
            return items
        for name, obj in inspect.getmembers(current_module):
            if inspect.isfunction(obj) and getattr(obj, "__module__", None) == __name__:
                items.append((f"func:{name}", obj))
            elif inspect.isclass(obj) and getattr(obj, "__module__", None) == __name__:
                for method_name, method in inspect.getmembers(obj):
                    if inspect.isfunction(method) and getattr(method, "__module__", None) == __name__:
                        items.append((f"class:{name}.{method_name}", method))
        return items
    
    def _record_original_bytecode(self):
        """记录关键函数的原始字节码哈希"""
        try:
            # 获取当前模块的所有函数与类方法
            for key, obj in self._iter_protected_callables():
                if hasattr(obj, '__code__'):
                    bytecode = obj.__code__.co_code
                    hash_value = hashlib.sha256(bytecode).hexdigest()
                    self._original_bytecode_hashes[key] = hash_value

            current_module = sys.modules.get(__name__)
            module_file = getattr(current_module, "__file__", None) if current_module else None
            if module_file and os.path.isfile(module_file):
                file_hash = _hash_file(module_file)
                if file_hash:
                    self._module_file_hashes[module_file] = file_hash
        except Exception:
            pass
    
    def _start_monitoring(self):
        """启动后台监控线程"""
        try:
            self._protection_active = True
            self._stop_event.clear()
            if self._monitor_thread is None or not self._monitor_thread.is_alive():
                self._monitor_thread = threading.Thread(
                    target=self._continuous_monitoring,
                    daemon=True
                )
                self._monitor_thread.start()
        except Exception:
            pass
    
    def _continuous_monitoring(self):
        """持续监控威胁"""
        while self._protection_active and not self._stop_event.is_set():
            try:
                threats_detected = []

                # 检查反编译威胁
                decompile_threats = self._detect_decompilation_attempt() or []
                if decompile_threats:
                    threats_detected.extend(decompile_threats)

                # 检查字节码完整性
                bytecode_threats = self._check_bytecode_integrity() or []
                if bytecode_threats:
                    threats_detected.extend(bytecode_threats)

                # 检查文件完整性
                file_threats = self._check_file_integrity() or []
                if file_threats:
                    threats_detected.extend(file_threats)

                # 检查内存中的可疑模块
                module_threats = self._check_suspicious_modules() or []
                if module_threats:
                    threats_detected.extend(module_threats)

                # 检查调试器信号
                debug_threats = self._check_debugger_signals() or []
                if debug_threats:
                    threats_detected.extend(debug_threats)

                # 如果检测到威胁，触发保护并显示详细信息
                if threats_detected:
                    self._trigger_protection(threats_detected)

                if self._stop_event.wait(self._check_interval):
                    return

            except Exception as e:
                # 监控过程中的异常不应该影响主程序
                import logging
                logging.debug(f"监控过程异常: {e}")
                if self._stop_event.wait(self._check_interval):
                    return
    
    def _detect_decompilation_attempt(self) -> list:
        """检测反编译尝试"""
        threats_found = []

        try:
            # 1. 内存字符串扫描（严格模式或显式启用）
            if self._enable_gc_scan:
                max_hits = 5
                max_objects = 20000 if self._scan_level == "strict" else 5000
                scanned = 0
                for obj in gc.get_objects():
                    scanned += 1
                    if scanned > max_objects or len(threats_found) >= max_hits:
                        break
                    if isinstance(obj, (str, bytes)):
                        if isinstance(obj, str) and len(obj) > 200:
                            continue
                        obj_data = obj if isinstance(obj, bytes) else obj.encode('utf-8', errors='ignore')
                        if len(obj_data) > 200:
                            continue
                        for signature in self._decompile_signatures:
                            if signature in obj_data:
                                threats_found.append(
                                    f"内存中发现反编译工具特征: {signature.decode('utf-8', errors='ignore')}"
                                )
                                break

            # 2. 检查调用栈中的可疑操作（排除自身文件）
            if self._scan_level != "low":
                frame = sys._getframe()
                while frame:
                    try:
                        filename = frame.f_code.co_filename
                        # 排除自身的保护文件
                        if 'advanced_anti_decompile.py' not in filename:
                            lowered = filename.lower()
                            if any(keyword in lowered for keyword in
                                   ['uncompyle6', 'decompyle3', 'pycdc', 'pyinstxtractor']):
                                threats_found.append(f"调用栈中发现可疑文件: {filename}")
                                break
                        frame = frame.f_back
                    except Exception:
                        break

            # 3. 检查扫描目录中的可疑文件（非递归）
            for root in self._scan_roots:
                try:
                    for file in os.listdir(root):
                        file_path = os.path.join(root, file)
                        if os.path.isfile(file_path):
                            file_lower = file.lower()
                            if any(marker in file_lower for marker in FILE_MARKERS):
                                threats_found.append(f"发现可疑文件: {file} ({root})")
                except Exception:
                    continue

            return threats_found

        except Exception:
            return []
    
    def _check_bytecode_integrity(self) -> list:
        """检查字节码完整性"""
        threats_found = []

        try:
            if self._scan_level == "low":
                return threats_found
            for key, obj in self._iter_protected_callables():
                if key in self._original_bytecode_hashes and hasattr(obj, '__code__'):
                    current_bytecode = obj.__code__.co_code
                    current_hash = hashlib.sha256(current_bytecode).hexdigest()
                    if current_hash != self._original_bytecode_hashes[key]:
                        threats_found.append(f"字节码被修改: {key}")

            return threats_found

        except Exception as e:
            threats_found.append(f"字节码完整性检查异常: {e}")
            return threats_found

    def _check_file_integrity(self) -> list:
        """检查关键文件完整性"""
        threats_found = []
        try:
            if self._scan_level != "strict":
                return threats_found
            for path, original_hash in self._module_file_hashes.items():
                if not path or not os.path.isfile(path):
                    continue
                current_hash = _hash_file(path)
                if current_hash and current_hash != original_hash:
                    threats_found.append(f"文件内容被修改: {os.path.basename(path)}")
            return threats_found
        except Exception:
            return threats_found

    def _check_debugger_signals(self) -> list:
        """检测调试器信号"""
        threats_found = []
        try:
            if self._scan_level == "low":
                return threats_found
            debug_trace = bool(sys.gettrace())
            debug_profile = bool(sys.getprofile())
            debug_env = False
            for env_key in DEBUG_ENV_VARS:
                if os.environ.get(env_key):
                    threats_found.append(f"检测到调试环境变量: {env_key}")
                    debug_env = True
            if debug_trace:
                threats_found.append("检测到调试跟踪器")
            if debug_profile:
                threats_found.append("检测到性能分析钩子")
            debug_active = debug_trace or debug_profile or debug_env
            for module_name in DEBUG_MODULES:
                if module_name in sys.modules:
                    if module_name in ("pdb", "bdb") and not debug_active:
                        continue
                    threats_found.append(f"检测到调试模块: {module_name}")
            return threats_found
        except Exception:
            return threats_found
    
    def _check_suspicious_modules(self) -> list:
        """检查可疑模块"""
        threats_found = []

        try:
            # 只检查明确的反编译工具，不检查Python内置模块
            for module_name in DECOMPILE_MODULES:
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                    # 进一步验证是否真的是反编译工具
                    if hasattr(module, '__file__') and module.__file__:
                        threats_found.append(f"检测到反编译模块: {module_name} ({module.__file__})")
                    else:
                        threats_found.append(f"检测到反编译模块: {module_name}")

            return threats_found

        except Exception as e:
            # 不记录正常的异常
            return threats_found
    
    def _setup_exception_hooks(self):
        """设置异常钩子来检测调试尝试"""
        try:
            original_excepthook = sys.excepthook

            def _scan_traceback(exc_traceback):
                if not exc_traceback:
                    return None
                frame = exc_traceback.tb_frame
                while frame:
                    filename = frame.f_code.co_filename
                    if filename and any(keyword in filename.lower() for keyword in
                                       ['decompile', 'extract', 'unpack', 'debug']):
                        return filename
                    frame = frame.f_back
                return None
            
            def protected_excepthook(exc_type, exc_value, exc_traceback):
                # 检查异常是否来自反编译工具
                filename = _scan_traceback(exc_traceback)
                if filename:
                    self._trigger_protection([f"异常栈中发现可疑文件: {filename}"])
                    if self._mode == MODE_BLOCK:
                        return
                
                # 调用原始异常处理器
                original_excepthook(exc_type, exc_value, exc_traceback)
            
            sys.excepthook = protected_excepthook

            if hasattr(threading, "excepthook"):
                original_thread_hook = threading.excepthook

                def protected_thread_excepthook(args):
                    filename = _scan_traceback(getattr(args, "exc_traceback", None))
                    if filename:
                        self._trigger_protection([f"线程异常栈中发现可疑文件: {filename}"])
                        if self._mode == MODE_BLOCK:
                            return
                    if original_thread_hook:
                        original_thread_hook(args)

                threading.excepthook = protected_thread_excepthook
            
        except Exception:
            pass
    
    def _trigger_protection(self, threats_detected=None):
        """触发保护机制（检测到威胁直接退出）"""
        try:
            threats = list(threats_detected or [])
            self._last_threats = threats
            import logging

            if threats:
                threat_details = "; ".join(threats)
                if self._mode == MODE_BLOCK:
                    print(f"严重 高级反编译保护检测到威胁: {threat_details}")
                    logging.critical(f"高级反编译保护检测到威胁: {threat_details}")
                    for threat in threats:
                        logging.critical(f"威胁详情: {threat}")
                else:
                    print(f"提示 高级反编译保护检测到威胁: {threat_details}")
                    logging.warning(f"高级反编译保护检测到威胁: {threat_details}")
            else:
                if self._mode == MODE_BLOCK:
                    print("严重 高级反编译保护检测到未知威胁")
                    logging.critical("高级反编译保护检测到未知威胁")
                else:
                    print("提示 高级反编译保护检测到未知威胁")
                    logging.warning("高级反编译保护检测到未知威胁")

            if self._mode != MODE_BLOCK:
                return

            # 清理敏感数据
            self._cleanup_sensitive_data()

            # 混淆内存
            self._obfuscate_memory()

            # 强制退出程序
            print("程序因安全威胁退出")
            os._exit(1)

        except Exception as e:
            print(f"严重 保护机制触发时发生异常: {e}")
            import logging
            logging.critical(f"保护机制触发异常: {e}")
            # 即使异常也要退出
            if self._mode == MODE_BLOCK:
                os._exit(1)
    
    def _cleanup_sensitive_data(self):
        """清理内存中的敏感数据"""
        try:
            # 清理包含敏感信息的对象
            for obj in gc.get_objects():
                if isinstance(obj, str):
                    if any(keyword in obj for keyword in 
                           ['ED-', 'license', 'key', 'token', 'password']):
                        try:
                            # 尝试清零字符串内容（Python中字符串不可变，但可以尝试）
                            obj = '0' * len(obj)
                        except:
                            pass
            
            
        except Exception:
            pass
    
    def _obfuscate_memory(self):
        """混淆内存内容"""
        try:
            # 创建大量随机数据来混淆内存
            dummy_data = []
            for _ in range(1000):
                dummy_data.append(''.join(chr(random.randint(32, 126)) for _ in range(100)))
            
            # 立即删除
            del dummy_data
            
        except Exception:
            pass
    
    def stop_protection(self):
        """停止保护（用于正常退出）"""
        self._protection_active = False
        self._stop_event.set()
        monitor_thread = self._monitor_thread
        if monitor_thread is not None and monitor_thread.is_alive():
            try:
                monitor_thread.join(timeout=2.0)
            except Exception:
                pass
        if monitor_thread is self._monitor_thread and (monitor_thread is None or not monitor_thread.is_alive()):
            self._monitor_thread = None

# 全局保护实例
_global_anti_decompile = None

def init_advanced_protection(
    mode: Optional[str] = MODE_BLOCK,
    scan_level: Optional[str] = "standard",
    check_interval: Optional[float] = 30.0,
    enable_gc_scan: Optional[bool] = None,
    scan_roots: Optional[List[str]] = None,
):
    """初始化高级反编译保护"""
    global _global_anti_decompile
    if _global_anti_decompile is None:
        _global_anti_decompile = AdvancedAntiDecompile(
            mode=mode,
            scan_level=scan_level,
            check_interval=check_interval,
            enable_gc_scan=enable_gc_scan,
            scan_roots=scan_roots,
        )
    else:
        _global_anti_decompile.configure(
            mode=mode,
            scan_level=scan_level,
            check_interval=check_interval,
            enable_gc_scan=enable_gc_scan,
            scan_roots=scan_roots,
        )

def stop_advanced_protection():
    """停止高级保护"""
    global _global_anti_decompile
    if _global_anti_decompile:
        _global_anti_decompile.stop_protection()
