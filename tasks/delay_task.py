# Revert to Class-based implementation for Delay task, inheriting object

import time
import random
import logging
from typing import Dict, Any, Optional, Tuple

# Task Class Definition
class DelayTask(object):
    """
    执行延迟操作的任务。
    可以配置为固定延迟或在指定范围内的随机延迟。
    """
    NODE_TYPE = "Delay" # Unique identifier for this task type

    def __init__(self, config=None):
        """
        初始化延迟任务。
        Args:
            config (dict, optional): 任务配置。
        """
        # No super().__init__() needed as we inherit from object
        self.delay_mode = 'fixed'
        self.fixed_delay = 1.0
        self.min_delay = 0.5
        self.max_delay = 2.0
        self.set_config(config or {}) # Apply initial config

    def run(self): # Changed from execute to run for potential consistency
        """执行延迟操作。"""
        delay_seconds = 0
        try:
            if self.delay_mode == 'fixed':
                delay_seconds = self.fixed_delay
                logging.info(f"执行固定延迟: {delay_seconds:.2f} 秒")
            elif self.delay_mode == 'random':
                if self.min_delay > self.max_delay:
                    logging.warning("随机延迟配置错误：最小值大于最大值，使用最小值。")
                    delay_seconds = self.min_delay
                else:
                    delay_seconds = random.uniform(self.min_delay, self.max_delay)
                logging.info(f"执行随机延迟 (范围 {self.min_delay:.2f}-{self.max_delay:.2f}): {delay_seconds:.2f} 秒")
            else:
                logging.warning(f"未知的延迟模式: {self.delay_mode}，不执行延迟。")
                return True # Treat unknown mode as non-fatal

            time.sleep(delay_seconds)
            logging.info("延迟执行完毕。")
            return True # Indicate success

        except Exception as e:
            logging.error(f"延迟任务执行期间发生错误: {e}", exc_info=True)
            return False # Indicate failure
            
    def get_config(self) -> dict:
        """返回当前配置。"""
        return {
            'delay_mode': self.delay_mode,
            'fixed_delay': self.fixed_delay,
            'min_delay': self.min_delay,
            'max_delay': self.max_delay,
        }

    def set_config(self, config: dict):
        """根据提供的字典更新配置。"""
        self.delay_mode = config.get('delay_mode', self.delay_mode)
        self.fixed_delay = float(config.get('fixed_delay', self.fixed_delay))
        self.min_delay = float(config.get('min_delay', self.min_delay))
        self.max_delay = float(config.get('max_delay', self.max_delay))
        logging.debug(f"DelayTask 配置已更新: {self.get_config()}")

    # --- Static methods for UI display --- 
    @staticmethod
    def get_display_name() -> str:
        return "等待 (延迟)"

    @staticmethod
    def get_category() -> str:
        return "流程控制"

    @staticmethod
    def get_description() -> str:
        return "暂停执行固定的秒数或一段随机时间。"

    @staticmethod
    def get_icon() -> str:
        return "mdi.timer-sand"

# --- Define get_params_definition at the MODULE level --- 
# --- It MUST remain at module level for TaskCard compatibility --- 
def get_params_definition() -> Dict[str, Any]:
    """返回此任务的参数定义，供 ParameterDialog 使用 (仅含延迟相关参数)。"""
    return {
        "delay_mode": {
            "label": "延迟模式",
            "type": "select",
            "options": ["固定延迟", "随机延迟"],
            "default": "固定延迟",
            "tooltip": "选择固定延迟时间还是随机延迟时间"
        },

        # 固定延迟参数
        "---fixed_delay_params---": {
            "type": "separator",
            "label": "固定延迟参数",
            "condition": {"param": "delay_mode", "value": "固定延迟"}
        },
        "fixed_delay": {
            "label": "固定延迟 (秒)",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置固定的延迟时间",
            "condition": {"param": "delay_mode", "value": "固定延迟"}
        },

        # 随机延迟参数
        "---random_delay_params---": {
            "type": "separator",
            "label": "随机延迟参数",
            "condition": {"param": "delay_mode", "value": "随机延迟"}
        },
        "min_delay": {
            "label": "最小延迟 (秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置随机延迟的最小值",
            "condition": {"param": "delay_mode", "value": "随机延迟"}
        },
        "max_delay": {
            "label": "最大延迟 (秒)",
            "type": "float",
            "default": 2.0,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置随机延迟的最大值",
            "condition": {"param": "delay_mode", "value": "随机延迟"}
        },
        # REMOVED Separator and Post-Execution Jump Parameters
    }

