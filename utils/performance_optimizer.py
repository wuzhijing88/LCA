"""
性能优化配置模块
提供进程优先级提升、CPU亲和性设置等性能优化功能
"""

import os
import sys
import logging
import platform
from typing import Optional

logger = logging.getLogger(__name__)


class PerformanceOptimizer:
    """性能优化器"""

    def __init__(self):
        self.is_windows = platform.system() == 'Windows'
        self.psutil_available = False
        self.original_priority = None
        self.priority_elevated = False

        # 尝试导入psutil
        try:
            import psutil
            self.psutil = psutil
            self.psutil_available = True
            self.process = psutil.Process(os.getpid())
            logger.info("psutil已加载，性能优化功能可用")
        except ImportError:
            logger.warning("psutil未安装，部分性能优化功能不可用")
            logger.warning("安装命令: pip install psutil")

    def elevate_priority(self, priority_level: str = 'high') -> bool:
        """
        提升进程优先级

        Args:
            priority_level: 优先级级别
                - 'high': 高优先级（推荐用于回放）
                - 'realtime': 实时优先级（慎用，可能导致系统不稳定）
                - 'above_normal': 高于正常
                - 'normal': 正常（恢复默认）

        Returns:
            bool: 是否成功
        """
        if not self.psutil_available:
            logger.warning("无法提升进程优先级：psutil未安装")
            return False

        try:
            # 保存原始优先级
            if self.original_priority is None:
                self.original_priority = self.process.nice()

            if self.is_windows:
                # Windows优先级映射
                priority_map = {
                    'realtime': self.psutil.REALTIME_PRIORITY_CLASS,
                    'high': self.psutil.HIGH_PRIORITY_CLASS,
                    'above_normal': self.psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                    'normal': self.psutil.NORMAL_PRIORITY_CLASS,
                }

                priority_class = priority_map.get(priority_level, self.psutil.HIGH_PRIORITY_CLASS)
                self.process.nice(priority_class)

                priority_name = {
                    self.psutil.REALTIME_PRIORITY_CLASS: '实时',
                    self.psutil.HIGH_PRIORITY_CLASS: '高',
                    self.psutil.ABOVE_NORMAL_PRIORITY_CLASS: '高于正常',
                    self.psutil.NORMAL_PRIORITY_CLASS: '正常',
                }.get(priority_class, '未知')

                self.priority_elevated = (priority_level != 'normal')
                logger.info(f"进程优先级已设置为: {priority_name}")

                if priority_level == 'realtime':
                    logger.warning("⚠ 使用实时优先级可能导致系统响应变慢，请谨慎使用")

                return True

            else:
                # Linux/Mac使用nice值 (-20到19，越小优先级越高)
                nice_map = {
                    'high': -10,
                    'above_normal': -5,
                    'normal': 0,
                }
                nice_value = nice_map.get(priority_level, -10)
                self.process.nice(nice_value)

                self.priority_elevated = (priority_level != 'normal')
                logger.info(f"进程nice值已设置为: {nice_value}")
                return True

        except PermissionError:
            logger.error("提升进程优先级失败：权限不足")
            logger.error("请尝试以管理员身份运行程序")
            return False
        except Exception as e:
            logger.error(f"提升进程优先级失败: {e}")
            return False

    def restore_priority(self) -> bool:
        """恢复原始进程优先级"""
        if not self.psutil_available or self.original_priority is None:
            return False

        try:
            self.process.nice(self.original_priority)
            self.priority_elevated = False
            logger.info("进程优先级已恢复为默认值")
            return True
        except Exception as e:
            logger.error(f"恢复进程优先级失败: {e}")
            return False

    def set_cpu_affinity(self, cpu_cores: Optional[list] = None) -> bool:
        """
        设置CPU亲和性（绑定到特定CPU核心）

        Args:
            cpu_cores: CPU核心列表，如[0, 1]表示绑定到核心0和1
                      None表示使用所有核心

        Returns:
            bool: 是否成功
        """
        if not self.psutil_available:
            logger.warning("无法设置CPU亲和性：psutil未安装")
            return False

        try:
            if cpu_cores is None:
                # 使用所有核心
                cpu_cores = list(range(self.psutil.cpu_count()))

            self.process.cpu_affinity(cpu_cores)
            logger.info(f"CPU亲和性已设置: 核心{cpu_cores}")
            return True

        except AttributeError:
            logger.warning("当前平台不支持设置CPU亲和性")
            return False
        except Exception as e:
            logger.error(f"设置CPU亲和性失败: {e}")
            return False

    def get_system_info(self) -> dict:
        """获取系统性能信息"""
        info = {
            'platform': platform.system(),
            'cpu_count': os.cpu_count(),
        }

        if self.psutil_available:
            try:
                info.update({
                    'cpu_percent': self.psutil.cpu_percent(interval=0.1),
                    'memory_percent': self.psutil.virtual_memory().percent,
                    'process_priority': self.process.nice(),
                    'priority_elevated': self.priority_elevated,
                })
            except:
                pass

        return info

    def print_system_info(self):
        """打印系统性能信息"""
        info = self.get_system_info()

        logger.info("=" * 50)
        logger.info("系统性能信息")
        logger.info("=" * 50)
        logger.info(f"操作系统: {info.get('platform', '未知')}")
        logger.info(f"CPU核心数: {info.get('cpu_count', '未知')}")

        if 'cpu_percent' in info:
            logger.info(f"CPU使用率: {info['cpu_percent']:.1f}%")
            logger.info(f"内存使用率: {info['memory_percent']:.1f}%")
            logger.info(f"进程优先级: {info['process_priority']}")
            logger.info(f"优先级已提升: {'是' if info['priority_elevated'] else '否'}")

        logger.info("=" * 50)

    def optimize_for_recording(self):
        """针对录制场景的优化（不需要太高优先级）"""
        logger.info("应用录制优化配置...")
        # 录制不需要很高优先级，避免干扰其他程序
        success = self.elevate_priority('above_normal')
        if success:
            logger.info("✓ 录制优化配置应用成功")
        else:
            logger.warning("⚠ 录制优化配置应用失败，使用默认配置")

    def optimize_for_playback(self, aggressive: bool = False):
        """
        针对回放场景的优化（需要高优先级确保精度）

        Args:
            aggressive: 是否使用激进模式（仅在高负载环境推荐）
        """
        if not aggressive:
            # 默认模式：仅在高负载时才提升优先级
            if self.psutil_available:
                cpu_percent = self.psutil.cpu_percent(interval=0.1)
                mem_percent = self.psutil.virtual_memory().percent

                # 只有在系统负载较高时才提升优先级
                if cpu_percent > 30 or mem_percent > 70:
                    logger.info("检测到系统负载较高，应用回放优化...")
                    success = self.elevate_priority('high')
                    if success:
                        logger.info("✓ 回放优化配置应用成功（高负载模式）")
                    return
                else:
                    logger.info("系统负载低，使用标准优先级（避免过度优化）")
                    return
            else:
                logger.info("psutil不可用，跳过优先级优化")
                return
        else:
            # 激进模式：强制提升优先级
            logger.info("应用回放优化配置（激进模式）...")
            success = self.elevate_priority('high')
            if success:
                logger.info("✓ 回放优化配置应用成功")
                logger.info("  - 进程优先级: 高")
                logger.info("  - 预期效果: 降低延迟抖动，提升回放精度")
            else:
                logger.warning("⚠ 回放优化配置应用失败，使用默认配置")
                logger.warning("  提示: 如需提升优先级，请以管理员身份运行")

    def optimize_extreme(self):
        """
        极致性能优化（慎用）

        警告：
        - 使用实时优先级可能导致系统响应变慢
        - 仅在需要极致精度且系统资源充足时使用
        """
        logger.warning("⚠ 正在应用极致性能优化...")
        logger.warning("⚠ 这可能导致系统响应变慢，请确保你知道自己在做什么")

        success = self.elevate_priority('realtime')
        if success:
            logger.info("✓ 极致性能优化应用成功")
            logger.info("  - 进程优先级: 实时")
            logger.warning("  ⚠ 如果系统变慢，请结束程序")
        else:
            logger.error("✗ 极致性能优化应用失败")
            logger.info("  降级使用高优先级模式...")
            self.elevate_priority('high')


# 全局性能优化器实例
_global_optimizer: Optional[PerformanceOptimizer] = None


def get_global_optimizer() -> PerformanceOptimizer:
    """获取全局性能优化器实例"""
    global _global_optimizer
    if _global_optimizer is None:
        _global_optimizer = PerformanceOptimizer()
    return _global_optimizer


def apply_playback_optimizations():
    """应用回放性能优化（快捷函数）"""
    optimizer = get_global_optimizer()
    optimizer.optimize_for_playback()


def restore_default_priority():
    """恢复默认优先级（快捷函数）"""
    optimizer = get_global_optimizer()
    optimizer.restore_priority()
