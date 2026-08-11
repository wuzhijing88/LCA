"""
多窗口停止管理器集成适配器
将增强的停止管理器集成到现有的多窗口执行器中
"""
import logging
from typing import Dict, Any, Optional
from PySide6.QtCore import QObject, Signal

from ..runtime_parts.enhanced_multi_window_stop_manager import (
    EnhancedMultiWindowStopManager,
    WindowStopContext,
    StopState
)

# 初始化logger
logger = logging.getLogger(__name__)

# 【内存优化】延迟导入OCR停止管理器，避免主程序启动时加载OCR模块
OCR_STOP_MANAGER_AVAILABLE = None  # None表示尚未检测
_ocr_stop_manager_module = None

def _ensure_ocr_stop_manager():
    """延迟检测并导入OCR停止管理器"""
    global OCR_STOP_MANAGER_AVAILABLE, _ocr_stop_manager_module
    if OCR_STOP_MANAGER_AVAILABLE is None:
        try:
            from services.enhanced_ocr_pool_stop_manager import get_ocr_stop_manager
            _ocr_stop_manager_module = get_ocr_stop_manager
            OCR_STOP_MANAGER_AVAILABLE = True
        except ImportError:
            OCR_STOP_MANAGER_AVAILABLE = False
            logger.warning("OCR停止管理器不可用")
    return OCR_STOP_MANAGER_AVAILABLE

def get_ocr_stop_manager():
    """获取OCR停止管理器（延迟导入）"""
    _ensure_ocr_stop_manager()
    if _ocr_stop_manager_module:
        return _ocr_stop_manager_module()
    return None