# Removed module-level execute function 

logger = logging.getLogger(__name__)
TASK_NAME = '延迟'

def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode='foreground', **kwargs) -> Tuple[bool, str, Optional[int]]:
    """Executes the delay task."""
    logger.info("开始执行延迟任务")

    # 获取停止检查器
    stop_checker = kwargs.get('stop_checker', None)

    delay_mode = params.get('delay_mode', 'fixed')
    
    # 支持中文值的映射
    mode_mapping = {
        '固定延迟': 'fixed',
        '随机延迟': 'random',
        'fixed': 'fixed',
        'random': 'random'
    }
    delay_mode = mode_mapping.get(delay_mode, delay_mode)
    
    # --- Explicitly convert parameters to float --- 
    try:
        fixed_delay = float(params.get('fixed_delay', 1.0))
        min_delay = float(params.get('min_delay', 0.5))
        max_delay = float(params.get('max_delay', 2.0))
    except (ValueError, TypeError) as e:
        logger.error(f"无效的延迟参数值: {params.get('fixed_delay')}, {params.get('min_delay')}, {params.get('max_delay')}. 错误: {e}")
        return False, '执行下一步', None # Treat as failure
    # ----------------------------------------------

    calculated_delay = 0.0 # Initialize calculated delay
    try:
        if delay_mode == 'fixed':
            calculated_delay = fixed_delay
            logger.info(f"执行固定延迟: {calculated_delay:.2f} 秒")
        elif delay_mode == 'random':
            if min_delay > max_delay:
                logger.warning("随机延迟配置错误：最小值大于最大值，使用最小值。")
                calculated_delay = min_delay
            else:
                calculated_delay = random.uniform(min_delay, max_delay)
            logger.info(f"执行随机延迟 (范围 {min_delay:.2f}-{max_delay:.2f}): {calculated_delay:.2f} 秒")
        else:
            logger.warning(f"未知的延迟模式: {delay_mode}，不执行延迟。")
            # Treat unknown mode as success, but no delay
            return True, '执行下一步', None 

        # --- ADDED: Store calculated delay in counters ---
        if 'card_id' in kwargs and kwargs['card_id'] is not None:
            card_id = kwargs['card_id']
            counters[f"__last_delay_{card_id}"] = calculated_delay
            logger.debug(f"存储卡片 {card_id} 的实际延迟: {calculated_delay:.4f} 秒到 counters")
        else:
            logger.warning("无法存储实际延迟时间，因为 execute_task 未收到 card_id。")
        # ------------------------------------------------

        # 可中断的延迟执行 - 使用高精度计时器避免累积误差
        if calculated_delay > 0:
            check_interval = 0.1  # 每100ms检查一次停止信号
            start_time = time.perf_counter()  # 使用高精度计时器
            last_log_second = -1

            logger.info(f"开始可中断延迟，总时长: {calculated_delay:.2f} 秒")

            while True:
                elapsed_time = time.perf_counter() - start_time

                # 检查是否已完成
                if elapsed_time >= calculated_delay:
                    break

                # 检查停止信号
                if stop_checker and stop_checker():
                    logger.info(f"延迟任务被用户中断，已延迟 {elapsed_time:.2f}/{calculated_delay:.2f} 秒")
                    return False, '停止工作流', None

                # 计算本次睡眠时间（基于实际剩余时间）
                remaining_time = calculated_delay - elapsed_time
                sleep_time = min(check_interval, remaining_time)

                time.sleep(sleep_time)

                # 每秒输出一次进度（可选）
                current_second = int(elapsed_time)
                if current_second != last_log_second and remaining_time > 1:
                    logger.debug(f"延迟进度: {elapsed_time:.1f}/{calculated_delay:.1f} 秒")
                    last_log_second = current_second

        logger.info("延迟执行完毕。")
        # Default success action is '执行下一步'
        return True, '执行下一步', None

    except TypeError as te:
        # Catch TypeError specifically, often related to sleep argument type
        logger.error(f"延迟任务执行期间发生类型错误 (可能是无效的延迟值: {calculated_delay}): {te}", exc_info=True)
        return False, '执行下一步', None 
    except Exception as e:
        logger.error(f"延迟任务执行期间发生错误: {e}", exc_info=True)
        # Default failure action is '执行下一步' (unless overridden by params, but Delay doesn't have them)
        return False, '执行下一步', None

# The function previously named execute is now execute_task

# Removed module-level execute function 