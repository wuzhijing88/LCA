import logging
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)


class MainWindowTimerRuntimeMixin:
    def _is_schedule_interval_mode(self) -> bool:

        return str(getattr(self, '_schedule_mode', 'fixed_time') or '').strip().lower() == 'interval'

    def _get_schedule_interval_seconds(self) -> int:

        try:

            value = max(1, int(getattr(self, '_schedule_interval_value', 5) or 5))

        except (TypeError, ValueError):

            value = 5

        unit = str(getattr(self, '_schedule_interval_unit', '分钟') or '').strip()

        if unit == '小时':

            return value * 3600

        if unit == '分钟':

            return value * 60

        return value

    def _format_schedule_interval_text(self) -> str:

        value = getattr(self, '_schedule_interval_value', 5)

        unit = str(getattr(self, '_schedule_interval_unit', '分钟') or '').strip() or '分钟'

        return f"{value}{unit}"

    def _reset_schedule_next_trigger(self) -> None:

        self._schedule_next_trigger_monotonic = None

        if not self._schedule_enabled or not self._is_schedule_interval_mode():

            return

        self._schedule_next_trigger_monotonic = time.monotonic() + self._get_schedule_interval_seconds()

    def _has_active_workflow_execution(self) -> bool:

        if bool(getattr(self, '_is_paused', False)):

            return True

        task_state_manager = getattr(self, 'task_state_manager', None)

        if task_state_manager is not None:

            try:

                if bool(task_state_manager.is_running()):

                    return True

            except Exception as exc:

                logger.warning(f"[定时启动] 读取任务状态失败: {exc}")

        task_manager = getattr(self, 'task_manager', None)

        if task_manager is None:

            return False

        try:

            for task in task_manager.get_all_tasks():

                if getattr(task, 'status', None) in ('running', 'paused'):

                    return True

        except Exception as exc:

            logger.warning(f"[定时启动] 遍历任务状态失败: {exc}")

        return False

    def _on_global_timer_timeout(self):

        """全局定时器超时处理"""

        logger.info("全局定时器超时")

        # 先停止定时器,防止重复触发

        self._global_timer.stop()

        # 如果启用了定时停止，则停止所有任务

        if self._global_timer_enabled:

            logger.info("定时停止已启用，自动停止所有工作流")

            self._global_timer_enabled = False

            # 停止随机暂停定时器

            if self._random_pause_timer.isActive():

                self._random_pause_timer.stop()

            if hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive():

                self._timed_pause_timer.stop()

            if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():

                self._timed_pause_resume_timer.stop()

            self._random_pause_enabled = False

            self._timed_pause_enabled = False

            self._auto_pause_source = None

            # 停止所有任务

            self._stop_all_tasks()

        else:

            logger.info("定时停止未启用，不停止工作流")

        # 显示定时停止提示

        QMessageBox.information(self, "定时器到时", "定时时间已到,所有工作流已自动停止")

    def _can_execute_timer_action(self, action_name: str, now) -> bool:

        """同一分钟内按优先级仲裁定时动作，避免冲突。"""

        priority_map = {

            'schedule': 1,

            'timed_pause': 2,

            'stop': 3

        }

        action_priority = priority_map.get(action_name, 0)

        current_slot_key = (now.date(), now.hour, now.minute)

        if self._timer_slot_key != current_slot_key:

            self._timer_slot_key = current_slot_key

            self._timer_slot_priority = -1

            self._timer_slot_action = None

        if self._timer_slot_priority >= action_priority:

            return False

        self._timer_slot_priority = action_priority

        self._timer_slot_action = action_name

        return True

    def _check_schedule_time(self):

        """检查是否到达定时启动时间"""

        if not self._schedule_enabled:

            return

        from datetime import datetime

        now = datetime.now()

        if self._is_schedule_interval_mode():

            self._check_schedule_interval(now)

            return

        current_hour = now.hour

        current_minute = now.minute

        today = now.date()

        # 每日模式下，跨天后重置执行标记

        if self._schedule_repeat == 'daily' and self._schedule_executed:

            if self._schedule_last_exec_date is not None and self._schedule_last_exec_date != today:

                self._schedule_executed = False

                logger.info("[定时启动] 跨日重置执行标记，准备下次执行")

        # 检查是否到达设定时间

        if current_hour == self._schedule_hour and current_minute == self._schedule_minute:

            # 检查今天是否已经执行过

            if not self._schedule_executed:

                if not self._can_execute_timer_action('schedule', now):

                    return

                self._schedule_executed = True

                self._schedule_last_exec_date = today  # 记录执行日期

                if self._has_active_workflow_execution():

                    logger.info(

                        f"[定时启动] 到达定时启动时间 {self._schedule_hour:02d}:{self._schedule_minute:02d}，当前工作流正在执行，跳过本次触发"

                    )

                else:

                    logger.info(f"[定时启动] 到达定时启动时间 {self._schedule_hour:02d}:{self._schedule_minute:02d}，开始执行工作流")

                    try:

                        self.safe_start_tasks()

                    except Exception as e:

                        logger.error(f"定时启动工作流失败: {e}")

                        import traceback

                        logger.error(traceback.format_exc())

                # 如果是仅一次模式，执行后禁用定时功能

                if self._schedule_repeat == 'once':

                    logger.info("定时任务为'仅一次'模式，执行后自动禁用")

                    self._schedule_enabled = False

                    self._schedule_timer.stop()

                    self._schedule_next_trigger_monotonic = None

    def _check_schedule_interval(self, now):

        deadline = getattr(self, '_schedule_next_trigger_monotonic', None)

        if deadline is None:

            self._reset_schedule_next_trigger()

            return

        if time.monotonic() < deadline:

            return

        if not self._can_execute_timer_action('schedule', now):

            self._reset_schedule_next_trigger()

            return

        self._reset_schedule_next_trigger()

        if self._has_active_workflow_execution():

            logger.info(f"[定时启动] 到达间隔触发时间（每隔 {self._format_schedule_interval_text()}），当前工作流正在执行，跳过本次触发")

            return

        logger.info(f"[定时启动] 到达间隔触发时间（每隔 {self._format_schedule_interval_text()}），开始执行工作流")

        try:

            self.safe_start_tasks()

        except Exception as e:

            logger.error(f"定时启动工作流失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _start_schedule_timer(self):

        """启动定时检查定时器"""

        if self._schedule_enabled and not self._schedule_timer.isActive():

            if self._is_schedule_interval_mode() and getattr(self, '_schedule_next_trigger_monotonic', None) is None:

                self._reset_schedule_next_trigger()

            # 每1秒检查一次时间，确保准时触发

            self._schedule_timer.start(1000)

            if self._is_schedule_interval_mode():

                logger.info(f"定时启动功能已启用，将每隔 {self._format_schedule_interval_text()} 尝试执行一次，执行中自动跳过")

            else:

                logger.info(f"定时启动功能已启用，将在 {self._schedule_hour:02d}:{self._schedule_minute:02d} 执行，重复模式: {self._schedule_repeat}")

    def _stop_schedule_timer(self):

        """停止定时检查定时器"""

        if self._schedule_timer.isActive():

            self._schedule_timer.stop()

            logger.info("定时启动功能已停止")

    def _update_schedule_config(self):

        """根据当前设置更新定时启动定时器"""

        # 重启定时器以应用新配置

        self._stop_schedule_timer()

        # 重置执行标记，允许新配置立即生效

        self._schedule_executed = False

        self._schedule_last_exec_date = None

        self._reset_schedule_next_trigger()

        if self._schedule_enabled:

            self._start_schedule_timer()

        if self._is_schedule_interval_mode():

            logger.info(f"定时设置已更新: 启用={self._schedule_enabled}, 模式=interval, 间隔={self._format_schedule_interval_text()}")

        else:

            logger.info(

                f"定时设置已更新: 启用={self._schedule_enabled}, 模式=fixed_time, 时间={self._schedule_hour:02d}:{self._schedule_minute:02d}, 重复={self._schedule_repeat}"

            )

    def _start_timed_pause_timer(self):

        """启动定时暂停检查定时器"""

        if self._timed_pause_enabled and not self._timed_pause_timer.isActive():

            self._timed_pause_timer.start(1000)

            logger.info(

                f"定时暂停功能已启用，将在 {self._timed_pause_hour:02d}:{self._timed_pause_minute:02d} 暂停，"

                f"持续 {self._timed_pause_duration_value}{self._timed_pause_duration_unit}，重复模式: {self._timed_pause_repeat}"

            )

    def _stop_timed_pause_timer(self):

        """停止定时暂停检查定时器"""

        if hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive():

            self._timed_pause_timer.stop()

            logger.info("定时暂停功能已停止")

    def _update_timed_pause_config(self):

        """根据当前设置更新定时暂停定时器"""

        self._stop_timed_pause_timer()

        self._timed_pause_executed = False

        if self._timed_pause_enabled:

            self._start_timed_pause_timer()

        logger.info(

            f"定时暂停设置已更新: 启用={self._timed_pause_enabled}, "

            f"时间={self._timed_pause_hour:02d}:{self._timed_pause_minute:02d}, "

            f"时长={self._timed_pause_duration_value}{self._timed_pause_duration_unit}, "

            f"重复={self._timed_pause_repeat}"

        )

    def _check_timed_pause_time(self):

        """检查是否到达定时暂停时间"""

        if not self._timed_pause_enabled:

            return

        from datetime import datetime

        now = datetime.now()

        current_hour = now.hour

        current_minute = now.minute

        today = now.date()

        if self._timed_pause_repeat == 'daily' and self._timed_pause_executed:

            if self._timed_pause_last_exec_date is not None and self._timed_pause_last_exec_date != today:

                self._timed_pause_executed = False

                logger.info("[定时暂停] 跨日重置执行标记，准备下次执行")

        if current_hour == self._timed_pause_hour and current_minute == self._timed_pause_minute:

            if self._timed_pause_executed:

                return

            triggered = False

            try:

                if self._is_paused:

                    logger.info("[定时暂停] 当前已经处于暂停状态，跳过本次触发")

                else:

                    running_count = 0

                    if hasattr(self, 'task_manager') and self.task_manager:

                        running_count = self.task_manager.get_running_count()

                    if running_count <= 0:

                        logger.info("[定时暂停] 当前没有运行中的任务，跳过本次触发")

                    else:

                        if not self._can_execute_timer_action('timed_pause', now):

                            return

                        self._trigger_timed_pause()

                        triggered = True

            except Exception as e:

                logger.error(f"[定时暂停] 触发失败: {e}")

            if triggered:

                self._timed_pause_executed = True

                self._timed_pause_last_exec_date = today

            if triggered and self._timed_pause_repeat == 'once':

                self._timed_pause_enabled = False

                self._timed_pause_timer.stop()

                logger.info("[定时暂停] 仅一次模式执行完成，定时器已停止")

    def _trigger_timed_pause(self):

        """触发定时暂停"""

        duration_sec = 0

        try:

            if self._timed_pause_duration_unit == "小时":

                duration_sec = int(self._timed_pause_duration_value) * 3600

            elif self._timed_pause_duration_unit == "分钟":

                duration_sec = int(self._timed_pause_duration_value) * 60

            else:

                duration_sec = int(self._timed_pause_duration_value)

        except Exception:

            duration_sec = 0

        duration_sec = max(1, duration_sec)

        logger.info(f"[定时暂停] 开始暂停，时长: {duration_sec} 秒")

        self._pause_workflow()

        self._is_paused = True

        self._auto_pause_source = 'timed'

        if hasattr(self, '_timed_pause_resume_timer'):

            if self._timed_pause_resume_timer.isActive():

                self._timed_pause_resume_timer.stop()

            duration_ms = duration_sec * 1000

            max_qtimer_ms = 2147483647  # QTimer 支持的安全上限（约24.8天）

            if duration_ms > max_qtimer_ms:

                duration_ms = max_qtimer_ms

                logger.warning("[定时暂停] 时长超过QTimer上限，已自动截断到最大可用值")

            self._timed_pause_resume_timer.start(duration_ms)

        logger.info(f"[定时暂停] 已暂停，将在 {duration_sec} 秒后自动恢复")

    def _on_timed_pause_resume_timeout(self):

        """定时暂停恢复回调"""

        if self._is_paused and getattr(self, '_auto_pause_source', None) == 'timed':

            logger.info("[定时暂停] 恢复定时器触发，恢复工作流")

            self._resume_workflow()

            self._is_paused = False

            self._auto_pause_source = None

    def _check_stop_time(self):

        """检查是否到达定时停止时间"""

        if not self._global_timer_enabled:

            return

        from datetime import datetime

        now = datetime.now()

        current_hour = now.hour

        current_minute = now.minute

        today = now.date()

        # 每日模式下，跨天后重置执行标记

        if self._stop_repeat == 'daily' and self._stop_executed:

            if self._stop_last_exec_date is not None and self._stop_last_exec_date != today:

                self._stop_executed = False

                logger.info("[定时停止] 跨日重置执行标记，准备下次执行")

        # 检查是否到达停止时间

        if current_hour == self._stop_hour and current_minute == self._stop_minute:

            if not self._stop_executed:

                if not self._can_execute_timer_action('stop', now):

                    return

                logger.info(f"[定时停止] 到达定时停止时间 {self._stop_hour:02d}:{self._stop_minute:02d}，停止工作流")

                self._stop_executed = True

                self._stop_last_exec_date = today  # 记录执行日期

                self.safe_stop_tasks()

                # 如果是仅一次，停止定时器

                if self._stop_repeat == 'once':

                    self._global_timer_enabled = False

                    self._stop_timer.stop()

                    logger.info("[定时停止] 仅一次模式执行完成，定时器已停止")

            else:

                # 在同一分钟内多次检查时，只记录第一次

                pass

    def _update_stop_config(self):

        """根据当前设置更新定时停止定时器"""

        # 重启定时器以应用新配置

        self._stop_timer.stop()

        # 重置执行标记，允许新配置立即生效

        self._stop_executed = False

        if self._global_timer_enabled:

            # 每1秒检查一次时间，确保准时触发

            self._stop_timer.start(1000)

            logger.info(f"定时停止功能已启用，将在 {self._stop_hour:02d}:{self._stop_minute:02d} 停止，重复模式: {self._stop_repeat}")

        else:

            logger.info("定时停止功能已禁用")

    def _start_random_pause_cycle(self):

        """启动随机暂停检查循环"""

        logger.info(f"[随机暂停] _start_random_pause_cycle 被调用, enabled={self._random_pause_enabled}")

        if not self._random_pause_enabled:

            logger.info("[随机暂停] 未启用，不启动定时器")

            return

        # 计算检查间隔(毫秒)

        def convert_to_milliseconds(value: int, unit: str) -> int:

            if unit == "分钟":

                return value * 60 * 1000

            else:  # 秒

                return value * 1000

        interval_ms = convert_to_milliseconds(self._pause_check_interval, self._pause_check_interval_unit)

        # 启动定时检查

        self._random_pause_timer.stop()

        self._random_pause_timer.start(interval_ms)

        logger.info(f"[随机暂停] 定时器已启动: 间隔={interval_ms}ms ({self._pause_check_interval} {self._pause_check_interval_unit}), 概率={self._pause_probability}%")

        logger.info(f"[随机暂停] 定时器状态: isActive={self._random_pause_timer.isActive()}")

    def _on_random_pause_check(self):

        """随机暂停检查 - 每隔一段时间检查是否触发暂停"""

        import random as rand

        logger.info(f"[随机暂停] 检查触发: enabled={self._random_pause_enabled}, is_paused={self._is_paused}")

        if not self._random_pause_enabled or self._is_paused:

            logger.info(f"[随机暂停] 跳过: enabled={self._random_pause_enabled}, is_paused={self._is_paused}")

            return

        # 检查是否有任务正在运行

        running_count = 0

        if hasattr(self, 'task_manager') and self.task_manager:

            running_count = self.task_manager.get_running_count()

        logger.info(f"[随机暂停] 运行中任务数: {running_count}")

        if running_count == 0:

            logger.info("[随机暂停] 没有运行中的任务，跳过")

            return

        # 概率为0时不触发

        if self._pause_probability <= 0:

            logger.info("[随机暂停] 概率为0，跳过")

            return

        # 根据概率决定是否暂停

        # rand.randint(1, 100) 生成1-100的随机数，概率计算：roll <= threshold

        roll = rand.randint(1, 100)

        logger.info(f"[随机暂停] 概率检查: roll={roll}/100, 阈值={self._pause_probability}%")

        if roll <= self._pause_probability:

            logger.info(f"[随机暂停] 触发! ({roll} <= {self._pause_probability})")

            self._trigger_random_pause()

        else:

            logger.info(f"[随机暂停] 未触发 ({roll} > {self._pause_probability})")

    def _trigger_random_pause(self):

        """触发随机暂停"""

        import random as rand

        # 计算暂停时长(秒)

        def convert_to_seconds(value: int, unit: str) -> int:

            if unit == "分钟":

                return value * 60

            elif unit == "小时":

                return value * 3600

            else:

                return value

        pause_min_sec = convert_to_seconds(self._pause_min_value, self._pause_min_unit)

        pause_max_sec = convert_to_seconds(self._pause_max_value, self._pause_max_unit)

        # 随机生成暂停时长

        pause_duration = rand.randint(pause_min_sec, pause_max_sec)

        logger.info(f"开始随机暂停，暂停时长: {pause_duration} 秒")

        # 暂停所有任务（使用与主窗口按钮一致的方法）

        self._pause_workflow()

        self._is_paused = True

        self._auto_pause_source = 'random'

        # 设置恢复定时器

        QTimer.singleShot(pause_duration * 1000, self._on_random_resume_timeout)

        logger.info(f"工作流已暂停，将在 {pause_duration} 秒后恢复")

    def _on_random_resume_timeout(self):

        """恢复定时器超时 - 恢复任务"""

        # 无论随机暂停是否被禁用，都需要恢复任务（因为任务已被暂停）

        if self._is_paused and getattr(self, '_auto_pause_source', None) == 'random':

            logger.info("恢复定时器触发，恢复所有工作流")

            # 使用与主窗口按钮一致的方法恢复

            self._resume_workflow()

            self._is_paused = False

            self._auto_pause_source = None

            if not self._random_pause_enabled:

                logger.info("随机暂停已禁用，不再继续检查循环")

            else:

                logger.info("工作流已恢复，继续随机暂停检查循环")

    def _pause_all_tasks(self):

        """暂停所有任务"""

        try:
            from .main_window_pause_controller import pause_main_window_workflow
            pause_main_window_workflow(self, source='timer')

        except Exception as e:

            logger.error(f"暂停任务时出错: {e}")

    def _resume_all_tasks(self):

        """恢复所有任务"""

        try:
            from .main_window_pause_controller import resume_main_window_workflow
            resume_main_window_workflow(self, source='timer')

        except Exception as e:

            logger.error(f"恢复任务时出错: {e}")