class MultiWindowStopIntegration(QObject):
    """多窗口停止管理器集成类"""
    
    # 转发信号
    stop_progress = Signal(str, str)  # window_id, status
    stop_completed = Signal(str, bool)  # window_id, success
    all_stopped = Signal(bool, str)  # success, message
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 创建增强的停止管理器
        self.stop_manager = EnhancedMultiWindowStopManager(self)
        
        # 连接信号
        self.stop_manager.stop_progress.connect(self.stop_progress)
        self.stop_manager.stop_completed.connect(self.stop_completed)
        self.stop_manager.all_stopped.connect(self.all_stopped)
        
        # 窗口映射（用于兼容现有代码）
        self.window_mapping: Dict[str, str] = {}  # old_key -> new_window_id
        
        logger.info("多窗口停止管理器集成已初始化")
    
    def integrate_with_executor(self, executor):
        """与现有执行器集成"""
        try:
            # 检查执行器类型并注册窗口
            if hasattr(executor, 'windows'):
                self._integrate_with_multi_window_executor(executor)
            elif hasattr(executor, 'window_contexts'):
                self._integrate_with_unified_executor(executor)
            else:
                logger.warning(f"未知的执行器类型: {type(executor)}")
                return False
            
            # 替换执行器的停止方法
            self._patch_executor_stop_method(executor)
            
            logger.info(f"已与执行器集成: {type(executor).__name__}")
            return True
            
        except Exception as e:
            logger.error(f"执行器集成失败: {e}", exc_info=True)
            return False
    
    def _integrate_with_multi_window_executor(self, executor):
        """与MultiWindowExecutor集成"""
        for window_key, window_state in executor.windows.items():
            window_id = f"mwe_{window_key}"
            self.window_mapping[window_key] = window_id
            
            self.stop_manager.register_window(
                window_id=window_id,
                title=window_state.title,
                hwnd=window_state.hwnd,
                thread=window_state.thread,
                executor=window_state.executor
            )
            
            logger.debug(f"注册MultiWindowExecutor窗口: {window_state.title}")
    
    def _integrate_with_unified_executor(self, executor):
        """与UnifiedMultiWindowExecutor集成"""
        for window_key, window_state in executor.windows.items():
            window_id = f"uwe_{window_key}"
            self.window_mapping[window_key] = window_id
            
            self.stop_manager.register_window(
                window_id=window_id,
                title=window_state.title,
                hwnd=window_state.hwnd,
                thread=window_state.thread,
                executor=window_state.executor
            )
            
            logger.debug(f"注册UnifiedMultiWindowExecutor窗口: {window_state.title}")
    
    def _patch_executor_stop_method(self, executor):
        """替换执行器的停止方法"""
        # 保存原始方法
        if hasattr(executor, 'stop_all'):
            executor._original_stop_all = executor.stop_all
        
        # 替换为增强的停止方法
        def enhanced_stop_all(force: bool = False):
            logger.info("使用增强的停止方法")
            return self.request_stop_all(force=force)
        
        executor.stop_all = enhanced_stop_all
        logger.debug("已替换执行器的停止方法")
    
    def request_stop_all(self, timeout: float = 30.0, force: bool = False) -> str:
        """请求停止所有窗口"""
        def completion_callback(success: bool, message: str):
            logger.info(f"停止完成回调: 成功={success}, 消息={message}")

            # 额外的OCR服务池清理（延迟检测）
            if _ensure_ocr_stop_manager():
                try:
                    ocr_stop_manager = get_ocr_stop_manager()
                    # 获取所有窗口句柄
                    all_hwnds = []
                    for window_id, mapped_id in self.window_mapping.items():
                        if mapped_id in self.stop_manager.window_contexts:
                            context = self.stop_manager.window_contexts[mapped_id]
                            all_hwnds.append(context.hwnd)

                    if all_hwnds:
                        logger.info(f"额外清理 {len(all_hwnds)} 个窗口的OCR服务")
                        ocr_stop_manager.request_stop_services_for_windows(all_hwnds, timeout=5.0)

                except Exception as e:
                    logger.error(f"额外OCR服务清理失败: {e}")

        return self.stop_manager.request_stop_all(
            timeout=timeout,
            callback=completion_callback,
            force=force,
        )
    
    def request_stop_window(self, window_key: str, timeout: float = 15.0) -> bool:
        """请求停止特定窗口"""
        window_id = self.window_mapping.get(window_key)
        if not window_id:
            logger.warning(f"未找到窗口映射: {window_key}")
            return False
        
        return self.stop_manager.request_stop_window(window_id, timeout)
    
    def get_stop_status(self) -> Dict[str, Any]:
        """获取停止状态"""
        status = self.stop_manager.get_stop_status()
        
        # 转换窗口ID回原始键
        if 'window_states' in status:
            converted_states = {}
            for window_id, state in status['window_states'].items():
                # 查找原始键
                original_key = None
                for old_key, mapped_id in self.window_mapping.items():
                    if mapped_id == window_id:
                        original_key = old_key
                        break
                
                if original_key:
                    converted_states[original_key] = state
                else:
                    converted_states[window_id] = state
            
            status['window_states'] = converted_states
        
        return status
    
    def is_stop_in_progress(self) -> bool:
        """检查是否正在停止"""
        return self.stop_manager._stop_in_progress
    
    def cleanup(self):
        """清理资源"""
        logger.info("清理多窗口停止集成")
        
        # 清理停止管理器
        self.stop_manager.cleanup()
        
        # 清理映射
        self.window_mapping.clear()




# 使用示例和测试函数
def test_stop_manager_integration():
    """测试停止管理器集成"""
    logger.info("开始测试停止管理器集成")
    
    try:
        # 创建停止集成
        integration = MultiWindowStopIntegration()
        
        # 模拟窗口注册
        integration.stop_manager.register_window(
            window_id="test_window_1",
            title="测试窗口1",
            hwnd=12345,
            thread=None,
            executor=None
        )
        
        # 测试停止请求
        request_id = integration.request_stop_all(timeout=5.0)
        logger.info(f"停止请求ID: {request_id}")
        
        # 获取状态
        status = integration.get_stop_status()
        logger.info(f"停止状态: {status}")
        
        # 清理
        integration.cleanup()
        
        logger.info("停止管理器集成测试完成")
        return True
        
    except Exception as e:
        logger.error(f"停止管理器集成测试失败: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 运行测试
    test_stop_manager_integration()
