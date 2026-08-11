import logging

from PySide6.QtWidgets import QMessageBox

from utils.window_coordinate_common import center_window_on_widget_screen

from utils.thread_start_utils import THREAD_START_TASK_TYPE, is_thread_start_task_type

logger = logging.getLogger(__name__)


class MainWindowMultiWindowRuntimeMixin:
    def _run_multi_window_workflow(self):

        """执行多窗口工作流（支持多个工作流合并执行）"""

        logger.info("开始多窗口工作流执行")

        # ===【新增】检查并自动应用参数面板===

        if hasattr(self, 'parameter_panel') and self.parameter_panel.is_panel_open():

            logger.info("[多窗口执行前检查] 发现参数面板处于打开状态，自动应用并关闭")

            self.parameter_panel.apply_and_close()

        # =====================================

        # 检查是否有启用的窗口

        enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

        if not enabled_windows:

            QMessageBox.warning(self, "提示", "没有启用的窗口，请在全局设置中添加并启用窗口")

            return

        # 获取所有启用的工作流任务

        enabled_tasks = self.task_manager.get_enabled_tasks()

        logger.info(f"多窗口执行: 找到 {len(enabled_tasks)} 个启用的工作流任务")

        # 如果只有一个启用的任务，使用该任务的工作流

        if len(enabled_tasks) == 1:

            task = enabled_tasks[0]

            logger.info(f"多窗口执行: 使用单个工作流任务 '{task.name}'")

            # 【关键修复】从画布获取最新的序列化数据，而不是使用缓存的 task.workflow_data

            workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)

            if workflow_view:

                current_task_id = None

                if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                    current_task_id = self.workflow_tab_widget.get_current_task_id()

                variables_override = self._resolve_variables_override(task, current_task_id)

                workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)

                logger.info(f"多窗口执行: 从画布获取最新工作流数据")

            else:

                workflow_data = task.workflow_data

                logger.warning(f"多窗口执行: 无法获取画布，使用缓存的 workflow_data")

        elif len(enabled_tasks) > 1:

            # 多个工作流任务，合并为一个

            logger.info(f"多窗口执行: 合并 {len(enabled_tasks)} 个工作流任务")

            workflow_data = self._merge_workflows(enabled_tasks)

            if not workflow_data:

                QMessageBox.warning(self, "提示", "合并工作流失败，请检查工作流配置")

                return

        else:

            # 没有启用的任务，使用当前画布的工作流

            logger.info("多窗口执行: 没有启用的工作流任务，使用当前画布")

            # 工具 修复：检查 workflow_view 是否存在

            if not self.workflow_view:

                logger.error("多窗口执行: 当前画布不存在（workflow_view为None）")

                QMessageBox.warning(self, "提示", "没有可执行的工作流。\n\n请先创建或导入工作流后再执行。")

                return

            workflow_data = self.workflow_view.serialize_workflow()

        # 工具 关键修复：补充必要的配置信息到workflow_data

        # 确保多窗口执行器能获得和单窗口相同的配置

        if 'task_modules' not in workflow_data or not workflow_data['task_modules']:

            workflow_data['task_modules'] = self.task_modules

            logger.info("多窗口执行: 添加task_modules到workflow_data")

        if 'images_dir' not in workflow_data or not workflow_data['images_dir']:

            workflow_data['images_dir'] = self.images_dir

            logger.info(f"多窗口执行: 添加images_dir到workflow_data: {self.images_dir}")

        # 验证关键配置

        if not workflow_data.get('task_modules'):

            logger.error("多窗口执行: task_modules为空，无法执行")

            QMessageBox.warning(self, "配置错误", "任务模块未加载，请重启软件后重试")

            return

        if not workflow_data.get('images_dir'):

            logger.warning("多窗口执行: images_dir为空，图片路径可能解析失败")

            # 不阻止执行，因为可能没有使用图片的任务

        # 检查工作流是否为空

        if not workflow_data or not workflow_data.get("cards"):

            QMessageBox.warning(self, "提示", "工作流为空，请添加任务卡片或启用工作流任务")

            return

        # 调试：检查工作流数据

        cards_data = workflow_data.get("cards", [])

        logger.info(f"多窗口执行: 合并后的工作流包含 {len(cards_data)} 个卡片")

        # 检查是否有线程起点卡片

        start_cards = [

            card for card in cards_data

            if is_thread_start_task_type(card.get('task_type'))

        ]

        logger.info(f"多窗口执行: 找到 {len(start_cards)} 个线程起点卡片")

        if len(start_cards) == 0:

            logger.error(f"多窗口执行: 未找到{THREAD_START_TASK_TYPE}卡片")

            logger.debug(f"多窗口执行: 所有卡片类型: {[(card.get('id'), card.get('task_type')) for card in cards_data]}")

            QMessageBox.warning(self, "提示", f"工作流中必须包含至少一个'{THREAD_START_TASK_TYPE}'卡片才能执行")

            return

        else:

            start_ids = [card.get('id') for card in start_cards if card.get('id') is not None]

            if len(start_cards) == 1:

                logger.info(f"多窗口执行: 线程起点卡片验证通过，ID: {start_cards[0].get('id')}")

            else:

                logger.info(f"多窗口执行: 多线程起点验证通过，将并发执行 {len(start_cards)} 个线程起点: {start_ids}")

        # 保存工作流（如果需要）

        if not self._save_before_execution():

            return

        # 检查前台模式限制：只有单个工作流时才能使用前台模式

        if len(enabled_tasks) > 1:

            # 多个工作流必须使用后台模式

            if not (self.current_execution_mode or '').startswith('background'):

                QMessageBox.warning(

                    self, "执行模式提示",

                    "多个工作流只能使用后台模式\n请在全局设置中将执行模式切换为后台模式"

                )

                return

        # 多窗口模式强制使用后台模式

        if not (self.current_execution_mode or '').startswith('background'):

            reply = QMessageBox.question(

                self, "执行模式确认",

                "多窗口模式需要使用后台模式，是否继续？",

                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No

            )

            if reply != QMessageBox.StandardButton.Yes:

                return

        # 工具 关键修复：先清理旧的多窗口执行器

        if hasattr(self, 'multi_executor') and self.multi_executor:

            logger.info("清理旧的多窗口执行器...")

            try:

                # 断开旧的信号连接

                self.multi_executor.execution_progress.disconnect()

                self.multi_executor.execution_completed.disconnect()

                if hasattr(self.multi_executor, 'card_executing'):

                    self.multi_executor.card_executing.disconnect()

                if hasattr(self.multi_executor, 'card_finished'):

                    self.multi_executor.card_finished.disconnect()

                if hasattr(self.multi_executor, 'error_occurred'):

                    self.multi_executor.error_occurred.disconnect()

                # 清理执行器资源

                if hasattr(self.multi_executor, 'cleanup'):

                    self.multi_executor.cleanup()

                logger.info("旧的多窗口执行器已清理")

            except Exception as e:

                logger.warning(f"清理旧执行器时出错: {e}")

        # 创建统一多窗口执行器

        try:

            from ..runtime_parts.unified_multi_window_executor import UnifiedMultiWindowExecutor

            logger.info("创建新的多窗口执行器...")

            self.multi_executor = UnifiedMultiWindowExecutor(self)

            # 工具 关键修复：添加所有窗口（包括禁用的），正确传递enabled状态

            successfully_added = 0

            failed_windows = []

            # 遍历所有绑定的窗口，而不仅仅是启用的窗口

            logger.info(f"检查绑定窗口状态，总数: {len(self.bound_windows)}")

            for i, window_info in enumerate(self.bound_windows):

                window_title = window_info['title']

                window_enabled = window_info.get('enabled', True)

                logger.info(f"  窗口{i+1}: {window_title}, enabled={window_enabled}, hwnd={window_info.get('hwnd')}")

                # 优先使用绑定窗口中保存的句柄

                hwnd = window_info.get('hwnd')

                if hwnd:

                    # 验证句柄是否仍然有效

                    try:

                        import win32gui

                        if win32gui.IsWindow(hwnd):

                            logger.info(f"使用保存的窗口句柄: {window_title} (HWND: {hwnd}), 启用: {window_enabled}")

                            # 工具 强制重新检测DPI信息，不使用保存的旧信息

                            self._force_refresh_dpi_info(window_info, hwnd)

                        else:

                            logger.warning(f"保存的句柄无效，重新查找: {window_title} (HWND: {hwnd})")

                            hwnd = None

                    except:

                        logger.warning(f"无法验证句柄，重新查找: {window_title}")

                        hwnd = None

                # 工具 关键修复：多窗口模式下不重新查找窗口，避免窗口混乱

                if not hwnd:

                    logger.error(f"多窗口模式下窗口句柄无效且无法恢复: {window_title}")

                    logger.error(f"   建议：重新绑定该窗口以获取正确的句柄")

                    failed_windows.append(window_title)

                    continue

                if hwnd:

                    # 工具 关键修复：传递正确的enabled状态

                    self.multi_executor.add_window(window_title, hwnd, window_enabled)

                    if window_enabled:

                        successfully_added += 1

                    logger.info(f"添加窗口到多窗口执行器: {window_title} (HWND: {hwnd}), 启用: {window_enabled}")

                else:

                    failed_windows.append(window_title)

                    logger.warning(f"未找到窗口: {window_title}")

            # 检查是否有成功添加的窗口

            if successfully_added == 0:

                error_msg = f"无法找到任何绑定的窗口！\n\n"

                error_msg += f"状态统计:\n"

                error_msg += f"   启用的窗口数量: {len(enabled_windows)}\n"

                error_msg += f"   成功找到: 0 个\n"

                error_msg += f"   未找到: {len(failed_windows)} 个\n\n"

                error_msg += f"未找到的窗口:\n"

                for i, window in enumerate(failed_windows, 1):

                    error_msg += f"   {i}. {window}\n"

                error_msg += f"\n灯泡 建议解决方案:\n"

                error_msg += f"   1. 检查目标窗口是否已打开\n"

                error_msg += f"   2. 在全局设置中重新绑定窗口\n"

                error_msg += f"   3. 确认窗口标题是否正确\n"

                error_msg += f"   4. 尝试使用'添加模拟器'功能重新添加"

                # 创建自定义消息框，包含打开设置的按钮

                msg_box = QMessageBox(self)

                msg_box.setWindowTitle("多窗口执行失败")

                msg_box.setText(error_msg)

                msg_box.setIcon(QMessageBox.Icon.Warning)

                # 添加按钮

                settings_button = msg_box.addButton("打开全局设置", QMessageBox.ButtonRole.ActionRole)

                close_button = msg_box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)

                center_window_on_widget_screen(msg_box, self)

                msg_box.exec()

                # 如果用户点击了设置按钮，打开全局设置

                if msg_box.clickedButton() == settings_button:

                    self.open_global_settings()

                return

            # 如果部分窗口未找到，给出警告

            if failed_windows:

                warning_msg = f"部分窗口未找到，是否继续执行？\n\n"

                warning_msg += f"执行状态:\n"

                warning_msg += f"可执行窗口: {successfully_added} 个\n"

                warning_msg += f"未找到窗口: {len(failed_windows)} 个\n\n"

                warning_msg += f"未找到的窗口:\n"

                for i, window in enumerate(failed_windows, 1):

                    warning_msg += f"   {i}. {window}\n"

                warning_msg += f"\n将仅在 {successfully_added} 个可用窗口中执行任务。\n"

                warning_msg += f"是否继续执行？"

                reply = QMessageBox.question(

                    self, "部分窗口未找到", warning_msg,

                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No

                )

                if reply != QMessageBox.StandardButton.Yes:

                    return

            # 连接信号

            logger.info("连接多窗口执行器信号...")

            self.multi_executor.execution_progress.connect(self._on_multi_window_progress)

            self.multi_executor.execution_completed.connect(self._on_multi_window_completed)

            logger.info("已连接多窗口执行器的主要信号 (progress, completed)")

            # 工具 连接卡片状态信号以支持闪烁效果

            if hasattr(self.multi_executor, 'card_executing'):

                self.multi_executor.card_executing.connect(self._handle_card_executing)

                self.multi_executor.card_finished.connect(self._handle_card_finished)

                self.multi_executor.error_occurred.connect(self._on_multi_window_error)

                if hasattr(self.multi_executor, 'show_warning'):

                    self.multi_executor.show_warning.connect(self._show_warning_dialog)

                logger.info("已连接多窗口执行器的卡片状态信号")

            else:

                logger.warning("多窗口执行器没有卡片状态信号")

            # 开始执行

            delay_ms = self.multi_window_delay

            # 全局执行模式与多窗口并发策略解耦：

            # - execution_mode: 传给窗口执行器（foreground/background）

            # - sync_execution_mode: 传给多窗口调度器（parallel/sequential）

            from ..runtime_parts.unified_multi_window_executor import ExecutionMode

            runtime_execution_mode = (

                self.current_execution_mode if hasattr(self, 'current_execution_mode') else 'background_sendmessage'

            )

            sync_execution_mode = ExecutionMode.PARALLEL

            workflow_payload = dict(workflow_data) if isinstance(workflow_data, dict) else {}

            workflow_payload['execution_mode'] = runtime_execution_mode

            logger.info(

                f"多窗口执行配置: 执行模式={runtime_execution_mode}, 同步模式={sync_execution_mode.value}, "

                f"延迟={delay_ms}ms, 窗口数={successfully_added}"

            )

            # 工具 异步执行优化：优先使用异步执行，回退到同步执行

            execution_success = False

            # 检查是否支持异步执行

            if hasattr(self.multi_executor, '_async_mode'):

                logger.info(f"异步模式状态: {self.multi_executor._async_mode}")

            if hasattr(self.multi_executor, '_async_mode') and self.multi_executor._async_mode:

                logger.info("使用异步执行模式启动多窗口任务")

                try:

                    # 使用 QTimer 来在事件循环中执行异步任务

                    import asyncio

                    from PySide6.QtCore import QTimer

                    # 创建异步执行任务

                    async def async_execution():

                        return await self.multi_executor.start_execution_async(

                            workflow_payload, delay_ms, sync_execution_mode, self.bound_windows

                        )

                    # 在Qt事件循环中执行异步任务

                    if hasattr(asyncio, 'get_event_loop'):

                        try:

                            loop = asyncio.get_event_loop()

                            if loop.is_running():

                                # 如果事件循环正在运行，创建任务

                                task = asyncio.create_task(async_execution())

                                # 使用QTimer来检查任务完成状态

                                self._async_execution_task = task

                                self._cleanup_async_execution_watchdog_timers()

                                self._check_async_execution_timer = QTimer(self)

                                self._check_async_execution_timer.setObjectName("__async_execution_watchdog__")

                                self._check_async_execution_timer.timeout.connect(self._check_async_execution_status)

                                self._check_async_execution_timer.start(100)  # 每100ms检查一次

                                execution_success = True

                                logger.info("异步执行任务已创建")

                            else:

                                # 关键修复：不使用run_until_complete，改用QTimer异步执行

                                logger.warning("事件循环未运行，改用QTimer异步执行避免干扰Qt事件循环")

                                task = asyncio.create_task(async_execution())

                                self._async_execution_task = task

                                self._cleanup_async_execution_watchdog_timers()

                                self._check_async_execution_timer = QTimer(self)

                                self._check_async_execution_timer.setObjectName("__async_execution_watchdog__")

                                self._check_async_execution_timer.timeout.connect(self._check_async_execution_status)

                                self._check_async_execution_timer.start(100)  # 每100ms检查一次

                                execution_success = True

                                logger.warning("已创建异步任务和检查定时器")

                                # 立即启动异步任务检查

                                self._check_async_execution_status()

                        except Exception as e:

                            logger.warning(f"异步执行失败，回退到同步模式: {e}")

                            execution_success = False

                    else:

                        logger.warning("asyncio不可用，回退到同步模式")

                        execution_success = False

                except Exception as e:

                    logger.warning(f"异步执行初始化失败，回退到同步模式: {e}")

                    execution_success = False

            # 如果异步执行失败或不可用，使用同步执行

            if not execution_success:

                logger.warning("异步执行失败，回退到同步执行模式启动多窗口任务")

                execution_success = self.multi_executor.start_execution(

                    workflow_payload, delay_ms, sync_execution_mode, self.bound_windows

                )

            if execution_success:

                logger.info(f"多窗口执行已启动，共 {successfully_added} 个窗口，延迟 {delay_ms}ms")
                self._runtime_pause_owner = 'multi_executor'
                self._runtime_stop_owner = 'multi_executor'

                # 正确设置执行状态和停止按钮

                self._setup_multi_window_stop_button()

                # 工具 删除弹窗：直接在日志中记录启动信息，不显示弹窗

                # QMessageBox.information(self, "执行开始", f"已在 {successfully_added} 个窗口开始执行任务")

            else:

                logger.error("多窗口执行启动失败")

                QMessageBox.warning(self, "执行失败", "多窗口执行启动失败，请检查窗口状态")

                self._reset_run_button()

        except ImportError:

            logger.error("无法导入多窗口执行器")

            QMessageBox.critical(self, "功能不可用", "多窗口执行功能不可用，请检查相关模块")

        except Exception as e:

            logger.error(f"多窗口执行启动失败: {e}")

            QMessageBox.critical(self, "执行失败", f"多窗口执行启动失败:\n{e}")

            self._reset_run_button()

    def _cleanup_async_execution_watchdog_timers(self):

        """停止并回收所有异步执行状态检查定时器（含历史遗留对象）。"""

        from PySide6.QtCore import QTimer

        for timer in self.findChildren(QTimer, "__async_execution_watchdog__"):

            if timer is None:

                continue

            try:

                if timer.isActive():

                    timer.stop()

            except RuntimeError:

                continue

            try:

                timer.deleteLater()

            except RuntimeError:

                continue

        if hasattr(self, '_check_async_execution_timer'):

            try:

                delattr(self, '_check_async_execution_timer')

            except Exception:

                pass

    def _check_async_execution_status(self):

        """检查异步执行状态"""

        task = getattr(self, '_async_execution_task', None)

        if task is None:

            # 若任务引用已不存在，主动清理全部看门狗定时器，避免历史对象持续触发

            self._cleanup_async_execution_watchdog_timers()

            return

        if not task.done():

            return

        # 任务完成，统一清理看门狗定时器

        self._cleanup_async_execution_watchdog_timers()

        try:

            result = task.result()

            if result:

                self._runtime_pause_owner = 'multi_executor'
                self._runtime_stop_owner = 'multi_executor'
                self._setup_multi_window_stop_button()

            else:

                logger.error("异步多窗口执行失败")

                QMessageBox.warning(self, "执行失败", "异步多窗口执行失败，请检查窗口状态")

                self._reset_run_button()

        except Exception as e:

            logger.error(f"异步多窗口执行异常: {e}")

            QMessageBox.warning(self, "执行异常", f"异步多窗口执行异常:\n{e}")

            self._reset_run_button()

        finally:

            if hasattr(self, '_async_execution_task'):

                delattr(self, '_async_execution_task')
