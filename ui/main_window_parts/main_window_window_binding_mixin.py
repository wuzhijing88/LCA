import logging
from utils.window.window_finder import (
    find_all_exact_window_hwnds,
    find_window_with_parent_info,
    resolve_exact_window_match,
    sanitize_window_lookup_title,
)
from utils.window.window_binding_utils import (
    get_active_target_window_title,
    get_native_bound_windows,
    get_window_binding_mode,
    sync_runtime_window_binding_state,
)
from utils.window.window_identity import match_bound_window, refresh_bound_windows
from .main_window_support import normalize_execution_mode

logger = logging.getLogger(__name__)
try:
    import win32gui
    PYWIN32_AVAILABLE = True
except ImportError:
    win32gui = None
    PYWIN32_AVAILABLE = False
try:
    import win32con
    import win32gui
    PYWIN32_AVAILABLE = True
except ImportError:
    win32con = None
    win32gui = None
    PYWIN32_AVAILABLE = False

class MainWindowWindowBindingMixin:

    def _apply_multi_window_resize(self):
        """应用多窗口分辨率调整（使用通用窗口管理器）"""
        try:
            logger.debug("开始多窗口分辨率调整")
            target_client_width = self.custom_width
            target_client_height = self.custom_height
            if target_client_width <= 0 or target_client_height <= 0:
                logging.info("未配置自定义分辨率，跳过多窗口大小调整。")
                return
            # 工具 修复：安全检查绑定窗口
            if not hasattr(self, 'bound_windows') or not self.bound_windows:
                logging.warning("没有绑定窗口，跳过多窗口大小调整。")
                return
            # 获取所有启用的绑定窗口
            enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]
            if not enabled_windows:
                logging.warning("没有启用的绑定窗口，跳过多窗口大小调整。")
                return
            logger.debug(f"准备调整 {len(enabled_windows)} 个窗口的分辨率")
        except Exception as init_error:
            logger.error(f"多窗口分辨率调整初始化失败: {init_error}", exc_info=True)
            return
        try:
            # 工具 修复：安全导入和初始化通用分辨率适配器
            logger.debug("导入通用分辨率适配器")
            from utils.universal_resolution_adapter import get_universal_adapter
            logger.debug("获取适配器实例")
            adapter = get_universal_adapter()
            # 调试：打印窗口信息和检查句柄重复
            logging.info("调试：多窗口调整前的窗口状态:")
            # 检查句柄重复
            hwnd_count = {}
            for i, window_info in enumerate(enabled_windows):
                hwnd = window_info.get('hwnd')
                title = window_info.get('title', '未知窗口')
                if hwnd:
                    hwnd_count[hwnd] = hwnd_count.get(hwnd, 0) + 1
                    debug_info = adapter.debug_window_info(hwnd)
                    logging.info(f"  窗口 {i+1}: {title}")
                    logging.info(f"    HWND: {hwnd}")
                    logging.info(f"    类名: {debug_info.get('class_name', 'N/A')}")
                    logging.info(f"    客户区尺寸: {debug_info.get('client_size', 'N/A')}")
                    logging.info(f"    窗口尺寸: {debug_info.get('window_size', 'N/A')}")
                    logging.info(f"    可见: {debug_info.get('is_visible', 'N/A')}")
                    logging.info(f"    启用: {debug_info.get('is_enabled', 'N/A')}")
                else:
                    logging.warning(f"  窗口 {i+1}: {title} - 无有效句柄")
            # 报告句柄重复情况
            duplicate_hwnds = [hwnd for hwnd, count in hwnd_count.items() if count > 1]
            if duplicate_hwnds:
                logging.error(f"发现重复的窗口句柄: {duplicate_hwnds}")
                for hwnd in duplicate_hwnds:
                    logging.error(f"  句柄 {hwnd} 被 {hwnd_count[hwnd]} 个窗口使用")
            else:
                logging.info("所有窗口句柄都是唯一的")
            # 使用通用窗口管理器批量调整窗口（异步模式）
            from utils.window.universal_window_manager import get_universal_window_manager
            window_manager = get_universal_window_manager()
            results = []
            for window_info in enabled_windows:
                hwnd = window_info.get('hwnd')
                if hwnd:
                    # 每个窗口使用异步调整
                    result = window_manager.adjust_single_window(
                        hwnd, target_client_width, target_client_height, async_mode=True
                    )
                    results.append(result)
            # 生成调整报告
            report = window_manager.create_adjustment_report(results)
            logging.info("多窗口分辨率调整完成:")
            logging.info(f"  总窗口数: {report['summary']['total_windows']}")
            logging.info(f"  成功: {report['summary']['successful']}")
            logging.info(f"  失败: {report['summary']['failed']}")
            logging.info(f"  成功率: {report['summary']['success_rate']}")
            # 记录失败的窗口
            for failed_window in report['failed_windows']:
                logging.error(f"  失败窗口: {failed_window['title']} - {failed_window['reason']}")
            # 调试：打印调整后的窗口状态
            logging.info("调试：多窗口调整后的窗口状态:")
            for i, window_info in enumerate(enabled_windows):
                hwnd = window_info.get('hwnd')
                title = window_info.get('title', '未知窗口')
                if hwnd:
                    debug_info = adapter.debug_window_info(hwnd)
                    logging.info(f"  窗口 {i+1}: {title}")
                    logging.info(f"    调整后客户区尺寸: {debug_info.get('client_size', 'N/A')}")
        except Exception as e:
            logging.error(f"使用通用窗口管理器调整失败: {e}")

    def _get_bound_hwnds_for_title(self, title):
        """获取当前绑定列表中与标题匹配的 HWND 集合。"""
        bound_hwnds = []

        for window_info in getattr(self, 'bound_windows', []) or []:
            if window_info.get('title') != title:
                continue
            hwnd = int(window_info.get('hwnd', 0) or 0)
            if hwnd:
                bound_hwnds.append(hwnd)

        return bound_hwnds

    def _find_window_by_title(self, title):

        """查找窗口，支持顶级窗口和子窗口。"""

        if not PYWIN32_AVAILABLE or win32gui is None:
            return None

        exact_top_level_hwnds = find_all_exact_window_hwnds(title)
        hwnd = resolve_exact_window_match(
            title,
            exact_top_level_hwnds,
            preferred_hwnds=self._get_bound_hwnds_for_title(title),
            prefer_preferred=True,
        )
        if hwnd:
            return hwnd

        if exact_top_level_hwnds:
            return None

        hwnd, _, _ = find_window_with_parent_info(title)
        if hwnd:
            logger.info(f"通过公共窗口查找找到窗口: {title} (HWND: {hwnd})")
        return hwnd

    def _find_window_with_parent_info(self, title):

        """查找窗口并返回父窗口信息。"""

        if not PYWIN32_AVAILABLE or win32gui is None:
            return None, False, None

        clean_title = title
        if title:
            clean_title = sanitize_window_lookup_title(title)
        if clean_title != title:
            logger.info(f"清理窗口标题: '{title}' -> '{clean_title}'")

        hwnd, is_child, parent_hwnd = find_window_with_parent_info(
            clean_title,
            preferred_hwnds=self._get_bound_hwnds_for_title(clean_title),
            prefer_preferred=True,
        )
        if hwnd:
            logger.info(
                f"通过公共窗口查找找到窗口: {clean_title} "
                f"(HWND: {hwnd}, 是否为子窗口: {is_child})"
            )
        return hwnd, is_child, parent_hwnd

    def _sync_runtime_window_binding_state(self):

        if not hasattr(self, 'config') or not isinstance(self.config, dict):

            return

        self.native_bound_windows = get_native_bound_windows(self.config)

        self.native_window_binding_mode = get_window_binding_mode(self.config)

        self.bound_windows = self.native_bound_windows

        self.window_binding_mode = self.native_window_binding_mode

        sync_runtime_window_binding_state(self.config)
        self._publish_instance_bound_hwnds()

        if self.window_binding_mode == 'multiple':

            self.current_target_window_title = get_active_target_window_title(self.config)

        elif self.bound_windows:

            self.current_target_window_title = str(self.bound_windows[0].get('title', '') or '').strip() or None

    def get_bound_windows(self):

        return list(self.bound_windows or [])

    def _store_runtime_bound_windows_to_config(self):

        if not hasattr(self, 'config') or not isinstance(self.config, dict):

            return

        self.native_bound_windows = self.bound_windows

        self.native_window_binding_mode = self.window_binding_mode

        self.config['bound_windows'] = self.native_bound_windows

        self.config['window_binding_mode'] = self.native_window_binding_mode

        sync_runtime_window_binding_state(self.config)
        self._publish_instance_bound_hwnds()

    def _publish_instance_bound_hwnds(self):
        try:
            from utils.instance_runtime import publish_bound_hwnds

            publish_bound_hwnds(getattr(self, "bound_windows", None))
        except Exception:
            pass

    def _update_task_window_binding(self, task):

        """

        检查任务的窗口绑定信息（不修改绑定状态）

        Args:

            task: WorkflowTask对象

        """

        # 【关键修复】只验证窗口绑定，不修改任务的绑定状态

        # 如果窗口绑定失效，让 _create_executor 中的逻辑来处理

        if task.target_hwnd or task.target_window_title or getattr(task, 'bound_window_id', None):

            refresh_bound_windows(self.bound_windows)
            matched_window = match_bound_window(
                self.bound_windows,
                hwnd=task.target_hwnd,
                title=task.target_window_title,
                bind_id=getattr(task, 'bound_window_id', None),
            )

            if matched_window:

                new_hwnd = matched_window.get('hwnd')
                if new_hwnd and new_hwnd != task.target_hwnd:
                    logger.info(
                        f"任务 '{task.name}' 绑定窗口句柄已重连: {task.target_hwnd} => {new_hwnd}"
                    )
                    task.target_hwnd = new_hwnd
                if matched_window.get('title'):
                    task.target_window_title = matched_window.get('title')
                logger.info(f"任务 '{task.name}' 已绑定窗口 (HWND: {task.target_hwnd}, '{task.target_window_title}')，且窗口仍在全局设置中")

                self._update_task_execution_mode(task)

                return

            else:

                logger.warning(f"任务 '{task.name}' 绑定的窗口 (HWND: {task.target_hwnd}, '{task.target_window_title}') 已从全局设置中移除或被禁用")

                logger.warning("  保留任务的绑定信息，执行时将提示用户处理")

                self._update_task_execution_mode(task)

                return

        # 任务没有绑定窗口

        # [注意] 不自动设置窗口绑定，保持任务的"未绑定"状态

        # 执行时会使用全局配置的第一个窗口

        logger.info(f"任务 '{task.name}' 未绑定窗口，执行时将使用全局配置的第一个启用窗口")

        # 更新执行模式

        self._update_task_execution_mode(task)

    def is_hwnd_bound(self, hwnd):

        """

        检查指定句柄是否在全局绑定列表中

        Args:

            hwnd: 窗口句柄（可以是整数或字符串"ALL_BOUND"）

        Returns:

            bool: True如果句柄在绑定列表中，False否则

        """

        if not hwnd:

            return False

        # 特殊值"ALL_BOUND"总是返回False，因为它不是有效的窗口句柄

        if hwnd == "ALL_BOUND":

            logger.warning("检测到特殊标记ALL_BOUND，这不是有效的窗口句柄")

            return False

        # 检查句柄是否在绑定列表中

        for window in self.bound_windows:

            if window.get('hwnd') == hwnd:

                return True

        return False

    def validate_hwnd_or_get_first(self, hwnd):

        """

        验证句柄是否有效，如果无效则返回第一个绑定的窗口句柄

        Args:

            hwnd: 要验证的窗口句柄

        Returns:

            tuple: (valid_hwnd, is_original)

                   valid_hwnd - 有效的句柄（可能是原句柄或第一个窗口）

                   is_original - True如果返回的是原句柄，False如果是替换的

        """

        # 检查原句柄是否有效

        if hwnd and self.is_hwnd_bound(hwnd):

            return hwnd, True

        # 原句柄无效时，仅在只有一个可用绑定窗口时才允许自动切换

        valid_hwnds = []

        if self.bound_windows:

            for window_info in self.bound_windows:

                candidate_hwnd = window_info.get('hwnd')

                if candidate_hwnd and candidate_hwnd != "ALL_BOUND":

                    valid_hwnds.append(candidate_hwnd)

        if len(valid_hwnds) == 1:

            fallback_hwnd = valid_hwnds[0]

            logger.warning(f"原句柄 {hwnd} 无效或未绑定，已切换到唯一可用窗口: {fallback_hwnd}")

            return fallback_hwnd, False

        if len(valid_hwnds) > 1:

            logger.error(f"句柄 {hwnd} 无效，当前存在 {len(valid_hwnds)} 个可用绑定窗口，拒绝自动切换")

            return None, False

        # 没有可用的窗口

        logger.error(f"句柄 {hwnd} 无效且没有其他可用窗口")

        return None, False

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
                    logger.info("窗口已最小化，正在恢复...")
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
