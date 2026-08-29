import logging
import os

from PySide6.QtWidgets import QMessageBox

from utils.window.hwnd_utils import as_hwnd
from task_workflow.thread_start import is_thread_start_task_type

logger = logging.getLogger(__name__)


class MainWindowExecutionHelperMixin:
    def _merge_workflows(self, tasks):

        """

        合并多个工作流任务为一个工作流（并行执行）

        Args:

            tasks: 工作流任务列表

        Returns:

            合并后的工作流数据字典，失败返回None

        """

        logger.info(f"开始合并 {len(tasks)} 个工作流任务（并行模式）")

        try:

            import copy

            # 初始化合并后的工作流数据

            merged_workflow = {

                "cards": [],

                "connections": [],

                # 工具 关键修复：添加必要的配置信息

                "task_modules": self.task_modules,  # 任务模块字典

                "images_dir": self.images_dir,      # 图片目录

            }

            # 记录卡片ID映射，避免冲突（旧ID -> 新ID）

            next_card_id = 1  # 从1开始分配新ID（0保留给起点）

            # 记录起点卡片

            start_card = None

            # 记录每个工作流的第一个卡片ID（用于并行连接）

            workflow_first_cards = []

            # 遍历所有任务

            for task_index, task in enumerate(tasks):

                logger.info(f"处理第 {task_index + 1} 个工作流: '{task.name}'")

                workflow_data = task.workflow_data

                if not workflow_data or not workflow_data.get("cards"):

                    logger.warning(f"工作流 '{task.name}' 为空，跳过")

                    continue

                cards = workflow_data.get("cards", [])

                connections = workflow_data.get("connections", [])

                logger.info(f"  工作流 '{task.name}' 包含 {len(cards)} 个卡片，{len(connections)} 个连接")

                # 为当前工作流创建ID映射

                current_mapping = {}

                current_first_id = None

                # 处理卡片

                for card in cards:

                    old_id = card.get("id")

                    # 检查是否是线程起点卡片

                    if is_thread_start_task_type(card.get("task_type")):

                        if start_card is None:

                            start_card = copy.deepcopy(card)

                            logger.info("  找到线程起点卡片")

                        else:

                            logger.warning("  跳过额外的线程起点卡片")

                        continue

                    # 为卡片分配新ID

                    new_id = next_card_id

                    next_card_id += 1

                    # 记录ID映射

                    current_mapping[old_id] = new_id

                    # 记录第一个卡片ID

                    if current_first_id is None:

                        current_first_id = new_id

                    # 创建新卡片

                    new_card = copy.deepcopy(card)

                    new_card["id"] = new_id

                    # 添加到合并后的工作流

                    merged_workflow["cards"].append(new_card)

                    logger.debug(f"    卡片 {old_id} -> {new_id}: {card.get('task_type')}")

                # 处理连接关系

                for conn in connections:

                    source_id = conn.get("source")

                    target_id = conn.get("target")

                    # 跳过起点卡片的连接

                    if source_id == 0:  # 起点卡片ID通常为0

                        continue

                    # 映射新的ID

                    new_source = current_mapping.get(source_id)

                    new_target = current_mapping.get(target_id)

                    # 如果源或目标卡片被跳过（如起点），则跳过这个连接

                    if new_source is None or new_target is None:

                        continue

                    new_conn = copy.deepcopy(conn)

                    new_conn["source"] = new_source

                    new_conn["target"] = new_target

                    merged_workflow["connections"].append(new_conn)

                    logger.debug(f"    连接 {source_id}->{target_id} 映射为 {new_source}->{new_target}")

                # 记录当前工作流的第一个卡片（用于并行连接）

                if current_first_id is not None:

                    workflow_first_cards.append(current_first_id)

                    logger.info(f"  工作流 '{task.name}' 第一个卡片: {current_first_id}")

            # 处理起点卡片

            if start_card is None:

                logger.error("合并失败: 没有找到起点卡片")

                return None

            # 添加起点卡片

            start_card["id"] = 0

            merged_workflow["cards"].insert(0, start_card)

            # 并行连接：起点同时连接到所有工作流的第一个卡片

            if len(workflow_first_cards) > 0:

                for first_card_id in workflow_first_cards:

                    merged_workflow["connections"].append({

                        "source": 0,

                        "target": first_card_id

                    })

                    logger.info(f"创建并行连接: 起点(0) -> 工作流起始卡片({first_card_id})")

            logger.info(f"合并完成（并行模式）: 总计 {len(merged_workflow['cards'])} 个卡片，{len(merged_workflow['connections'])} 个连接")

            logger.info(f"  起点并行连接到 {len(workflow_first_cards)} 个工作流")

            return merged_workflow

        except Exception as e:

            logger.error(f"合并工作流失败: {e}", exc_info=True)

            return None

    def _save_before_execution(self):

        """执行前保存并备份所有标签页的工作流，处理同名冲突"""

        all_tasks = self.task_manager.get_all_tasks()

        logger.info(f"_save_before_execution: 保存和备份所有标签页的工作流，共 {len(all_tasks)} 个")

        if not all_tasks:

            return True

        # 收集所有需要保存的任务信息，并获取最新工作流数据

        tasks_to_save = []

        for task_item in all_tasks:

            workflow_view = self.workflow_tab_widget.task_views.get(task_item.task_id)

            latest_workflow_data = None

            if workflow_view:

                logger.info(f"从画布获取最新工作流数据: {task_item.name}")

                latest_workflow_data = workflow_view.serialize_workflow()

                task_item.update_workflow_data(latest_workflow_data)

            else:

                logger.warning(f"无法获取任务 '{task_item.name}' 的 WorkflowView，使用现有数据")

            tasks_to_save.append((task_item, latest_workflow_data))

        # 处理没有保存路径的任务

        tasks_without_path = [(t, d) for t, d in tasks_to_save if not t.filepath]

        if tasks_without_path:

            # 让用户选择保存目录

            from PySide6.QtWidgets import QFileDialog

            save_dir = QFileDialog.getExistingDirectory(

                self,

                "选择保存目录（用于保存未命名的工作流）",

                ""

            )

            if not save_dir:

                QMessageBox.warning(self, "保存取消", "未选择保存目录，执行已取消")

                return False

            # 为没有路径的任务分配文件名

            for task, _ in tasks_without_path:

                base_name = task.name if task.name else "工作流"

                base_name = os.path.splitext(base_name)[0]

                filepath = os.path.join(save_dir, f"{base_name}.lca")

                task.filepath = filepath

                task.name = os.path.basename(filepath)

        # 检测同名冲突并处理

        filepath_count = {}

        for task, workflow_data in tasks_to_save:

            filepath = task.filepath

            if filepath in filepath_count:

                filepath_count[filepath].append((task, workflow_data))

            else:

                filepath_count[filepath] = [(task, workflow_data)]

        # 处理冲突

        for filepath, task_list in filepath_count.items():

            if len(task_list) > 1:

                # 有冲突，重命名

                base_path = os.path.splitext(filepath)[0]

                for i, (task, _) in enumerate(task_list):

                    if i == 0:

                        # 第一个保持原名

                        pass

                    else:

                        # 后续的添加序号

                        new_filepath = f"{base_path}({i}).lca"

                        task.filepath = new_filepath

                        task.name = os.path.basename(new_filepath)

                        logger.info(f"同名冲突，重命名任务: {filepath} -> {new_filepath}")

        # 执行保存和备份

        saved_count = 0

        backup_failed_tasks = []

        for task_item, latest_workflow_data in tasks_to_save:

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

        return True  # 总是返回True，即使部分失败也继续执行

    def _validate_bound_windows_on_startup(self):

        """启动时按窗口特征刷新句柄。找不到也不删除绑定，避免目标进程未启动时把配置清掉。"""

        if not self.bound_windows:

            return

        logger.info(f"启动时验证绑定窗口，配置中有 {len(self.bound_windows)} 个窗口")

        from utils.window.window_identity import is_window_alive, refresh_bound_windows

        original_hwnds = [window_info.get('hwnd') for window_info in self.bound_windows]
        changed = refresh_bound_windows(self.bound_windows)

        alive_count = 0
        for window_info in self.bound_windows:
            window_title = window_info.get('title', '')
            hwnd = as_hwnd(window_info.get('hwnd', 0))
            if is_window_alive(hwnd):
                alive_count += 1
                logger.info(f"窗口有效: {window_title} (HWND: {hwnd})")
            else:
                logger.warning(f"窗口暂未重连，已保留绑定: {window_title}")

        if changed or [window_info.get('hwnd') for window_info in self.bound_windows] != original_hwnds:
            logger.info(f"窗口验证完成: 已刷新句柄，当前 {alive_count}/{len(self.bound_windows)} 个窗口在线")
            self._store_runtime_bound_windows_to_config()
        else:
            logger.info(f"窗口验证完成，所有 {len(self.bound_windows)} 个绑定均已保留")
