import logging

logger = logging.getLogger(__name__)


class MainWindowWorkflowSwitchTabsMixin:

    def _on_current_workflow_changed(self, task_id: int):

        """当前工作流标签页变化"""

        logger.info(f"切换到工作流标签页: task_id={task_id}")

        # 更新 workflow_view 引用

        old_view = self.workflow_view

        if not self._is_qobject_alive(old_view):

            old_view = None

            self.workflow_view = None

        try:

            from task_workflow.workflow_context import export_global_vars

            from task_workflow.workflow_vars import has_runtime_variables

            from task_workflow.workflow_vars import workflow_context_key

            if old_view is not None and hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                old_task_id = None

                for task_id_candidate, view in self.workflow_tab_widget.task_views.items():

                    if view is old_view:

                        old_task_id = task_id_candidate

                        break

                if old_task_id is not None and hasattr(self, 'task_manager'):

                    task = self.task_manager.get_task(old_task_id)

                    if task:

                        if not isinstance(task.workflow_data, dict):

                            task.workflow_data = {}

                        old_workflow_id = workflow_context_key(old_task_id) or "default"

                        runtime_variables = export_global_vars(old_workflow_id)

                        existing_variables = task.workflow_data.get("variables")

                        if has_runtime_variables(runtime_variables) or not isinstance(existing_variables, dict):

                            task.workflow_data["variables"] = runtime_variables

                        from task_workflow.workflow_vars import update_context_from_variables

                        update_context_from_variables(old_task_id, task.workflow_data.get("variables"))

        except Exception as var_store_err:

            logger.warning(f"同步旧工作流变量失败: {var_store_err}")

        current_view = None

        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

            try:

                current_view = self.workflow_tab_widget.get_current_workflow_view()

            except Exception as get_view_err:

                logger.warning(f"获取当前 WorkflowView 失败: {get_view_err}")

                current_view = None

        if not self._is_qobject_alive(current_view):

            current_view = None

        self.workflow_view = current_view

        logger.info(f"   旧WorkflowView: {old_view}")

        logger.info(f"   新WorkflowView: {self.workflow_view}")

        try:

            from task_workflow.workflow_context import import_global_vars, prune_orphan_vars

            from task_workflow.workflow_vars import workflow_context_key

            variables_data = None

            task = None

            if hasattr(self, 'task_manager'):

                task = self.task_manager.get_task(task_id)

                if task and isinstance(task.workflow_data, dict):

                    variables_data = task.workflow_data.get("variables")

                    try:

                        from task_workflow.runtime_var_store import is_storage_manifest

                        if variables_data is not None and not is_storage_manifest(variables_data):

                            task.workflow_data.pop("variables", None)

                            variables_data = None

                            logger.info("切换工作流时已清空旧版内嵌变量: task_id=%s", task_id)

                    except Exception as legacy_var_clear_err:

                        logger.warning(f"清理旧版内嵌变量失败: {legacy_var_clear_err}")

            workflow_id = workflow_context_key(task_id) or "default"

            import_global_vars(variables_data, workflow_id=workflow_id)

            try:

                if task:

                    from task_workflow.runtime_var_store import (

                        STORAGE_KIND,

                        build_task_key,

                        is_storage_manifest,

                        load_runtime_snapshot,

                        save_runtime_snapshot,

                    )

                    from task_workflow.workflow_context import export_global_vars, get_workflow_context

                    from task_workflow.workflow_vars import has_runtime_variables

                    context = get_workflow_context(workflow_id)

                    task_key = build_task_key(

                        filepath=getattr(task, "filepath", None),

                        task_id=getattr(task, "task_id", None),

                        task_name=getattr(task, "name", None),

                    )

                    migrated_manifest = None

                    if is_storage_manifest(variables_data):

                        manifest_data = dict(variables_data)

                        manifest_task_key = str(manifest_data.get("task_key") or "").strip() or task_key

                        context.bind_runtime_storage(

                            task_key=manifest_task_key,

                            manifest=manifest_data,

                            dirty=False,

                        )

                    else:

                        context.bind_runtime_storage(task_key=task_key)

                        runtime_snapshot = export_global_vars(workflow_id)

                        if has_runtime_variables(runtime_snapshot):

                            migrated_manifest = save_runtime_snapshot(task_key, runtime_snapshot)

                        else:

                            existing_vars, _ = load_runtime_snapshot(task_key)

                            if existing_vars:

                                migrated_manifest = {

                                    "storage": STORAGE_KIND,

                                    "task_key": task_key,

                                    "count": len(existing_vars),

                                }

                    if isinstance(migrated_manifest, dict):

                        context.bind_runtime_storage(

                            task_key=task_key,

                            manifest=dict(migrated_manifest),

                            dirty=False,

                        )

                        if isinstance(task.workflow_data, dict):

                            task.workflow_data["variables"] = migrated_manifest

                            variables_data = task.workflow_data.get("variables")

            except Exception as runtime_var_bind_err:

                logger.warning(f"绑定运行变量数据库上下文失败: {runtime_var_bind_err}")

            if self.workflow_view is not None and self._is_qobject_alive(self.workflow_view):

                prune_orphan_vars(self.workflow_view.cards.keys(), workflow_id=workflow_id)

        except Exception as var_restore_err:

            logger.warning(f"恢复工作流变量失败：{var_restore_err}")

        # 连接信号（如果需要）

        if self.workflow_view is not None:

            if not self._is_qobject_alive(self.workflow_view):

                logger.warning("当前 WorkflowView 已销毁，跳过切换后同步")

                self.workflow_view = None

                logger.debug(f"当前工作流已切换到任务ID: {task_id}")

                return

            # 确保WorkflowView可见并激活

            self.workflow_view.setEnabled(True)

            self.workflow_view.setVisible(True)

            # 关键修复：强制恢复画布拖拽模式

            from PySide6.QtWidgets import QGraphicsView

            current_drag_mode = self.workflow_view.dragMode()

            logger.info(f"   当前拖拽模式: {current_drag_mode}")

            # 确保设置为ScrollHandDrag（画布可拖拽）

            self.workflow_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

            logger.info(f"   已强制设置拖拽模式为: ScrollHandDrag")

            # 诊断信息：场景大小和视口大小

            scene_rect = self.workflow_view.sceneRect()

            viewport_rect = self.workflow_view.viewport().rect()

            cards_count = len(self.workflow_view.cards)

            logger.info(f"   场景大小: {scene_rect.width()}x{scene_rect.height()}")

            logger.info(f"   视口大小: {viewport_rect.width()}x{viewport_rect.height()}")

            logger.info(f"   卡片数量: {cards_count}")

            logger.info(f"   横向滚动条可见: {self.workflow_view.horizontalScrollBar().isVisible()}")

            logger.info(f"   纵向滚动条可见: {self.workflow_view.verticalScrollBar().isVisible()}")

            # 关键修复：强制重新计算场景大小

            if self.workflow_view.scene.items():

                items_rect = self.workflow_view.scene.itemsBoundingRect()

                # 添加padding确保有足够的拖动空间

                padding = 500

                padded_rect = items_rect.adjusted(-padding, -padding, padding, padding)

                self.workflow_view.scene.setSceneRect(padded_rect)

                logger.info(f"   已重新设置场景大小: {padded_rect.width()}x{padded_rect.height()}")

                # 强制更新滚动条

                self.workflow_view.viewport().update()

                new_hbar = self.workflow_view.horizontalScrollBar().isVisible()

                new_vbar = self.workflow_view.verticalScrollBar().isVisible()

                logger.info(f"   更新后滚动条: 横向={new_hbar}, 纵向={new_vbar}")

            else:

                logger.warning(f"   场景中没有items，无法调整场景大小")

            # 连接场景选择变化信号

            try:

                # 先断开旧的连接，避免重复连接

                if old_view is not None and old_view is not self.workflow_view:

                    self._disconnect_workflow_selection_signal(old_view)

                self.workflow_view.scene.selectionChanged.connect(self.update_status_bar_for_selection)

                logger.debug("场景选择变化信号已连接")

            except Exception as e:

                logger.error(f"连接场景选择变化信号失败: {e}")

            # 更新参数面板

            self._connect_parameter_panel_signals()

            # 修复：连接card_added信号，以便新增卡片能自动连接参数面板信号

            try:

                # 断开旧 WorkflowView 的信号，避免重复连接

                if old_view is not None and old_view is not self.workflow_view:

                    if old_view.property("_mw_workflow_signals_connected"):

                        try:

                            old_view.card_added.disconnect(self._on_card_added)

                            logger.debug("已断开旧 WorkflowView 的 card_added 信号")

                        except:

                            pass

                        # 断开旧测试执行信号

                        try:

                            old_view.test_card_execution_requested.disconnect(self._handle_test_card_execution)

                            old_view.test_flow_execution_requested.disconnect(self._handle_test_flow_execution)

                            logger.info("已断开旧 WorkflowView 测试执行信号")

                        except:

                            pass

                        old_view.setProperty("_mw_workflow_signals_connected", False)

                # 使用 UniqueConnection 防止重复绑定

                from PySide6.QtCore import Qt

                if not self.workflow_view.property("_mw_workflow_signals_connected"):

                    self.workflow_view.card_added.connect(self._on_card_added, Qt.ConnectionType.UniqueConnection)

                    logger.debug("card_added 已连接到 _on_card_added (UniqueConnection)")

                    # 测试执行信号也使用 UniqueConnection

                    self.workflow_view.test_card_execution_requested.connect(self._handle_test_card_execution, Qt.ConnectionType.UniqueConnection)

                    self.workflow_view.test_flow_execution_requested.connect(self._handle_test_flow_execution, Qt.ConnectionType.UniqueConnection)

                    self.workflow_view.setProperty("_mw_workflow_signals_connected", True)

            except Exception as e:

                logger.error(f"连接card_added信号失败: {e}", exc_info=True)

            logger.info(f"WorkflowView切换完成，可拖动: {self.workflow_view.isEnabled()}")

        logger.debug(f"当前工作流已切换到任务ID: {task_id}")

    def _disconnect_workflow_selection_signal(self, workflow_view) -> None:

        """断开指定 WorkflowView 的 selectionChanged 槽连接。"""

        if not self._is_qobject_alive(workflow_view):

            return

        try:

            scene_attr = getattr(workflow_view, "scene", None)

        except RuntimeError:

            return

        except Exception:

            scene_attr = None

        if scene_attr is None:

            return

        if callable(scene_attr):

            try:

                scene = scene_attr()

            except RuntimeError:

                return

            except Exception:

                scene = None

        else:

            scene = scene_attr

        if not self._is_qobject_alive(scene):

            return

        selection_changed = getattr(scene, "selectionChanged", None)

        if selection_changed is None:

            return

        try:

            selection_changed.disconnect(self.update_status_bar_for_selection)

        except (TypeError, RuntimeError):

            pass

        except Exception:

            pass

    def _show_welcome_hint(self):

        """显示首次使用提示"""

        # 检查是否已经有任务

        if self.task_manager.get_task_count() == 0:

            # 显示友好提示

            hint_text = """

            <h3>欢迎使用多任务工作流系统！</h3>

            <p>现在您可以同时管理多个工作流任务。</p>

            <p><b>快速开始：</b></p>

            <ul>

                <li>点击标签栏的 <b>"+"</b> 按钮导入工作流</li>

                <li>或使用菜单 <b>"加载配置"</b> 导入任务</li>

            </ul>

            <p>详细说明请查看 <i>docs/多任务系统使用说明.md</i></p>

            """

            # 多任务模式：不再显示提示文字，保持界面简洁

            self.step_detail_label.setText("")

    def _is_qobject_alive(self, obj) -> bool:

        """判断 Qt 对象是否仍然有效，避免访问已销毁的 C++ 对象。"""

        if obj is None:

            return False

        try:

            from shiboken6 import isValid

            return bool(isValid(obj))

        except Exception:

            # 兼容未安装/导入失败场景，退化为一次轻量访问校验

            try:

                obj.metaObject()

                return True

            except RuntimeError:

                return False

            except Exception:

                return True
            pass

    def _on_task_count_changed(self, task_id: int = None):

        """任务数量变化时，更新UI元素的显示/隐藏"""

        task_count = len(self.task_manager.get_all_tasks())

        logger.info(f"任务数量变化: 当前任务数={task_count}")

        if task_count == 0 and getattr(self, "workflow_view", None) is not None:

            # 最后一个标签页关闭后，主窗口不能继续持有旧 WorkflowView 引用。

            self._disconnect_workflow_selection_signal(self.workflow_view)

            self.workflow_view = None

        # 【修复】只在没有执行器运行时更新状态栏

        # 执行中时由 _update_step_detail_for_card 控制显示

        if not (hasattr(self, 'executor') and self.executor is not None):

            self._update_status_bar()
