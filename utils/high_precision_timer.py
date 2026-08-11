"""
高精度计时器模块
提供微秒级精度的计时和sleep功能，用于优化录制回放系统
"""

import time
import ctypes
import platform
import logging
from collections import deque
from typing import Callable, Optional
from utils.precise_sleep import precise_sleep as _shared_precise_sleep

logger = logging.getLogger(__name__)


class HighPrecisionTimer:
    """高精度计时器类，提供比time.time()和time.sleep()更高的精度"""

    def __init__(self):
        self.is_windows = platform.system() == 'Windows'
        self._timer_resolution_set = False

        if self.is_windows:
            try:
                # 加载 winmm.dll 用于高精度多媒体计时器
                self.winmm = ctypes.windll.winmm
                # 设置系统计时器分辨率为1ms (默认是15-16ms)
                result = self.winmm.timeBeginPeriod(1)
                if result == 0:  # TIMERR_NOERROR
                    self._timer_resolution_set = True
                    logger.info("Windows高精度计时器已启用 (1ms分辨率)")
                else:
                    logger.warning(f"无法设置高精度计时器分辨率: {result}")
            except Exception as e:
                logger.warning(f"初始化高精度计时器失败: {e}")

    def __del__(self):
        """清理资源"""
        if self.is_windows and self._timer_resolution_set:
            try:
                self.winmm.timeEndPeriod(1)
                logger.debug("Windows高精度计时器已关闭")
            except:
                pass

    @staticmethod
    def get_time() -> float:
        """
        获取高精度时间戳
        使用 time.perf_counter() 提供微秒级精度

        Returns:
            float: 高精度时间戳（秒），适用于计时
        """
        return time.perf_counter()

    def precise_sleep(self, duration: float, busy_wait_threshold: float = 0.002):
        """
        高精度sleep函数

        对于较长的延迟使用time.sleep()，最后2ms使用busy-wait确保精度

        Args:
            duration: 延迟时间（秒）
            busy_wait_threshold: 使用busy-wait的阈值（秒），默认2ms
        """
        _shared_precise_sleep(duration, spin_threshold=busy_wait_threshold)

    def sleep_until(self, target_time: float, busy_wait_threshold: float = 0.002):
        """
        睡眠直到指定的目标时间

        Args:
            target_time: 目标时间戳（使用get_time()获取）
            busy_wait_threshold: 使用busy-wait的阈值（秒）
        """
        now = self.get_time()
        delay = target_time - now

        if delay > 0:
            self.precise_sleep(delay, busy_wait_threshold)

        return self.get_time()



class PerformanceMonitor:
    """性能监控器，用于分析回放精度"""

    MAX_TIMING_ERRORS = 20000

    def __init__(self):
        self.timer = HighPrecisionTimer()
        self.timing_errors = deque(maxlen=self.MAX_TIMING_ERRORS)
        self.max_error = 0.0
        self.total_actions = 0

    def record_timing_error(self, expected_time: float, actual_time: float):
        """记录时间误差"""
        error = abs(actual_time - expected_time)
        self.timing_errors.append(error)
        self.max_error = max(self.max_error, error)
        self.total_actions += 1

    def get_statistics(self) -> dict:
        """获取统计信息"""
        if not self.timing_errors:
            return {
                'total_actions': 0,
                'avg_error_ms': 0,
                'max_error_ms': 0,
                'std_dev_ms': 0
            }

        avg_error = sum(self.timing_errors) / len(self.timing_errors)

        # 计算标准差
        variance = sum((e - avg_error) ** 2 for e in self.timing_errors) / len(self.timing_errors)
        std_dev = variance ** 0.5

        return {
            'total_actions': self.total_actions,
            'avg_error_ms': avg_error * 1000,
            'max_error_ms': self.max_error * 1000,
            'std_dev_ms': std_dev * 1000,
            'errors_gt_1ms': sum(1 for e in self.timing_errors if e > 0.001),
            'errors_gt_10ms': sum(1 for e in self.timing_errors if e > 0.01),
            'errors_gt_100ms': sum(1 for e in self.timing_errors if e > 0.1),
        }

    def print_report(self):
        """打印性能报告"""
        stats = self.get_statistics()
        logger.info("=" * 50)
        logger.info("回放精度统计报告")
        logger.info("=" * 50)
        logger.info(f"总操作数: {stats['total_actions']}")
        logger.info(f"平均误差: {stats['avg_error_ms']:.3f}ms")
        logger.info(f"最大误差: {stats['max_error_ms']:.3f}ms")
        logger.info(f"标准差: {stats['std_dev_ms']:.3f}ms")
        if 'errors_gt_1ms' in stats:
            logger.info(f"误差>1ms: {stats['errors_gt_1ms']} ({stats['errors_gt_1ms']/stats['total_actions']*100:.1f}%)")
            logger.info(f"误差>10ms: {stats['errors_gt_10ms']} ({stats['errors_gt_10ms']/stats['total_actions']*100:.1f}%)")
            logger.info(f"误差>100ms: {stats['errors_gt_100ms']} ({stats['errors_gt_100ms']/stats['total_actions']*100:.1f}%)")
        logger.info("=" * 50)


# 创建全局计时器实例
_global_timer = None

