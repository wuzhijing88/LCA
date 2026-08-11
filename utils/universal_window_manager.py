"""
通用窗口管理器 - 统一处理窗口分辨率调整和管理
基于通用分辨率适配器，提供标准化的窗口操作接口

功能：
1. 窗口分辨率调整
2. 多窗口批量调整
3. 窗口状态监控
4. DPI变化检测和处理
"""

import logging
import threading
import time
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass
from utils.app_paths import get_config_path
from .universal_resolution_adapter import get_universal_adapter, REFERENCE_WIDTH, REFERENCE_HEIGHT
from .window_finder import resolve_unique_window_hwnd


logger = logging.getLogger(__name__)

@dataclass
class WindowAdjustmentResult:
    """窗口调整结果"""
    hwnd: int
    title: str
    success: bool
    message: str
    before_size: Tuple[int, int] = (0, 0)
    after_size: Tuple[int, int] = (0, 0)
    adjustment_time: float = 0.0

class UniversalWindowManager:
    """通用窗口管理器"""

    def __init__(self):
        self.adapter = get_universal_adapter()
        self._lock = threading.RLock()
        self._adjustment_callbacks: List[Callable] = []
        self._monitoring_enabled = True
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop_event = threading.Event()

        logger.info("通用窗口管理器初始化完成")
    
    def add_adjustment_callback(self, callback: Callable[[WindowAdjustmentResult], None]):
        """添加窗口调整回调函数"""
        with self._lock:
            if callback not in self._adjustment_callbacks:
                self._adjustment_callbacks.append(callback)
    
    def remove_adjustment_callback(self, callback: Callable):
        """移除窗口调整回调函数"""
        with self._lock:
            if callback in self._adjustment_callbacks:
                self._adjustment_callbacks.remove(callback)
    
    def _notify_adjustment_callbacks(self, result: WindowAdjustmentResult):
        """通知窗口调整回调"""
        with self._lock:
            for callback in self._adjustment_callbacks:
                try:
                    callback(result)
                except Exception as e:
                    logger.error(f"窗口调整回调执行失败: {e}")
    
    def adjust_single_window(self, hwnd: int, target_width: int = REFERENCE_WIDTH,
                           target_height: int = REFERENCE_HEIGHT, async_mode: bool = False) -> WindowAdjustmentResult:
        """调整单个窗口分辨率"""
        start_time = time.time()

        # 如果没有指定目标分辨率，尝试从全局设置获取
        if target_width == REFERENCE_WIDTH and target_height == REFERENCE_HEIGHT:
            try:
                # 尝试获取全局设置的分辨率
                global_width, global_height = self._get_global_resolution_settings()
                if global_width > 0 and global_height > 0:
                    target_width = global_width
                    target_height = global_height
                    logger.info(f"使用全局设置的分辨率: {target_width}x{target_height}")
            except Exception as e:
                logger.debug(f"获取全局分辨率设置失败，使用默认值: {e}")

        return self._adjust_standard_window(hwnd, target_width, target_height, start_time)

    def _adjust_standard_window(self, hwnd: int, target_width: int, target_height: int, start_time: float) -> WindowAdjustmentResult:
        """调整标准窗口分辨率"""
        # 获取窗口状态
        window_state = self.adapter.get_window_state(hwnd, force_refresh=True)
        if not window_state:
            result = WindowAdjustmentResult(
                hwnd=hwnd,
                title="未知窗口",
                success=False,
                message="无法获取窗口状态",
                adjustment_time=time.time() - start_time
            )
            self._notify_adjustment_callbacks(result)
            return result

        before_size = (window_state.width, window_state.height)

        # 检查当前分辨率是否已经符合要求
        if window_state.width == target_width and window_state.height == target_height:
            logger.info(f"窗口 {window_state.title} 当前分辨率 {window_state.width}x{window_state.height} 已符合目标分辨率，跳过调整")
            result = WindowAdjustmentResult(
                hwnd=hwnd,
                title=window_state.title,
                success=True,
                message="分辨率已符合要求，无需调整",
                before_size=before_size,
                after_size=before_size,
                adjustment_time=time.time() - start_time
            )
            self._notify_adjustment_callbacks(result)
            return result

        # 执行调整
        logger.info(f"调整窗口分辨率: {window_state.title} ({before_size[0]}x{before_size[1]} -> {target_width}x{target_height})")
        
        success = self.adapter.adjust_window_resolution(hwnd, target_width, target_height)
        
        # 获取调整后的状态
        after_state = self.adapter.get_window_state(hwnd, force_refresh=True)
        after_size = (after_state.width, after_state.height) if after_state else before_size
        
        result = WindowAdjustmentResult(
            hwnd=hwnd,
            title=window_state.title,
            success=success,
            message="调整成功" if success else "调整失败",
            before_size=before_size,
            after_size=after_size,
            adjustment_time=time.time() - start_time
        )
        
        self._notify_adjustment_callbacks(result)
        return result
    
    def adjust_multiple_windows(self, window_list: List[Dict[str, Any]],
                              target_width: int = REFERENCE_WIDTH,
                              target_height: int = REFERENCE_HEIGHT) -> List[WindowAdjustmentResult]:
        """批量调整多个窗口分辨率"""
        results = []

        logger.info(f"开始批量调整 {len(window_list)} 个窗口到 {target_width}x{target_height}")

        # 首先验证所有窗口句柄的唯一性
        hwnd_count = {}
        for i, window_info in enumerate(window_list):
            hwnd = window_info.get('hwnd')
            title = window_info.get('title', '未知窗口')
            logger.info(f"窗口 {i+1}: {title} (HWND: {hwnd})")

            if hwnd:
                hwnd_count[hwnd] = hwnd_count.get(hwnd, 0) + 1

        # 检查重复的句柄
        duplicate_hwnds = [hwnd for hwnd, count in hwnd_count.items() if count > 1]
        if duplicate_hwnds:
            logger.warning(f"发现重复的窗口句柄: {duplicate_hwnds}")

        for i, window_info in enumerate(window_list):
            hwnd = window_info.get('hwnd')
            title = window_info.get('title', '未知窗口')

            if not hwnd:
                # 尝试通过标题查找窗口
                if title:
                    hwnd = self._find_window_by_title(title)
                    if hwnd:
                        window_info['hwnd'] = hwnd
                        logger.info(f"通过标题找到窗口句柄: {title} -> {hwnd}")

            if hwnd:
                # 验证窗口句柄是否有效
                try:
                    import win32gui
                    if not win32gui.IsWindow(hwnd):
                        logger.error(f"窗口句柄无效: {title} (HWND: {hwnd})")
                        result = WindowAdjustmentResult(
                            hwnd=hwnd,
                            title=title,
                            success=False,
                            message="窗口句柄无效"
                        )
                        results.append(result)
                        continue
                except Exception as e:
                    logger.error(f"验证窗口句柄时出错: {e}")

                logger.info(f"[批量调整] 调整窗口 {i+1}/{len(window_list)}: {title} (HWND: {hwnd})")
                result = self.adjust_single_window(hwnd, target_width, target_height)
                logger.info(f"[批量调整] 窗口 {i+1} 调整结果: 成功={result.success}, "
                           f"调整前={result.before_size}, 调整后={result.after_size}")
                results.append(result)
            else:
                logger.error(f"无法找到窗口句柄: {title}")
                result = WindowAdjustmentResult(
                    hwnd=0,
                    title=title,
                    success=False,
                    message="无法找到窗口句柄"
                )
                results.append(result)
                self._notify_adjustment_callbacks(result)

        # 统计结果
        success_count = sum(1 for r in results if r.success)
        logger.info(f"批量调整完成: 成功 {success_count}/{len(results)} 个窗口")

        return results

    def _find_window_by_title(self, title: str) -> Optional[int]:
        """通过标题查找窗口句柄"""
        try:
            return resolve_unique_window_hwnd(title)
        except Exception as e:
            logger.error(f"查找窗口失败: {e}")
            return None
    
    def get_window_adjustment_status(self, hwnd: int, target_width: int = REFERENCE_WIDTH,
                                   target_height: int = REFERENCE_HEIGHT) -> Dict[str, Any]:
        """获取窗口调整状态"""
        window_state = self.adapter.get_window_state(hwnd)
        if not window_state:
            return {"error": "无法获取窗口状态"}
        
        needs_adjustment = (window_state.width != target_width or 
                          window_state.height != target_height)
        
        return {
            "hwnd": hwnd,
            "title": window_state.title,
            "current_size": f"{window_state.width}x{window_state.height}",
            "target_size": f"{target_width}x{target_height}",
            "needs_adjustment": needs_adjustment,
            "dpi_info": {
                "dpi": window_state.dpi,
                "scale_factor": window_state.scale_factor
            },
            "size_difference": {
                "width_diff": window_state.width - target_width,
                "height_diff": window_state.height - target_height
            }
        }
    
    def monitor_window_changes(self, window_list: List[Dict[str, Any]], 
                             check_interval: float = 5.0,
                             auto_adjust: bool = False) -> None:
        """监控窗口变化（在后台线程中运行）"""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            logger.info("窗口监控线程已在运行，跳过重复启动")
            return

        self._monitoring_enabled = True
        self._monitor_stop_event.clear()

        def monitor_thread():
            logger.info(f"开始监控 {len(window_list)} 个窗口的变化")
            
            while self._monitoring_enabled:
                try:
                    for window_info in window_list:
                        hwnd = window_info.get('hwnd')
                        if not hwnd:
                            continue
                        
                        # 检查窗口状态
                        current_state = self.adapter.get_window_state(hwnd, force_refresh=True)
                        if not current_state:
                            continue
                        
                        # 检查是否需要调整
                        target_width = window_info.get('target_width', REFERENCE_WIDTH)
                        target_height = window_info.get('target_height', REFERENCE_HEIGHT)
                        
                        if (current_state.width != target_width or 
                            current_state.height != target_height):
                            
                            logger.info(f"检测到窗口尺寸变化: {current_state.title} "
                                      f"({current_state.width}x{current_state.height})")
                            
                            if auto_adjust:
                                self.adjust_single_window(hwnd, target_width, target_height)
                            
                    if self._monitor_stop_event.wait(check_interval):
                        break
                    
                except Exception as e:
                    logger.error(f"窗口监控过程中发生错误: {e}")
                    if self._monitor_stop_event.wait(check_interval):
                        break
        
        # 在后台线程中启动监控
        self._monitor_thread = threading.Thread(target=monitor_thread, daemon=True)
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """停止窗口监控"""
        self._monitoring_enabled = False
        self._monitor_stop_event.set()
        if self._monitor_thread is not None:
            try:
                self._monitor_thread.join(timeout=2.0)
            except Exception:
                pass
            self._monitor_thread = None
        logger.info("窗口监控已停止")
    
    def get_all_adjustable_windows(self) -> List[Dict[str, Any]]:
        """获取所有可调整的窗口列表"""
        try:
            import win32gui
            
            windows = []
            
            def enum_windows_callback(hwnd, windows_list):
                if win32gui.IsWindowVisible(hwnd):
                    try:
                        title = win32gui.GetWindowText(hwnd)
                        if title and len(title.strip()) > 0:
                            window_state = self.adapter.get_window_state(hwnd)
                            if window_state and window_state.width > 100 and window_state.height > 100:
                                windows_list.append({
                                    'hwnd': hwnd,
                                    'title': title,
                                    'size': f"{window_state.width}x{window_state.height}",
                                    'dpi': window_state.dpi,
                                    'needs_adjustment': (window_state.width != REFERENCE_WIDTH or 
                                                       window_state.height != REFERENCE_HEIGHT)
                                })
                    except Exception:
                        pass
                return True
            
            win32gui.EnumWindows(enum_windows_callback, windows)
            return windows
            
        except Exception as e:
            logger.error(f"获取窗口列表失败: {e}")
            return []

    def _get_global_resolution_settings(self) -> Tuple[int, int]:
        """获取全局设置的分辨率"""
        try:
            # 尝试从主窗口获取分辨率设置
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if hasattr(widget, 'custom_width') and hasattr(widget, 'custom_height'):
                        width = getattr(widget, 'custom_width', 0)
                        height = getattr(widget, 'custom_height', 0)
                        if width > 0 and height > 0:
                            logger.debug(f"从主窗口获取全局分辨率设置: {width}x{height}")
                            return (width, height)

            # 如果无法从主窗口获取，尝试从配置文件读取
            import json
            import os
            config_path = get_config_path()
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    width = config.get('custom_width', 0)
                    height = config.get('custom_height', 0)
                    if width > 0 and height > 0:
                        logger.debug(f"从配置文件获取全局分辨率设置: {width}x{height}")
                        return (width, height)

            return (0, 0)

        except Exception as e:
            logger.debug(f"获取全局分辨率设置失败: {e}")
            return (0, 0)
    
    def create_adjustment_report(self, results: List[WindowAdjustmentResult]) -> Dict[str, Any]:
        """创建调整报告"""
        if not results:
            return {"error": "没有调整结果"}
        
        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count
        total_time = sum(r.adjustment_time for r in results)
        
        successful_windows = [r for r in results if r.success]
        failed_windows = [r for r in results if not r.success]
        
        return {
            "summary": {
                "total_windows": len(results),
                "successful": success_count,
                "failed": failed_count,
                "success_rate": f"{success_count/len(results)*100:.1f}%",
                "total_time": f"{total_time:.2f}s",
                "average_time": f"{total_time/len(results):.2f}s"
            },
            "successful_windows": [
                {
                    "title": r.title,
                    "before": f"{r.before_size[0]}x{r.before_size[1]}",
                    "after": f"{r.after_size[0]}x{r.after_size[1]}",
                    "time": f"{r.adjustment_time:.2f}s"
                }
                for r in successful_windows
            ],
            "failed_windows": [
                {
                    "title": r.title,
                    "reason": r.message,
                    "time": f"{r.adjustment_time:.2f}s"
                }
                for r in failed_windows
            ]
        }


# 全局实例
_window_manager = None

def get_universal_window_manager() -> UniversalWindowManager:
    """获取全局通用窗口管理器实例"""
    global _window_manager
    if _window_manager is None:
        _window_manager = UniversalWindowManager()
    return _window_manager
