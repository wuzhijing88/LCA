from .workflow_view_common import *
from ..system_parts.message_box_translator import show_warning_box


class WorkflowViewIdentityMixin:

    def handle_rename_card(self, card: TaskCard):
        """处理卡片备注名称功能"""
        current_name = card.custom_name if card.custom_name else ""

        # 创建自定义输入对话框以支持中文按钮
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("备注卡片名称")
        dialog.setModal(True)
        dialog.resize(350, 150)

        layout = QVBoxLayout(dialog)

        # 添加说明标签
        label = QLabel(f"为卡片 '{card.task_type}' (ID: {card.card_id}) 设置备注名称：\n\n留空则使用默认名称")
        layout.addWidget(label)

        # 添加输入框
        line_edit = QLineEdit(current_name)
        layout.addWidget(line_edit)

        # 添加按钮
        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")

        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        # è¿æ¥ä¿¡å·
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)

        # 设置默认按钮和焦点
        ok_button.setDefault(True)
        line_edit.setFocus()

        # 显示对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = line_edit.text()
            # 注释已清理（原注释编码损坏）
            if text.strip():
                new_name = text.strip()
                card.set_custom_name(new_name)
                debug_print(f"卡片 {card.card_id} 备注名称已设置为: '{new_name}'")
            else:
                card.set_custom_name(None)
                debug_print(f"卡片 {card.card_id} 备注名称已清除，恢复默认显示")

            if hasattr(self, 'main_window') and self.main_window:
                if hasattr(self.main_window, '_on_card_custom_name_changed'):
                    self.main_window._on_card_custom_name_changed(card.card_id, text.strip())

    def handle_change_card_id(self, card: TaskCard):
        """处理修改卡片ID功能"""
        old_id = card.card_id

        # 创建自定义输入对话框以支持中文按钮
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QSpinBox, QPushButton, QHBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("修改卡片ID")
        dialog.setModal(True)
        dialog.resize(350, 180)

        layout = QVBoxLayout(dialog)

        # 添加说明标签
        label = QLabel(f"当前卡片ID: {old_id}\n请输入新的ID (0-9999)：\n\n注意：ID 0 通常用于起点任务")
        layout.addWidget(label)

        # 添加数字输入框
        spin_box = NoWheelSpinBox()
        spin_box.setRange(0, 9999)
        spin_box.setValue(old_id)
        layout.addWidget(spin_box)

        # 添加按钮
        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")

        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        # è¿æ¥ä¿¡å·
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)

        # 设置默认按钮和焦点
        ok_button.setDefault(True)
        spin_box.setFocus()

        # 显示对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_id = spin_box.value()
            if new_id != old_id:
                # 注释已清理（原注释编码损坏）
                if new_id in self.cards:
                    # 注释已清理（原注释编码损坏）
                    existing_card = self.cards[new_id]

                    # 创建自定义消息框以支持中文按钮
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle("ID冲突")
                    msg_box.setText(f"ID {new_id} 已被卡片 '{existing_card.task_type}' 使用。\n\n是否要与该卡片对换ID？\n\n"
                                   f"• 卡片 '{card.task_type}' (ID: {old_id}) → ID: {new_id}\n"
                                   f"• 卡片 '{existing_card.task_type}' (ID: {new_id}) → ID: {old_id}")
                    msg_box.setIcon(QMessageBox.Icon.Question)
                    msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    msg_box.setDefaultButton(QMessageBox.StandardButton.No)

                    # 设置按钮中文文本
                    yes_button = msg_box.button(QMessageBox.StandardButton.Yes)
                    no_button = msg_box.button(QMessageBox.StandardButton.No)
                    if yes_button: yes_button.setText("是")
                    if no_button: no_button.setText("否")

                    reply = msg_box.exec()

                    if reply == QMessageBox.StandardButton.Yes:
                        # 执行ID对换
                        self._swap_card_ids(card, existing_card)
                        debug_print(f"卡片ID对换完成: {old_id} ↔ {new_id}")

                        # 更新序列显示
                        self.update_card_sequence_display()

                        # 创建自定义信息框以支持中文按钮
                        info_box = QMessageBox(self)
                        info_box.setWindowTitle("ID对换完成")
                        info_box.setText(f"卡片ID对换成功：\n\n"
                                        f"• '{card.task_type}' 的ID: {old_id} → {new_id}\n"
                                        f"• '{existing_card.task_type}' 的ID: {new_id} → {old_id}")
                        info_box.setIcon(QMessageBox.Icon.Information)
                        info_box.setStandardButtons(QMessageBox.StandardButton.Ok)

                        # 设置按钮中文文本
                        ok_button = info_box.button(QMessageBox.StandardButton.Ok)
                        if ok_button: ok_button.setText("确定")

                        info_box.exec()
                else:
                    # 新ID不冲突，直接修改
                    self._change_card_id(card, new_id)
                    debug_print(f"卡片ID修改完成: {old_id} → {new_id}")

                    # 更新序列显示
                    self.update_card_sequence_display()

                    # 创建自定义信息框以支持中文按钮
                    info_box = QMessageBox(self)
                    info_box.setWindowTitle("ID修改完成")
                    info_box.setText(f"卡片 '{card.task_type}' 的ID已从 {old_id} 修改为 {new_id}")
                    info_box.setIcon(QMessageBox.Icon.Information)
                    info_box.setStandardButtons(QMessageBox.StandardButton.Ok)

                    # 设置按钮中文文本
                    ok_button = info_box.button(QMessageBox.StandardButton.Ok)
                    if ok_button: ok_button.setText("确定")

                    info_box.exec()

    def _swap_card_ids(self, card1: TaskCard, card2: TaskCard):
        """对换两个卡片的ID"""
        coordinate_snapshot = self._snapshot_coordinate_parameters_for_id_change()
        old_id1 = card1.card_id
        old_id2 = card2.card_id

        # 临时移除卡片
        del self.cards[old_id1]
        del self.cards[old_id2]

        # 更新卡片ID
        card1.card_id = old_id2
        card2.card_id = old_id1

        # 同步默认结果变量名（仅同步自动生成的默认命名，不覆盖用户自定义名称）
        self._sync_result_variable_name_for_card_id_change(card1, old_id1, card1.card_id)
        self._sync_result_variable_name_for_card_id_change(card2, old_id2, card2.card_id)

        # 更新标题显示
        if card1.custom_name:
            card1.title = f"{card1.custom_name} (ID: {card1.card_id})"
        else:
            card1.title = f"{card1.task_type} (ID: {card1.card_id})"

        if card2.custom_name:
            card2.title = f"{card2.custom_name} (ID: {card2.card_id})"
        else:
            card2.title = f"{card2.task_type} (ID: {card2.card_id})"

        # 重新添加到字典
        self.cards[card1.card_id] = card1
        self.cards[card2.card_id] = card2

        # 注释已清理（原注释编码损坏）
        self._update_card_references(old_id1, card1.card_id)
        self._update_card_references(old_id2, card2.card_id)
        self._restore_coordinate_parameters_after_id_change(coordinate_snapshot)

        # 重新绘制卡片
        card1.update()
        card2.update()

    def _change_card_id(self, card: TaskCard, new_id: int):
        """修改单个卡片的ID"""
        coordinate_snapshot = self._snapshot_coordinate_parameters_for_id_change()
        old_id = card.card_id

        # 移除鏃х殑鏄犲皠
        del self.cards[old_id]

        # 更新卡片ID
        card.card_id = new_id

        # 同步默认结果变量名（仅同步自动生成的默认命名，不覆盖用户自定义名称）
        self._sync_result_variable_name_for_card_id_change(card, old_id, new_id)

        # 更新标题显示
        if card.custom_name:
            card.title = f"{card.custom_name} (ID: {card.card_id})"
        else:
            card.title = f"{card.task_type} (ID: {card.card_id})"

        # 添加新的映射
        self.cards[new_id] = card

        # 注释已清理（原注释编码损坏）
        self._update_card_references(old_id, new_id)
        self._restore_coordinate_parameters_after_id_change(coordinate_snapshot)

        # 重新绘制卡片
        card.update()

    def _sync_result_variable_name_for_card_id_change(self, card: TaskCard, old_id: int, new_id: int):
        """卡片 ID 变更时，仅同步默认命名，不覆盖自定义结果变量名。"""
        try:
            if not card or not hasattr(card, 'parameters'):
                return

            params = card.parameters or {}
            key = 'save_result_variable_name'
            current_name = str(params.get(key, '') or '').strip()
            new_name = f"卡片{new_id}结果"

            if current_name:
                is_default_name = False
                if hasattr(card, "_is_default_result_variable_name"):
                    try:
                        is_default_name = bool(card._is_default_result_variable_name(current_name))
                    except Exception:
                        is_default_name = False
                if not is_default_name:
                    is_default_name = bool(re.fullmatch(r"卡片\d+结果", current_name))
                if not is_default_name:
                    return

            if current_name == new_name:
                return

            params[key] = new_name

            # 注释已清理（原注释编码损坏）
            if current_name:
                try:
                    from task_workflow.workflow_context import get_workflow_context
                    context = get_workflow_context()
                    global_vars = dict(getattr(context, 'global_vars', {}) or {})
                    stale_names = []
                    for var_name in global_vars.keys():
                        var_name = str(var_name or '').strip()
                        if var_name == current_name or var_name.startswith(f"{current_name}."):
                            stale_names.append(var_name)
                    for var_name in stale_names:
                        try:
                            context.remove_global_var(var_name)
                        except Exception:
                            pass
                except Exception:
                    pass

            # 同步到参数面板（如果当前选中的就是该卡片）
            if hasattr(self, 'main_window') and self.main_window:
                panel = getattr(self.main_window, 'parameter_panel', None)
                if panel and getattr(panel, 'current_card_id', None) == card.card_id:
                    try:
                        panel.current_parameters[key] = new_name
                    except Exception:
                        pass

            logger.info(
                f"[卡片ID强制同步] 卡片 {old_id} -> {new_id}，"
                f"结果变量名: {current_name or '<空>'} -> {new_name}"
            )
        except Exception as exc:
            logger.debug(f"[卡片ID同步] 同步结果变量名失败: {exc}")

    def _cleanup_jump_target_references(self, deleted_card_id: int):
        """清理所有卡片中指向被删除卡片的跳转参数"""
        debug_print(f"    [CLEANUP_JUMP] Cleaning jump target references to card {deleted_card_id}")

        cards_updated = []
        for card_id, card in self.cards.items():
            if card_id == deleted_card_id:
                continue  # 跳过被删除的卡片本身

            updated = False

            # 注释已清理（原注释编码损坏）
            if card.parameters.get('success_jump_target_id') == deleted_card_id:
                debug_print(f"      Clearing success_jump_target_id in card {card_id}")
                card.parameters['success_jump_target_id'] = None
                # 同时重置相关的动作参数
                if card.parameters.get('on_success') == '跳转到步骤':
                    card.parameters['on_success'] = '执行下一步'
                    debug_print(f"      Reset on_success action to '执行下一步' in card {card_id}")
                updated = True

            # 注释已清理（原注释编码损坏）
            if card.parameters.get('failure_jump_target_id') == deleted_card_id:
                debug_print(f"      Clearing failure_jump_target_id in card {card_id}")
                card.parameters['failure_jump_target_id'] = None
                # 同时重置相关的动作参数
                if card.parameters.get('on_failure') == '跳转到步骤':
                    card.parameters['on_failure'] = '执行下一步'
                    debug_print(f"      Reset on_failure action to '执行下一步' in card {card_id}")
                updated = True

            # 注释已清理（原注释编码损坏）
            for param_name, param_value in card.parameters.items():
                if param_name.endswith('_jump_target_id') and param_value == deleted_card_id:
                    debug_print(f"      Clearing {param_name} in card {card_id}")
                    card.parameters[param_name] = None
                    updated = True

            if updated:
                cards_updated.append(card_id)
                card.update()  # 更新卡片显示
                debug_print(f"      Updated card {card_id} parameters and display")

        if cards_updated:
            debug_print(f"    [CLEANUP_JUMP] Updated {len(cards_updated)} cards: {cards_updated}")
            logger.info(f"清理了 {len(cards_updated)} 个卡片中指向已删除卡片 {deleted_card_id} 的跳转参数")
        else:
            debug_print(f"    [CLEANUP_JUMP] No cards had jump target references to card {deleted_card_id}")

    def _validate_and_cleanup_jump_targets(self):
        """验证并清理所有无效的跳转目标参数"""
        debug_print(f"    [VALIDATE_JUMP] Validating jump target parameters...")
        debug_print(f"    [VALIDATE_JUMP] Valid card IDs in scene: {list(self.cards.keys())}")

        valid_card_ids = set(self.cards.keys())
        cards_updated = []

        for card_id, card in self.cards.items():
            updated = False

            # 注释已清理（原注释编码损坏）
            success_target = card.parameters.get('success_jump_target_id')
            if success_target is not None:
                debug_print(f"      Card {card_id}: success_jump_target_id = {success_target}")
                if success_target not in valid_card_ids:
                    logger.warning(f"Card {card_id} has invalid success_jump_target_id {success_target} - clearing it")
                    debug_print(f"      Invalid success_jump_target_id {success_target} in card {card_id}, clearing...")
                    card.parameters['success_jump_target_id'] = None
                    if card.parameters.get('on_success') == '跳转到步骤':
                        card.parameters['on_success'] = '执行下一步'
                        debug_print(f"      Reset on_success action to '执行下一步' in card {card_id}")
                    updated = True
                else:
                    debug_print(f"      ✓ Valid success_jump_target_id {success_target} in card {card_id}")

            # 注释已清理（原注释编码损坏）
            failure_target = card.parameters.get('failure_jump_target_id')
            if failure_target is not None:
                debug_print(f"      Card {card_id}: failure_jump_target_id = {failure_target}")
                if failure_target not in valid_card_ids:
                    logger.warning(f"Card {card_id} has invalid failure_jump_target_id {failure_target} - clearing it")
                    debug_print(f"      Invalid failure_jump_target_id {failure_target} in card {card_id}, clearing...")
                    card.parameters['failure_jump_target_id'] = None
                    if card.parameters.get('on_failure') == '跳转到步骤':
                        card.parameters['on_failure'] = '执行下一步'
                        debug_print(f"      Reset on_failure action to '执行下一步' in card {card_id}")
                    updated = True
                else:
                    debug_print(f"      ✓ Valid failure_jump_target_id {failure_target} in card {card_id}")

            # 注释已清理（原注释编码损坏）
            for param_name, param_value in list(card.parameters.items()):
                if param_name.endswith('_jump_target_id') and param_value is not None:
                    if param_value not in valid_card_ids:
                        debug_print(f"      Invalid {param_name} {param_value} in card {card_id}, clearing...")
                        card.parameters[param_name] = None
                        updated = True

            if updated:
                cards_updated.append(card_id)
                card.update()  # 更新卡片显示
                debug_print(f"      Updated card {card_id} parameters and display")

        if cards_updated:
            debug_print(f"    [VALIDATE_JUMP] Cleaned invalid jump targets in {len(cards_updated)} cards: {cards_updated}")
            logger.info(f"清理了 {len(cards_updated)} 个卡片中的无效跳转参数")
        else:
            debug_print(f"    [VALIDATE_JUMP] All jump target parameters are valid")

    def _update_card_references(self, old_id: int, new_id: int):
        """更新所有卡片中引用指定 ID 的参数。"""
        if old_id == new_id:
            return

        def _is_card_reference_param(param_name: Any) -> bool:
            if not isinstance(param_name, str):
                return False
            return (
                param_name == 'success_jump_target_id'
                or param_name == 'failure_jump_target_id'
                or param_name.endswith('_jump_target_id')
                or param_name.endswith('_card_id')
            )

        for card in self.cards.values():
            if not hasattr(card, 'parameters') or not isinstance(card.parameters, dict):
                continue

            updated = False
            for param_name, param_value in list(card.parameters.items()):
                if not _is_card_reference_param(param_name):
                    continue

                if param_value == old_id:
                    card.parameters[param_name] = new_id
                    updated = True
                    debug_print(f"更新卡片 {card.card_id} 的参数 '{param_name}': {old_id} → {new_id}")
                elif isinstance(param_value, str):
                    try:
                        if int(param_value.strip()) == old_id:
                            card.parameters[param_name] = str(new_id)
                            updated = True
                            debug_print(f"更新卡片 {card.card_id} 的参数 '{param_name}': {old_id} → {new_id}")
                    except (TypeError, ValueError):
                        pass

            random_connections = card.parameters.get('_random_connections')
            if isinstance(random_connections, list):
                random_updated = False
                for item in random_connections:
                    if isinstance(item, dict) and item.get('card_id') == old_id:
                        item['card_id'] = new_id
                        random_updated = True
                if random_updated:
                    updated = True

            random_weights = card.parameters.get('random_weights')
            if isinstance(random_weights, dict):
                from tasks.random_jump import normalize_branch_weights

                normalized_weights = normalize_branch_weights(random_weights)
                old_key = str(old_id)
                if old_key in normalized_weights:
                    normalized_weights[str(new_id)] = normalized_weights.pop(old_key)
                    card.parameters['random_weights'] = normalized_weights
                    updated = True

    def _snapshot_coordinate_parameters_for_id_change(self) -> Dict[int, Dict[str, Any]]:
        """快照坐标参数，用于ID变更后防止误改。"""
        snapshot: Dict[int, Dict[str, Any]] = {}
        for card in self.cards.values():
            if not hasattr(card, 'parameters') or not isinstance(card.parameters, dict):
                continue
            values: Dict[str, Any] = {}
            if 'coordinate_x' in card.parameters:
                values['coordinate_x'] = card.parameters.get('coordinate_x')
            if 'coordinate_y' in card.parameters:
                values['coordinate_y'] = card.parameters.get('coordinate_y')
            if values:
                snapshot[id(card)] = {'card': card, 'values': values}
        return snapshot

    def _restore_coordinate_parameters_after_id_change(self, snapshot: Dict[int, Dict[str, Any]]):
        """恢复 ID 变更前的坐标参数，避免值被误替换。"""

        if not snapshot:
            return
        for item in snapshot.values():
            card = item.get('card')
            values = item.get('values')
            if not card or not isinstance(values, dict):
                continue
            if not hasattr(card, 'parameters') or not isinstance(card.parameters, dict):
                continue
            for key, original_value in values.items():
                if card.parameters.get(key) != original_value:
                    card.parameters[key] = original_value

    def _handle_test_card(self, card_id: int):
        """处理测试单个卡片的请求：执行指定卡片一次。"""
        logger.info(f"[WorkflowView] 请求测试卡片 ID: {card_id}")
        card = self.cards.get(card_id)
        if not card:
            logger.warning(f"无法找到卡片 ID: {card_id}")
            show_warning_box(self, "错误", f"无法找到卡片 ID: {card_id}")
            return
        logger.info(f"[WorkflowView] 发射 test_card_execution_requested 信号，卡片ID: {card_id}")
        self.test_card_execution_requested.emit(card_id)
        logger.info(f"[WorkflowView] test_card_execution_requested 信号已发射")

    def _handle_test_flow(self, card_id: int):
        """处理测试流程的请求：从指定卡片开始执行整个流程。"""
        logger.info(f"[WorkflowView] 请求从卡片 ID {card_id} 开始测试流程")
        card = self.cards.get(card_id)
        if not card:
            logger.warning(f"无法找到卡片 ID: {card_id}")
            show_warning_box(self, "错误", f"无法找到卡片 ID: {card_id}")
            return
        logger.info(f"[WorkflowView] 发射 test_flow_execution_requested 信号，卡片ID: {card_id}")
        self.test_flow_execution_requested.emit(card_id)
        logger.info(f"[WorkflowView] test_flow_execution_requested 信号已发射")
