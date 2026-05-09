import copy
import json
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from task_workflow.process_proxy import create_process_workflow_runtime
from utils.thread_start_utils import THREAD_START_TASK_TYPE, is_thread_start_task_type

logger = logging.getLogger(__name__)


class MainWindowRunWorkflowMixin:
    def run_workflow(self, *args, **kwargs):

        """Initiates the workflow execution in a separate thread.

        Args:

            test_mode: Optional test mode ('single_card' or 'flow')

            test_card_id: Card ID to use as start point in test mode

        """

        self._active_execution_task_id = None

        # 【互斥检查】检查中控是否有任务正在运行，如果有则拒绝启动

        if hasattr(self, 'control_center') and self.control_center:

            if self.control_center.is_any_task_running():

                logger.warning("中控有任务正在运行，主窗口拒绝启动新任务")

                QMessageBox.warning(

                    self,

                    "无法启动",

                    "中控正在执行任务，请等待中控任务完成或停止后再从主窗口启动。\n\n"

                    "中控和主窗口的执行器不能同时运行，否则可能导致程序卡死。"

                )

                return

        # 提取测试模式参数

        test_mode = kwargs.get('test_mode', None)  # 'single_card' or 'flow'

        test_card_id = kwargs.get('test_card_id', None)

        # 防御：标准化测试参数，避免非测试启动误携带测试状态

        if test_mode not in (None, 'single_card', 'flow'):

            logger.warning(f"run_workflow: 非法 test_mode='{test_mode}'，已重置为None")

            test_mode = None

        if not test_mode and test_card_id is not None:

            logger.warning(f"run_workflow: 非测试模式下忽略 test_card_id={test_card_id}")

            test_card_id = None

        if test_mode:

            if not isinstance(test_card_id, int):

                try:

                    test_card_id = int(test_card_id)

                except Exception:

                    QMessageBox.warning(self, "测试参数错误", "测试模式缺少有效的卡片ID，已取消执行。")

                    return

            if test_card_id < 0:

                QMessageBox.warning(self, "测试参数错误", "测试模式卡片ID无效，已取消执行。")

                return

        if test_mode:

            logger.info(f"测试模式: {test_mode}, 卡片ID: {test_card_id}")

        # 检查是否有标记为"首个执行"的工作流

        # 注意：测试模式下跳过此步骤

        first_execute_task = None

        logger.info(f"========== 检查首个执行任务 ==========")

        logger.info(f"test_mode = {test_mode}")

        if not test_mode:

            if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                all_tasks = self.task_manager.get_all_tasks()

                logger.info(f"共有 {len(all_tasks)} 个任务")

                for task_item in all_tasks:

                    logger.info(f"  任务: '{task_item.name}' (ID={task_item.task_id})")

                    logger.info(f"    hasattr first_execute: {hasattr(task_item, 'first_execute')}")

                    if hasattr(task_item, 'first_execute'):

                        logger.info(f"    first_execute = {task_item.first_execute}")

                    if hasattr(task_item, 'first_execute') and task_item.first_execute:

                        first_execute_task = task_item

                        logger.info(f"  ✓ 找到首个执行任务: '{task_item.name}' (ID={task_item.task_id})")

                        break

        if not first_execute_task:

            logger.info(f"  未找到首个执行任务")

        logger.info(f"======================================")

        # 【关键】立即确定要执行的任务，优先使用首个执行任务

        actual_task = None

        if not test_mode and first_execute_task:

            logger.info(f"将使用首个执行任务: '{first_execute_task.name}'")

            actual_task = first_execute_task

        else:

            # 没有首个执行任务，使用当前标签页的任务

            actual_task_id = self.workflow_tab_widget.get_current_task_id()

            if actual_task_id:

                actual_task = self.task_manager.get_task(actual_task_id)

                if actual_task:

                    logger.info(f"使用当前标签页任务: '{actual_task.name}'")

            else:

                logger.warning(f"get_current_task_id() 返回 None")

        if not actual_task:

            logger.error("无法确定要执行的任务")

            QMessageBox.warning(self, "错误", "无法确定要执行的任务")

            return

        logger.info(f"=== 最终执行任务: '{actual_task.name}' (ID={actual_task.task_id}) ===")

        # ===【新增】检查并自动应用参数面板===

        if hasattr(self, 'parameter_panel'):

            if self.parameter_panel.is_panel_open():

                self.parameter_panel.apply_and_close()

        # =====================================

        # 首先检查是否有当前工作流

        if not self._ensure_current_workflow(show_warning=True):

            return

        # 执行前重置卡片状态

        self._reset_all_workflow_card_states("执行前重置卡片状态")

        log_func = logging.info if logging.getLogger().hasHandlers() else print

        # 新增：执行前自动保存并备份所有标签页的工作流

        all_tasks = self.task_manager.get_all_tasks()

        logger.info(f"run_workflow: 执行前自动保存和备份所有标签页的工作流，共 {len(all_tasks)} 个")

        saved_count = 0

        backup_failed_tasks = []

        current_task_id = None

        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

            current_task_id = self.workflow_tab_widget.get_current_task_id()

        for task_item in all_tasks:

            # 先从画布获取最新工作流数据

            workflow_view = self.workflow_tab_widget.task_views.get(task_item.task_id)

            latest_workflow_data = None

            if workflow_view:

                logger.info(f"从画布获取最新工作流数据: {task_item.name}")

                variables_override = self._resolve_variables_override(task_item, current_task_id)

                latest_workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)

            else:

                logger.warning(f"无法获取任务 '{task_item.name}' 的 WorkflowView，使用现有数据")

            # 保存和备份（传入最新数据，避免覆盖跳转配置）

            if task_item.save_and_backup(workflow_data=latest_workflow_data):

                saved_count += 1

                logger.info(f"任务 '{task_item.name}' 保存和备份成功")

                # 更新标签页状态，移除星号

                self.workflow_tab_widget._update_tab_status(task_item.task_id)

            else:

                backup_failed_tasks.append(task_item.name)

                logger.warning(f"任务 '{task_item.name}' 保存或备份失败，但继续执行")

        logger.info(f"成功保存和备份 {saved_count}/{len(all_tasks)} 个任务")

        if backup_failed_tasks:

            logger.warning(f"以下任务保存或备份失败: {', '.join(backup_failed_tasks)}，但将继续执行")

        # 在任务执行前检查并更新窗口句柄

        # HOTFIX: 临时禁用此方法调用，因为方法定义位置错误（在类外部）

        # try:

        #     self._check_and_update_window_handles()

        # except Exception as e:

        #     logger.error(f"检查窗口句柄时出错: {e}")

        # 工具 关键修复：动态检查窗口绑定模式，根据启用窗口数量决定执行方式

        enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

        enabled_count = len(enabled_windows)

        logger.info(f"搜索 运行时检查: 总绑定窗口={len(self.bound_windows)}, 启用窗口={enabled_count}")

        if enabled_count > 1:

            # 多个启用窗口：强制使用多窗口模式

            logger.info(f"检测到{enabled_count}个启用窗口，使用多窗口模式")

            self._run_multi_window_workflow()

            return

        elif enabled_count == 1:

            # 单个启用窗口：使用单窗口模式，但使用启用的那个窗口

            enabled_window = enabled_windows[0]

            logger.info(f"检测到1个启用窗口，使用单窗口模式: {enabled_window['title']} (HWND: {enabled_window.get('hwnd')})")

            # 工具 关键修复：直接保存启用窗口的句柄，避免通过标题查找导致的混乱

            self._forced_target_hwnd = enabled_window.get('hwnd')

            self._forced_target_title = enabled_window['title']

            logger.info(f"强制使用启用窗口句柄: {self._forced_target_hwnd}")

        else:

            # 没有启用的窗口

            logger.warning("没有启用的窗口，无法执行")

            QMessageBox.warning(self, "无法执行", "没有启用的窗口。请在全局设置中启用至少一个窗口。")

            return

        # 单窗口模式（原有逻辑）

        # --- MODIFIED: Always Save/Backup or Prompt Save As before running ---

        save_successful = False

        # 使用actual_task来处理保存逻辑

        task = actual_task

        task_save_path = task.filepath

        logger.info(f"检查任务 '{task.name}' 的保存状态，路径: {task_save_path}")

        if task_save_path:

            # 任务已有保存路径，直接使用（导入的任务默认已保存）

            logger.info(f"任务已有保存路径，无需再次保存: {task_save_path}")

            save_successful = True

        else:

            # 任务没有保存路径，提示用户保存

            logger.info("任务未保存，提示用户另存为...")

            reply = QMessageBox.question(self, "需要保存",

                                         f"工作流 '{task.name}' 尚未保存。是否先保存再运行？",

                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,

                                         QMessageBox.StandardButton.Yes)

            if reply == QMessageBox.StandardButton.Yes:

                # 获取任务的WorkflowView来序列化

                task_workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)

                if not task_workflow_view:

                    logger.error(f"无法找到任务 '{task.name}' 的WorkflowView")

                    QMessageBox.warning(self, "错误", f"无法找到任务 '{task.name}' 的视图")

                    return

                # 调用标签页的保存方法

                import os
                from PySide6.QtWidgets import QFileDialog
                from utils.app_paths import get_workflows_dir

                filepath, _ = QFileDialog.getSaveFileName(

                    self,

                    "保存工作流",

                    os.path.join(get_workflows_dir(), task.name),

                    "JSON文件 (*.json);;所有文件 (*)"

                )

                if filepath:

                    # 保存任务

                    current_task_id = None

                    if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                        current_task_id = self.workflow_tab_widget.get_current_task_id()

                    variables_override = self._resolve_variables_override(task, current_task_id)

                    workflow_data = task_workflow_view.serialize_workflow(variables_override=variables_override)

                    import json

                    try:

                        with open(filepath, 'w', encoding='utf-8') as f:

                            json.dump(workflow_data, f, indent=2, ensure_ascii=False)

                        task.filepath = filepath

                        task.modified = False

                        save_successful = True

                        logger.info(f"任务保存成功: {filepath}")

                    except Exception as e:

                        logger.error(f"保存任务失败: {e}")

                        QMessageBox.warning(self, "保存失败", f"保存失败: {e}")

                        return

                else:

                    logger.info("用户取消了保存操作，中止执行。")

                    return

            else:

                logger.info("用户选择不保存，中止执行。")

                return

        # --- Proceed only if save was successful ---

        if not save_successful:

            logger.error("保存步骤未成功完成，无法继续执行。")

            return

        # --- Check for existing thread BEFORE getting data ---

        if self.executor_thread is not None:

             logging.warning("run_workflow: 检测到现有工作流线程引用，尝试清理...")

             # 【关键修复】等待旧线程退出

             if self.executor_thread.isRunning():

                 logging.info("旧线程仍在运行，尝试停止...")

                 if self.executor and hasattr(self.executor, 'request_stop'):

                     try:
                         self.executor.request_stop(force=True)
                     except TypeError:
                         self.executor.request_stop()

                 # 等待最多2秒让线程退出

                 if self.executor_thread.wait(2000):  # 等待2秒

                     logging.info("旧线程已成功退出")

                 else:

                     logging.error("旧线程在2秒内未退出，强制继续（可能导致问题）")

                     QMessageBox.warning(self, "操作冲突",

                                       "先前的工作流正在清理中但超时未完成。\n"

                                       "建议等待几秒后再试，或重启程序。")

                     return

             # 清理引用

             self.executor = None

             self.executor_thread = None

             logging.info("已清理旧的执行器和线程引用")

        # --- End Check ---

        logging.info("run_workflow: 准备运行工作流...")

        # 获取该任务对应的 WorkflowView

        workflow_view = self.workflow_tab_widget.task_views.get(actual_task.task_id)

        if not workflow_view:

            logger.error(f"无法找到任务 '{actual_task.name}' 的 WorkflowView")

            QMessageBox.warning(self, "错误", f"无法找到任务 '{actual_task.name}' 的视图")

            return

        try: # --- Add outer try block ---

            # 1. Gather data

            logging.debug("run_workflow: Gathering data using serialize_workflow...")

            # --- Use serialize_workflow() for structured data ---

            current_task_id = None

            if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                current_task_id = self.workflow_tab_widget.get_current_task_id()

            variables_override = self._resolve_variables_override(actual_task, current_task_id)

            workflow_data = workflow_view.serialize_workflow(variables_override=variables_override) # <-- 使用确定的任务的WorkflowView

            if not workflow_data or not workflow_data.get("cards"):

                logger.warning("工作流为空或无法序列化，无法执行。") # <-- Updated message

                QMessageBox.warning(self, "提示", "工作流为空或无法序列化，请添加步骤或检查配置。") # <-- Updated message

                self._reset_run_button() # Reset button if workflow is empty/invalid

                return

            # --------------------------------------------------

            # 【关键修复】使用序列化数据（深拷贝）而不是TaskCard对象引用

            # 这样可以确保参数在工作流开始时被固定，避免执行过程中被UI修改

            # 将 workflow_data["cards"] 列表转换为 {card_id: card_data} 字典格式

            cards_dict = {}

            for card_data in workflow_data.get("cards", []):

                card_id = card_data.get("id")

                if card_id is not None:

                    # 深拷贝参数，确保完全隔离

                    cards_dict[card_id] = {

                        'id': card_id,

                        'task_type': card_data.get('task_type', '未知'),

                        'parameters': copy.deepcopy(card_data.get('parameters', {})),

                        'custom_name': card_data.get('custom_name'),

                        'pos_x': card_data.get('pos_x', 0),

                        'pos_y': card_data.get('pos_y', 0)

                    }

            logger.info(f"[工作流启动] 已将 {len(cards_dict)} 个卡片转换为序列化字典格式（参数已深拷贝）")

            # 修复：测试模式下跳过场景遍历，避免卡死

            if not test_mode:

                # 【优化】使用已序列化的连接数据，而不是遍历场景对象

                connections_list = workflow_data.get("connections", [])

            else:

                # 测试模式下也需要加载原有连接，特别是流程测试需要完整的连接关系

                connections_list = workflow_data.get("connections", [])

                logger.info(f"[测试模式] 加载原有连接 {len(connections_list)} 条，后续会添加虚拟连接")

            logging.debug(f"run_workflow: Found {len(cards_dict)} cards, {len(connections_list)} connections for executor.")

            # Redundant check, already checked serialized data

            # if not cards_dict:

            #     QMessageBox.information(self, "提示", "工作流为空，无法执行。")

            #     logging.warning("run_workflow: 工作流为空，中止执行。")

            #     self._reset_run_button() # Ensure button is reset

            # ----------------------------------------------------------------

            # Visually update button, but keep signal connected to run_workflow for now

            logging.debug("run_workflow: Updating UI button state (Appearance only).")

            self.run_action.setEnabled(False) # Disable temporarily until thread starts

            self.run_action.setText("准备中...") # Indicate preparation

            # self.run_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)) # Don't set icon yet

            self.run_action.setToolTip("正在准备执行工作流")

            # --- DO NOT DISCONNECT/RECONNECT SIGNAL HERE --- 

            # self.run_action.triggered.disconnect()

            # self.run_action.triggered.connect(self.request_stop_workflow) 

            # -----------------------------------------------

            

            # 2. Create Thread and Executor

            logging.debug("run_workflow: Creating QThread...")

            self.executor_thread = None

            logging.debug("run_workflow: Creating WorkflowExecutor...")

            # --- Add inner try block for Executor creation ---

            try:

                # --- MODIFIED: Find the starting card ---

                start_card_id = None

                start_card_ids = []

                thread_labels = {}

                start_card_obj = None

                start_card_count = 0

                # 测试模式下会在后面创建虚拟起点，这里先跳过起点检查

                if not test_mode:

                    # 正常模式：查找类型为“线程起点”的卡片

                    # 【修复闪退】检查workflow_view和cards是否存在

                    if not workflow_view or not hasattr(workflow_view, 'cards'):

                        logging.error("workflow_view 或 cards 不存在，无法执行工作流")

                        QMessageBox.critical(self, "错误", "工作流视图异常，无法执行")

                        self._reset_run_button()

                        self.executor = None

                        self.executor_thread = None

                        return

                    for card in workflow_view.cards.values():

                        if is_thread_start_task_type(getattr(card, "task_type", "")):

                            start_card_ids.append(card.card_id)

                    start_card_ids = sorted(set(start_card_ids))

                    start_card_count = len(start_card_ids)

                    # Validate the start card

                    if start_card_count == 0:

                        logging.error(f"未能找到{THREAD_START_TASK_TYPE}卡片。执行中止。")

                        QMessageBox.critical(self, "错误", f"无法开始执行：工作流中必须包含至少一个类型为 '{THREAD_START_TASK_TYPE}' 的卡片。")

                        self._reset_run_button()

                        # --- ADDED: Explicit cleanup on start card error ---

                        self.executor = None

                        self.executor_thread = None

                        # -------------------------------------------------

                        return

                    else:

                        start_card_id = start_card_ids[0]

                        start_card_obj = workflow_view.cards.get(start_card_id)

                        for sid in start_card_ids:

                            card_data = cards_dict.get(sid) if isinstance(cards_dict, dict) else None

                            label_text = ""

                            if isinstance(card_data, dict):

                                label_text = str(card_data.get("custom_name") or "").strip()

                            if not label_text:

                                card_obj = workflow_view.cards.get(sid)

                                label_text = str(getattr(card_obj, "custom_name", "") or "").strip()

                            if label_text:

                                thread_labels[sid] = label_text

                        if start_card_count == 1:

                            card_type = getattr(start_card_obj, "task_type", THREAD_START_TASK_TYPE)

                            logging.info(f"找到唯一的线程起点卡片: Card ID={start_card_id}, Type={card_type}")

                        else:

                            logging.info(

                                "找到 %d 个线程起点卡片，将以多线程模式并发执行: %s",

                                start_card_count,

                                start_card_ids,

                            )

                # --- END MODIFICATION ---

                # 工具 关键修复：优先使用强制指定的窗口句柄（单个启用窗口模式）

                target_hwnd = None

                target_window_title = self.current_target_window_title or None

                # 第一优先级：强制指定的窗口句柄（来自启用窗口检查）

                if hasattr(self, '_forced_target_hwnd') and self._forced_target_hwnd:

                    target_hwnd = self._forced_target_hwnd

                    target_window_title = getattr(self, '_forced_target_title', None) or target_window_title

                    logger.info(f"使用强制指定的启用窗口句柄: {target_hwnd} ('{self._forced_target_title}')")

                # 第二优先级：从绑定窗口中查找保存的句柄

                elif self.current_target_window_title:

                    target_window_title = self.current_target_window_title

                    # 首先尝试从绑定窗口列表中获取保存的句柄

                    for window_info in self.bound_windows:

                        if window_info['title'] == self.current_target_window_title:

                            saved_hwnd = window_info.get('hwnd')

                            if saved_hwnd:

                                # 验证保存的句柄是否仍然有效

                                try:

                                    import win32gui

                                    if win32gui.IsWindow(saved_hwnd):

                                        target_hwnd = saved_hwnd

                                        logger.info(f"单窗口模式: 使用保存的窗口句柄 '{self.current_target_window_title}' (HWND: {target_hwnd})")

                                        # 工具 应用保存的DPI信息

                                        self._apply_saved_dpi_info(window_info, target_hwnd)

                                        break

                                    else:

                                        logger.warning(f"保存的窗口句柄已失效: {saved_hwnd}")

                                except Exception as e:

                                    logger.warning(f"验证保存的窗口句柄时出错: {e}")

                    # 如果没有找到有效的保存句柄，才重新查找（但这可能导致窗口混乱）

                    if not target_hwnd:

                        logger.warning(f"未找到保存的窗口句柄，重新查找可能导致窗口混乱: '{self.current_target_window_title}'")

                        target_hwnd = self._find_window_by_title(self.current_target_window_title)

                        if target_hwnd:

                            logger.warning(f"重新查找到窗口，但可能不是用户绑定的特定窗口: {target_hwnd}")

                        else:

                            logger.error(f"完全找不到目标窗口: '{self.current_target_window_title}'")

                # 工具 关键修复：在创建WorkflowExecutor之前应用强制窗口句柄

                if hasattr(self, '_forced_target_hwnd') and self._forced_target_hwnd:

                    logger.info(f"应用强制窗口句柄: {target_hwnd} -> {self._forced_target_hwnd}")

                    target_hwnd = self._forced_target_hwnd

                    target_window_title = getattr(self, '_forced_target_title', None) or target_window_title

                logger.info(f"单窗口模式: 最终目标窗口句柄 = {target_hwnd}")

                # --- 测试模式：创建虚拟起点并修改工作流 ---

                logger.info(f"[测试检查] test_mode={test_mode}, test_card_id={test_card_id}")

                if test_mode:

                    logger.info(f"[测试模式] 进入测试模式分支")

                    # 创建一个虚拟的测试线程起点卡片（ID使用负数，避免与真实卡片冲突）

                    virtual_start_id = -9999

                    virtual_start_card = {

                        'id': virtual_start_id,

                        'task_type': THREAD_START_TASK_TYPE,

                        'parameters': {},

                        'position': {'x': 0, 'y': 0}

                    }

                    logger.info(f"[测试模式] 虚拟线程起点已创建: {virtual_start_id}")

                    if test_mode == 'single_card':

                        logger.info(f"[单卡测试] 开始处理单卡测试，test_card_id={test_card_id}")

                        # 单卡测试：虚拟起点 -> 测试卡片，无其他卡片和连接

                        logger.info(f"[单卡测试] 创建虚拟起点 -> 卡片 {test_card_id}")

                        single_card_obj = workflow_view.cards.get(test_card_id)

                        if not single_card_obj:

                            logging.error(f"[单卡测试] 无法找到卡片 {test_card_id}")

                            QMessageBox.critical(self, "错误", f"无法找到测试卡片 {test_card_id}")

                            self._reset_run_button()

                            self.executor = None

                            self.executor_thread = None

                            return

                        # 创建单卡工作流数据（序列化卡片对象）

                        # 检查是TaskCard对象还是字典（字典类型检查更可靠）

                        if isinstance(single_card_obj, dict):

                            # 已经是字典，需要深拷贝以避免修改原始数据

                            single_card_data = copy.deepcopy(single_card_obj)

                            logger.info(f"[单卡测试] 卡片 {test_card_id} 已经是字典格式")

                        else:

                            # TaskCard对象，需要序列化

                            single_card_data = {

                                'id': test_card_id,

                                'task_type': single_card_obj.task_type,

                                'parameters': copy.deepcopy(single_card_obj.parameters),

                                'position': {'x': single_card_obj.x(), 'y': single_card_obj.y()}

                            }

                            logger.info(f"[单卡测试] 卡片 {test_card_id} 从TaskCard对象序列化为字典")

                        # 清除跳转相关参数，避免跳转到不存在的卡片

                        params = single_card_data.get('parameters', {})

                        # 列出所有可能包含卡片ID引用的参数键

                        # 遍历所有参数，将值为整数且看起来像卡片ID的参数设置为None

                        params_to_clear = []

                        for key, value in list(params.items()):

                            # 检查参数名是否包含跳转、目标、卡片等关键词

                            key_lower = key.lower()

                            if any(keyword in key_lower for keyword in ['jump', 'target', 'card_id', 'next', 'goto']):

                                # 检查值是否像卡片ID（整数，包括0）

                                # 注意：value >= 0 用于捕获跳转到ID为0的卡片的情况

                                if isinstance(value, int) and value >= 0:

                                    params_to_clear.append((key, value))

                                    params[key] = None  # 设置为None，表示无跳转

                        if params_to_clear:

                            cleared_str = ', '.join([f"{k}={v}" for k, v in params_to_clear])

                            logger.info(f"[单卡测试] 已清除跳转参数: {cleared_str}")

                        if hasattr(self, "_apply_ai_cli_runtime_parameter_overrides"):

                            try:

                                params = self._apply_ai_cli_runtime_parameter_overrides(test_card_id, params)

                            except Exception as exc:

                                logger.debug(f"[单卡测试] AI CLI 运行时参数覆盖失败: {exc}")

                        single_card_data['parameters'] = params

                        # 只包含虚拟起点和测试卡片

                        cards_dict = {

                            virtual_start_id: virtual_start_card,

                            test_card_id: single_card_data

                        }

                        # 创建连接：虚拟起点 -> 测试卡片

                        connections_list = [{

                            'start_card_id': virtual_start_id,

                            'end_card_id': test_card_id,

                            'type': 'success'

                        }]

                        # 设置虚拟起点作为起始卡片

                        start_card_id = virtual_start_id

                        logger.info(f"[单卡测试] 临时工作流: 虚拟起点({virtual_start_id}) -> 测试卡片({test_card_id})")

                    elif test_mode == 'flow':

                        # 流程测试：虚拟起点 -> 测试卡片 -> 后续完整流程

                        logger.info(f"[流程测试] 创建虚拟起点 -> 卡片 {test_card_id} -> 完整流程")

                        # 序列化所有卡片为字典格式

                        serialized_cards = {}

                        for cid, card_obj in cards_dict.items():

                            if isinstance(card_obj, dict):

                                # 已经是字典

                                serialized_cards[cid] = card_obj

                            else:

                                # TaskCard对象，序列化

                                serialized_cards[cid] = {

                                    'id': cid,

                                    'task_type': card_obj.task_type,

                                    'parameters': copy.deepcopy(card_obj.parameters),

                                    'position': {'x': card_obj.x(), 'y': card_obj.y()}

                                }

                        # 添加虚拟起点

                        serialized_cards[virtual_start_id] = virtual_start_card

                        # 添加虚拟起点到测试卡片的连接

                        virtual_connection = {

                            'start_card_id': virtual_start_id,

                            'end_card_id': test_card_id,

                            'type': 'success'

                        }

                        connections_list = [virtual_connection] + connections_list

                        # 使用序列化的卡片字典

                        cards_dict = serialized_cards

                        # 设置虚拟起点作为起始卡片

                        start_card_id = virtual_start_id

                        logger.info(f"[流程测试] 完整工作流: {len(cards_dict)}张卡片(含虚拟起点), {len(connections_list)}个连接(含虚拟连接)")

                # ----------------------------------------------------

                # --- Create and start the executor ---

                from task_workflow.workflow_vars import workflow_context_key

                workflow_id = workflow_context_key(getattr(actual_task, "task_id", None)) or "default"
                self.executor, self.executor_thread = create_process_workflow_runtime(
                    cards_data=cards_dict,
                    connections_data=connections_list,
                    execution_mode=self.current_execution_mode,
                    images_dir=self.images_dir,
                    workflow_id=workflow_id,
                    workflow_filepath=getattr(actual_task, "filepath", None),
                    start_card_id=start_card_id,
                    start_card_ids=start_card_ids,
                    target_window_title=target_window_title or self.current_target_window_title,
                    target_hwnd=target_hwnd,
                    thread_labels=thread_labels,
                    bound_windows=self.bound_windows,
                    logger_obj=logger,
                    enable_thread_window_binding=not test_mode,
                    single_mode_overrides={"test_mode": test_mode},
                    config=self.config,
                    parent=self,
                )

                if not test_mode and start_card_count > 1:
                    logging.info(
                        "run_workflow: Process workflow executor prepared successfully. threads=%d",
                        len(start_card_ids),
                    )
                else:
                    logging.info(
                        "run_workflow: Single workflow executor prepared successfully. start_card_id=%s, test_mode=%s",
                        start_card_id,
                        test_mode,
                    )

                logging.debug("run_workflow: Process workflow executor created successfully.")

                self._active_execution_task_id = actual_task.task_id

            except Exception as exec_init_e:

                logging.error(f"run_workflow: 创建 WorkflowExecutor 时出错: {exec_init_e}", exc_info=True)

                QMessageBox.critical(self, "错误", f"无法初始化执行器: {exec_init_e}")

                self._reset_run_button() # Reset button on error

                # --- ADDED: Explicit cleanup on executor init error ---

                self.executor = None # Ensure executor ref is cleared

                # We might not have assigned executor_thread yet, but check just in case

                if self.executor_thread:

                     self.executor_thread.deleteLater() # Request deletion if it exists

                     self.executor_thread = None

                # ----------------------------------------------------

                return

            # --- End inner try block ---

            # Print parameters of the starting card for debugging

            if cards_dict:

                start_card_id_for_debug = min(cards_dict.keys())

                start_card = cards_dict.get(start_card_id_for_debug)

                if start_card:

                    # 处理字典和对象两种情况

                    if isinstance(start_card, dict):

                        params = start_card.get('parameters', {})

                    else:

                        params = start_card.parameters

                    logging.debug(f"run_workflow: Parameters for starting card ({start_card_id_for_debug}) before execution: {params}") 

            

            # 检查WorkflowExecutor是否为真正的QObject（支持线程）

            is_qobject_executor = hasattr(self.executor, 'moveToThread') and hasattr(self.executor, 'execution_started')

            if is_qobject_executor:

                logging.debug("run_workflow: Moving executor to thread...")

                self.executor.moveToThread(self.executor_thread)

                # 3. Connect signals/slots

                logging.debug("run_workflow: Connecting signals and slots...")

                self.executor.execution_started.connect(self._handle_execution_started)

                self.executor.card_executing.connect(self._handle_card_executing)

                self.executor.card_finished.connect(self._handle_card_finished)

                if hasattr(self.executor, 'card_ntfy_push_requested'):

                    self.executor.card_ntfy_push_requested.connect(self._publish_forwarded_ntfy_message)

                # self.executor.card_state_reset.connect(self._handle_card_state_reset)  # 注释：executor中未定义此信号，会导致卡死

                self.executor.error_occurred.connect(self._handle_error_occurred)

                self.executor.execution_finished.connect(self._handle_execution_finished)

                # --- ADDED: Connect new signals ---

                self.executor.path_updated.connect(self._handle_path_updated)

                self.executor.param_updated.connect(self._handle_param_updated)

                self.executor.path_resolution_failed.connect(self._handle_path_resolution_failed)

                # --- ADDED: Connect step_details signal ---

                self.executor.step_details.connect(self._update_step_details)

                # --- ADDED: Connect show_warning signal ---

                if hasattr(self.executor, 'show_warning'):

                    self.executor.show_warning.connect(self._show_warning_dialog)

                # --- 浮动窗口信号连接 ---

                if hasattr(self, '_floating_window') and self._floating_window:

                    if hasattr(self.executor, 'step_log'):

                        self.executor.step_log.connect(

                            self._forward_step_log,

                            Qt.ConnectionType.QueuedConnection

                        )

                        logging.info("[浮动窗口] step_log信号已连接到_forward_step_log")

                    else:

                        logging.warning("[浮动窗口] executor没有step_log信号")

                else:

                    logging.warning(f"[浮动窗口] 未连接信号: _floating_window={getattr(self, '_floating_window', None)}")

                # ------------------------------------------

                self.executor_thread.started.connect(self.executor.run)

                # 【修复闪退】创建一个安全的quit方法避免访问已删除的thread

                def safe_quit_thread():

                    try:

                        if hasattr(self, 'executor_thread') and self.executor_thread:

                            self.executor_thread.quit()

                    except (RuntimeError, AttributeError) as e:

                        logging.debug(f"safe_quit_thread: 线程已被删除或无效: {e}")

                self.executor.execution_finished.connect(lambda success, msg: safe_quit_thread())

                # 不使用lambda直接调用executor.deleteLater，改为在_cleanup_references中处理

                # self.executor.execution_finished.connect(lambda success, msg: self.executor.deleteLater())

                self.executor_thread.finished.connect(self.executor_thread.deleteLater)

                # --- ADDED connection for explicit reference cleanup ---

                self.executor_thread.finished.connect(self._cleanup_references)

                # -------------------------------------------------------

                logging.debug("run_workflow: Signals connected.")

            else:

                # 处理stub版本的WorkflowExecutor（打包版本）

                logging.warning("run_workflow: 检测到stub版本的WorkflowExecutor，工作流功能在打包版本中被禁用")

                QMessageBox.information(self, "功能限制",

                                      "工作流执行功能在当前版本中不可用。\n"

                                      "这是为了防止源代码泄露而设计的限制。")

                self._reset_run_button()

                # 清理资源

                self.executor = None

                if self.executor_thread:

                    self.executor_thread.deleteLater()

                    self.executor_thread = None

                self._active_execution_task_id = None

                return

            # 4. Start Thread

            logging.info("run_workflow: Starting thread...")

            # --- Add try block for thread start ---

            try:

                self.executor_thread.start()
                self._runtime_pause_owner = 'executor'
                self._runtime_stop_owner = 'executor'

                logging.info("run_workflow: 工作流执行线程已启动 (调用 thread.start() 成功)")

            except Exception as start_e:

                 logging.error(f"run_workflow: 启动线程时出错: {start_e}", exc_info=True)

                 QMessageBox.critical(self, "错误", f"无法启动执行线程: {start_e}")

                 self._reset_run_button()

                 # 使用 try-finally 确保清理，即使异常也能执行

                 try:

                     if self.executor:

                         # 只有QObject才能调用deleteLater

                         if hasattr(self.executor, 'deleteLater'):

                             self.executor.deleteLater()

                 finally:

                     self.executor = None

                 try:

                     if self.executor_thread:

                          # Don't try to quit/wait if start failed

                          self.executor_thread.deleteLater()

                 finally:

                     self.executor_thread = None

                     self._active_execution_task_id = None

                 return

            # --- End try block for thread start ---

            # --- ADDED: Reset unsaved changes if running a saved workflow ---

            if self.current_save_path:

                logging.debug(f"run_workflow: 工作流已保存 ({self.current_save_path})，运行后重置未保存状态。")

                self.unsaved_changes = False

                self._update_main_window_title()

            # -----------------------------------------------------------

        except Exception as e: # --- Catch errors in the outer block ---

            logging.error(f"run_workflow: 设置执行时发生意外错误: {e}", exc_info=True)

            QMessageBox.critical(self, "错误", f"准备执行工作流时出错: {e}")

            self._reset_run_button() # Ensure button is reset

            # Clean up any potentially created thread/executor objects

            if self.executor:

                # 只有QObject才能调用deleteLater

                if hasattr(self.executor, 'deleteLater'):

                    self.executor.deleteLater()

                self.executor = None

            if self.executor_thread:

                if self.executor_thread.isRunning():

                    self.executor_thread.quit()

                    self.executor_thread.wait()

                self.executor_thread.deleteLater()

                self.executor_thread = None

            logging.warning("run_workflow: 在主 try 块中捕获到错误，确保 executor 和 thread 已清理。") # ADDED Log
