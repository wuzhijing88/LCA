"""
增强的OCR服务池停止管理器
解决多窗口停止时OCR服务池的清理和资源释放问题
"""
import logging
import threading
import time
from typing import Dict, List, Set, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OCRServiceState(Enum):
    """OCR服务状态"""
    ACTIVE = "active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class OCRServiceStopContext:
    """OCR服务停止上下文"""
    service_id: str
    window_hwnd: int
    window_title: str
    state: OCRServiceState = OCRServiceState.ACTIVE
    stop_requested_at: Optional[float] = None
    stopped_at: Optional[float] = None
    error_message: Optional[str] = None


class EnhancedOCRPoolStopManager:
    """增强的OCR服务池停止管理器"""
    
    def __init__(self):
        self._stop_contexts: Dict[str, OCRServiceStopContext] = {}
        self._window_service_mapping: Dict[int, str] = {}  # hwnd -> service_id
        self._lock = threading.RLock()
        self._stop_in_progress = False
        
        # 统计信息
        self.stop_stats = {
            'total_services_stopped': 0,
            'successful_stops': 0,
            'failed_stops': 0,
            'forced_stops': 0,
            'average_stop_time': 0.0
        }
        
        logger.info("增强OCR服务池停止管理器已初始化")
    
    def register_ocr_service(self, service_id: str, window_hwnd: int, window_title: str):
        """注册OCR服务"""
        with self._lock:
            context = OCRServiceStopContext(
                service_id=service_id,
                window_hwnd=window_hwnd,
                window_title=window_title
            )
            self._stop_contexts[service_id] = context
            self._window_service_mapping[window_hwnd] = service_id
            
            logger.debug(f"注册OCR服务: {service_id} -> {window_title} (HWND: {window_hwnd})")
    
    def sync_with_ocr_pool(self, ocr_pool):
        """与OCR服务池同步状态"""
        try:
            with self._lock:
                # 清空现有映射
                self._stop_contexts.clear()
                self._window_service_mapping.clear()
                
                # 从OCR池同步当前服务
                if hasattr(ocr_pool, 'ocr_services') and hasattr(ocr_pool, 'window_service_mapping'):
                    for window_hwnd, service_id in ocr_pool.window_service_mapping.items():
                        if service_id in ocr_pool.ocr_services:
                            service_instance = ocr_pool.ocr_services[service_id]
                            self.register_ocr_service(
                                service_id=service_id,
                                window_hwnd=window_hwnd,
                                window_title=service_instance.window_title
                            )
                
                logger.info(f"已同步 {len(self._stop_contexts)} 个OCR服务状态")
                
        except Exception as e:
            logger.error(f"同步OCR服务池状态失败: {e}")
    
    def request_stop_services_for_windows(self, window_hwnds: List[int], timeout: float = 15.0) -> bool:
        """为指定窗口请求停止OCR服务"""
        if not window_hwnds:
            return True
        
        with self._lock:
            if self._stop_in_progress:
                logger.warning("OCR服务停止操作已在进行中")
                return False
            
            self._stop_in_progress = True
            
            # 找到需要停止的服务
            services_to_stop = []
            for hwnd in window_hwnds:
                if hwnd in self._window_service_mapping:
                    service_id = self._window_service_mapping[hwnd]
                    if service_id in self._stop_contexts:
                        context = self._stop_contexts[service_id]
                        if context.state == OCRServiceState.ACTIVE:
                            context.state = OCRServiceState.STOPPING
                            context.stop_requested_at = time.time()
                            services_to_stop.append(context)
            
            if not services_to_stop:
                logger.info("没有需要停止的OCR服务")
                self._stop_in_progress = False
                return True
            
            logger.info(f"开始停止 {len(services_to_stop)} 个OCR服务")
            
            # 在后台线程中执行停止操作
            stop_thread = threading.Thread(
                target=self._execute_stop_services,
                args=(services_to_stop, timeout),
                name="OCRServiceStopper",
                daemon=True
            )
            stop_thread.start()
            
            return True
    
    def request_stop_all_services(self, timeout: float = 20.0) -> bool:
        """停止所有OCR服务"""
        with self._lock:
            all_hwnds = list(self._window_service_mapping.keys())
            return self.request_stop_services_for_windows(all_hwnds, timeout)
    
    def _execute_stop_services(self, services_to_stop: List[OCRServiceStopContext], timeout: float):
        """执行停止OCR服务操作"""
        start_time = time.time()
        success_count = 0
        failed_count = 0
        forced_count = 0
        
        try:
            # 获取OCR服务池实例
            from services.multiprocess_ocr_pool import get_multi_ocr_pool
            ocr_pool = get_multi_ocr_pool()
            
            # 第一阶段：优雅停止服务
            logger.info("第一阶段：优雅停止OCR服务")
            graceful_timeout = timeout * 0.7  # 70%时间用于优雅停止
            
            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="ocr_graceful_stop") as executor:
                futures = []
                for context in services_to_stop:
                    future = executor.submit(self._graceful_stop_service, ocr_pool, context)
                    futures.append((future, context))
                
                # 等待优雅停止完成
                for future, context in futures:
                    try:
                        if future.result(timeout=graceful_timeout / len(services_to_stop)):
                            success_count += 1
                            context.state = OCRServiceState.STOPPED
                            context.stopped_at = time.time()
                            logger.debug(f"OCR服务优雅停止成功: {context.service_id}")
                        else:
                            context.state = OCRServiceState.STOPPING  # 继续尝试强制停止
                    except Exception as e:
                        logger.error(f"OCR服务优雅停止失败 {context.service_id}: {e}")
                        context.state = OCRServiceState.STOPPING
                        context.error_message = str(e)
            
            # 第二阶段：强制停止未完成的服务
            remaining_services = [ctx for ctx in services_to_stop 
                                if ctx.state == OCRServiceState.STOPPING]
            
            if remaining_services:
                logger.info(f"第二阶段：强制停止 {len(remaining_services)} 个OCR服务")
                for context in remaining_services:
                    try:
                        if self._force_stop_service(ocr_pool, context):
                            forced_count += 1
                            context.state = OCRServiceState.STOPPED
                            context.stopped_at = time.time()
                            logger.debug(f"OCR服务强制停止成功: {context.service_id}")
                        else:
                            failed_count += 1
                            context.state = OCRServiceState.ERROR
                            logger.error(f"OCR服务强制停止失败: {context.service_id}")
                    except Exception as e:
                        failed_count += 1
                        context.state = OCRServiceState.ERROR
                        context.error_message = str(e)
                        logger.error(f"OCR服务强制停止异常 {context.service_id}: {e}")
            
            # 第三阶段：清理服务池状态
            logger.info("第三阶段：清理OCR服务池状态")
            self._cleanup_pool_state(ocr_pool, services_to_stop)
            
        except Exception as e:
            logger.error(f"停止OCR服务流程失败: {e}", exc_info=True)
            failed_count = len(services_to_stop)
        
        finally:
            # 完成停止流程
            self._finalize_stop_process(start_time, success_count, forced_count, failed_count)
    
    def _graceful_stop_service(self, ocr_pool, context: OCRServiceStopContext) -> bool:
        """优雅停止单个OCR服务"""
        try:
            logger.debug(f"优雅停止OCR服务: {context.service_id}")
            
            # 标记服务为非活跃状态
            if hasattr(ocr_pool, 'ocr_services') and context.service_id in ocr_pool.ocr_services:
                service_instance = ocr_pool.ocr_services[context.service_id]
                service_instance.is_active = False
                
                # 如果有OCR服务实例，尝试清理
                if hasattr(service_instance, 'ocr_service') and service_instance.ocr_service:
                    # 等待当前请求完成
                    time.sleep(0.1)
                    
                    # 清理OCR服务资源
                    if hasattr(service_instance.ocr_service, 'cleanup'):
                        service_instance.ocr_service.cleanup()
                    elif hasattr(service_instance.ocr_service, 'shutdown'):
                        service_instance.ocr_service.shutdown()
            
            return True
            
        except Exception as e:
            logger.error(f"优雅停止OCR服务失败 {context.service_id}: {e}")
            return False
    
    def _force_stop_service(self, ocr_pool, context: OCRServiceStopContext) -> bool:
        """强制停止单个OCR服务"""
        try:
            logger.debug(f"强制停止OCR服务: {context.service_id}")
            
            # 直接从服务池中移除
            if hasattr(ocr_pool, '_remove_service'):
                ocr_pool._remove_service(context.service_id)
            elif hasattr(ocr_pool, 'remove_window_service'):
                ocr_pool.remove_window_service(context.window_hwnd)
            
            return True
            
        except Exception as e:
            logger.error(f"强制停止OCR服务失败 {context.service_id}: {e}")
            return False
    
    def _cleanup_pool_state(self, ocr_pool, stopped_services: List[OCRServiceStopContext]):
        """清理服务池状态"""
        try:
            # 清理窗口映射
            for context in stopped_services:
                if hasattr(ocr_pool, 'window_service_mapping'):
                    ocr_pool.window_service_mapping.pop(context.window_hwnd, None)
                
                # 从本地映射中移除
                with self._lock:
                    self._window_service_mapping.pop(context.window_hwnd, None)
                    # 保留停止上下文用于统计，但标记为已停止
            
            logger.debug(f"已清理 {len(stopped_services)} 个OCR服务的状态映射")
            
        except Exception as e:
            logger.error(f"清理OCR服务池状态失败: {e}")
    
    def _finalize_stop_process(self, start_time: float, success_count: int, 
                              forced_count: int, failed_count: int):
        """完成停止流程"""
        try:
            # 更新统计
            total_time = time.time() - start_time
            total_services = success_count + forced_count + failed_count
            
            self.stop_stats['total_services_stopped'] += total_services
            self.stop_stats['successful_stops'] += success_count
            self.stop_stats['forced_stops'] += forced_count
            self.stop_stats['failed_stops'] += failed_count
            
            # 更新平均停止时间
            if total_services > 0:
                current_avg = self.stop_stats['average_stop_time']
                total_stopped = self.stop_stats['total_services_stopped']
                self.stop_stats['average_stop_time'] = (
                    (current_avg * (total_stopped - total_services) + total_time) / total_stopped
                )
            
            # 生成结果消息
            if failed_count == 0:
                message = f"OCR服务停止完成 - 总计: {total_services}, 成功: {success_count}"
                if forced_count > 0:
                    message += f", 强制停止: {forced_count}"
                message += f", 耗时: {total_time:.1f}秒"
                logger.info(message)
            else:
                message = f"OCR服务停止部分失败 - 总计: {total_services}, 成功: {success_count}, 强制: {forced_count}, 失败: {failed_count}"
                logger.warning(message)
            
        finally:
            # 重置状态
            with self._lock:
                self._stop_in_progress = False
    
    def get_stop_status(self) -> Dict:
        """获取停止状态"""
        with self._lock:
            return {
                'stop_in_progress': self._stop_in_progress,
                'total_services': len(self._stop_contexts),
                'active_services': sum(1 for ctx in self._stop_contexts.values() 
                                     if ctx.state == OCRServiceState.ACTIVE),
                'stopping_services': sum(1 for ctx in self._stop_contexts.values() 
                                       if ctx.state == OCRServiceState.STOPPING),
                'stopped_services': sum(1 for ctx in self._stop_contexts.values() 
                                      if ctx.state == OCRServiceState.STOPPED),
                'error_services': sum(1 for ctx in self._stop_contexts.values() 
                                    if ctx.state == OCRServiceState.ERROR),
                'statistics': self.stop_stats.copy()
            }
    
    def cleanup(self):
        """清理管理器资源"""
        logger.info("清理OCR服务池停止管理器")
        
        with self._lock:
            self._stop_contexts.clear()
            self._window_service_mapping.clear()
            self._stop_in_progress = False


# 全局实例
_ocr_stop_manager = None
_manager_lock = threading.Lock()

def get_ocr_stop_manager() -> EnhancedOCRPoolStopManager:
    """获取全局OCR停止管理器实例"""
    global _ocr_stop_manager
    if _ocr_stop_manager is None:
        with _manager_lock:
            if _ocr_stop_manager is None:
                _ocr_stop_manager = EnhancedOCRPoolStopManager()
    return _ocr_stop_manager
