import logging
import time
import traceback

try:
    import win32con
    import win32gui
    PYWIN32_AVAILABLE = True
except ImportError:
    win32con = None
    win32gui = None
    PYWIN32_AVAILABLE = False

logger = logging.getLogger(__name__)


class MainWindowWindowBindingActivationMixin:

    def _activate_window_if_needed(self, hwnd: int, window_title: str):

        """根据执行模式和窗口状态决定是否激活窗口"""

        try:

            import win32gui

            import win32con

            import time

            logger.debug(f"_activate_window_if_needed 被调用，窗口: {window_title}")

            # 获取当前执行模式

            execution_mode = self.current_execution_mode

            # 检查是否为子窗口，如果是则检查父窗口的状态

            parent_hwnd = win32gui.GetParent(hwnd)

            target_hwnd = parent_hwnd if parent_hwnd else hwnd

            logger.info(f"检测窗口状态 - 目标窗口HWND: {hwnd}, 父窗口HWND: {parent_hwnd}, 检测状态的窗口: {target_hwnd}")

            # 检查窗口是否最小化（检查父窗口或顶级窗口）

            placement = win32gui.GetWindowPlacement(target_hwnd)

            is_minimized = placement[1] == win32con.SW_SHOWMINIMIZED

            # 检查窗口是否可见

            is_visible = win32gui.IsWindowVisible(target_hwnd)

            # 获取窗口状态的详细信息

            window_state = placement[1]

            state_names = {

                win32con.SW_HIDE: "隐藏",

                win32con.SW_SHOWNORMAL: "正常显示",

                win32con.SW_SHOWMINIMIZED: "最小化",

                win32con.SW_SHOWMAXIMIZED: "最大化",

                win32con.SW_SHOWNOACTIVATE: "显示但不激活",

                win32con.SW_SHOW: "显示",

                win32con.SW_MINIMIZE: "最小化",

                win32con.SW_SHOWMINNOACTIVE: "最小化但不激活",

                win32con.SW_SHOWNA: "显示但不激活",

                win32con.SW_RESTORE: "恢复"

            }

            state_name = state_names.get(window_state, f"未知状态({window_state})")

            logger.info(f"窗口状态检查 - {window_title}:")

            logger.info(f"  执行模式: {execution_mode}")

            logger.info(f"  窗口状态: {state_name}")

            logger.info(f"  是否最小化: {is_minimized}")

            logger.info(f"  是否可见: {is_visible}")

            should_activate = False

            reason = ""

            # 标准化执行模式

            normalized_mode = normalize_execution_mode(execution_mode)

            if normalized_mode == 'foreground':

                # 前台模式总是激活窗口

                should_activate = True

                reason = "前台模式需要激活窗口"

            elif normalized_mode == 'background':

                if is_minimized:

                    # 后台模式下，如果窗口最小化则需要激活

                    should_activate = True

                    reason = "窗口处于最小化状态，需要激活"

                else:

                    # 后台模式下，窗口正常显示则不激活

                    should_activate = False

                    reason = "后台模式且窗口正常显示，不需要激活"

            else:

                logger.warning(f"未识别的执行模式: {execution_mode}")

                should_activate = False

                reason = f"未识别的执行模式: {execution_mode}"

            logger.info(f"激活决策: {should_activate} - {reason}")

            if should_activate:

                logger.info(f"开始激活窗口: {window_title}")

                # 如果窗口最小化，先恢复窗口（恢复父窗口或顶级窗口）

                if is_minimized:

                    logger.info(f"窗口已最小化，正在恢复...")

                    win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)

                    logger.info(f"已发送恢复命令到窗口: {target_hwnd}")

                    # 等待窗口恢复

                    time.sleep(0.2)

                    # 验证窗口是否已恢复

                    new_placement = win32gui.GetWindowPlacement(target_hwnd)

                    new_state = new_placement[1]

                    new_state_name = state_names.get(new_state, f'未知({new_state})')

                    logger.info(f"恢复后窗口状态: {new_state_name}")

                # 激活窗口（激活父窗口或顶级窗口）

                logger.info(f"正在激活窗口: {target_hwnd}...")

                try:

                    win32gui.SetForegroundWindow(target_hwnd)

                    logger.info(f"窗口激活命令已发送: {window_title} (HWND: {target_hwnd})")

                except Exception as activate_error:

                    logger.error(f"激活窗口失败: {activate_error}")

                    # 尝试备用方法

                    try:

                        win32gui.BringWindowToTop(target_hwnd)

                        logger.info(f"使用备用方法将窗口置顶: {window_title} (HWND: {target_hwnd})")

                    except Exception as backup_error:

                        logger.error(f"备用激活方法也失败: {backup_error}")

            else:

                logger.info(f"不激活窗口: {window_title} - {reason}")

        except Exception as e:

            logger.error(f"激活窗口时出错: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _check_window_activation_after_settings_update(self):

        """在全局设置更新后检查是否需要激活窗口"""

        # 工具 修复：禁用设置更新后的自动窗口激活，避免干扰用户操作

        logger.info("全局设置更新完成，跳过自动窗口激活以避免干扰用户")

        return

        # 以下代码已禁用，只在实际执行任务时才激活窗口

        try:

            if self.window_binding_mode == 'single':

                # 单窗口模式：检查目标窗口

                if self.current_target_window_title:

                    hwnd = self._find_window_by_title(self.current_target_window_title)

                    if hwnd:

                        logger.info(f"全局设置更新后检查窗口激活: {self.current_target_window_title}")

                        self._activate_window_if_needed(hwnd, self.current_target_window_title)

            elif self.window_binding_mode == 'multiple':

                # 多窗口模式：检查所有绑定的窗口

                for window_info in self.bound_windows:

                    if window_info.get('enabled', True):

                        hwnd = window_info.get('hwnd')

                        window_title = window_info.get('title', '')

                        if hwnd and window_title:

                            logger.info(f"全局设置更新后检查窗口激活: {window_title}")

                            self._activate_window_if_needed(hwnd, window_title)

        except Exception as e:

            logger.error(f"检查窗口激活时出错: {e}")
