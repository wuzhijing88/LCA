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

        # 连接对话框按钮
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
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout

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

        # 连接对话框按钮
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
                        info_box.setText("卡片ID对换成功：\n\n"
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
        """将两张已登记卡片的 ID 作为一个操作对换。"""
        if card1 is card2:
            raise ValueError("不能对同一张卡片执行 ID 对换")
        id_mapping = {card1.card_id: card2.card_id, card2.card_id: card1.card_id}
        self._apply_card_id_mapping(id_mapping)
        self._save_undo_state('change_card_ids', {'id_mapping': id_mapping})

    def _change_card_id(self, card: TaskCard, new_id: int):
        """将一张已登记卡片改为未占用的 ID。"""
        old_id = card.card_id
        if new_id == old_id:
            return False
        id_mapping = {old_id: new_id}
        self._apply_card_id_mapping(id_mapping)
        self._save_undo_state('change_card_ids', {'id_mapping': id_mapping})
        return True

    @staticmethod
    def _reference_parameter_names(card: TaskCard) -> set:
        """返回当前参数定义中明确声明为本工作流卡片引用的字段。"""
        if not isinstance(card.param_definitions, dict):
            raise TypeError(f"卡片 {card.card_id} 的参数定义必须是字典")
        reference_hints = {'card_selector', 'jump_target_selector', 'workflow_card_selector'}
        names = {
            name
            for name, definition in card.param_definitions.items()
            if isinstance(definition, dict) and definition.get('widget_hint') in reference_hints
        }
        names.update({'success_jump_target_id', 'failure_jump_target_id'})
        return names

    @staticmethod
    def _reference_is_active(card: TaskCard, parameter_name: str) -> bool:
        definition = card.param_definitions.get(parameter_name, {})
        if not isinstance(definition, dict):
            raise TypeError(f"卡片 {card.card_id} 的参数定义 {parameter_name} 必须是字典")
        plural_conditions = definition.get('conditions')
        conditions = plural_conditions if plural_conditions is not None else definition.get('condition')
        if conditions is None:
            return True
        if isinstance(conditions, dict):
            conditions = [conditions]
        if not isinstance(conditions, list):
            raise TypeError(f"卡片 {card.card_id} 的参数条件 {parameter_name} 格式错误")
        matches = []
        for condition in conditions:
            if not isinstance(condition, dict) or 'param' not in condition or 'value' not in condition:
                raise TypeError(f"卡片 {card.card_id} 的参数条件 {parameter_name} 格式错误")
            actual_value = card.parameters.get(condition['param'])
            expected_value = condition['value']
            matches.append(
                actual_value in expected_value
                if isinstance(expected_value, list)
                else actual_value == expected_value
            )
        return any(matches) if plural_conditions is not None else all(matches)

    def _remap_card_parameters(self, card: TaskCard, id_mapping: Dict[int, int]) -> dict:
        if not isinstance(card.parameters, dict):
            raise TypeError(f"卡片 {card.card_id} 的参数必须是字典")
        updated = copy.deepcopy(card.parameters)

        for parameter_name in self._reference_parameter_names(card):
            if parameter_name not in updated or updated[parameter_name] is None:
                continue
            target_id = updated[parameter_name]
            if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 0:
                raise TypeError(f"卡片 {card.card_id} 的引用参数 {parameter_name} 必须是非负整数或 None")
            updated[parameter_name] = id_mapping.get(target_id, target_id)

        random_weights = updated.get('random_weights')
        if random_weights is not None:
            if not isinstance(random_weights, dict):
                raise TypeError(f"卡片 {card.card_id} 的随机跳转权重必须是字典")
            remapped_weights = {}
            for raw_target_id, weight in random_weights.items():
                if not isinstance(raw_target_id, str) or not raw_target_id.isdigit():
                    raise TypeError(f"卡片 {card.card_id} 的随机跳转目标 ID 必须是数字字符串")
                target_id = id_mapping.get(int(raw_target_id), int(raw_target_id))
                target_key = str(target_id)
                if target_key in remapped_weights:
                    raise RuntimeError(f"卡片 {card.card_id} 的随机跳转权重映射发生冲突")
                remapped_weights[target_key] = weight
            updated['random_weights'] = remapped_weights

        random_connections = updated.get('_random_connections')
        if random_connections is not None:
            if not isinstance(random_connections, list):
                raise TypeError(f"卡片 {card.card_id} 的随机跳转目标清单必须是列表")
            for item in random_connections:
                if not isinstance(item, dict):
                    raise TypeError(f"卡片 {card.card_id} 的随机跳转目标项必须是字典")
                target_id = item.get('card_id')
                if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 0:
                    raise TypeError(f"卡片 {card.card_id} 的随机跳转目标 ID 必须是非负整数")
                item['card_id'] = id_mapping.get(target_id, target_id)

        new_card_id = id_mapping.get(card.card_id, card.card_id)
        result_name = updated.get('save_result_variable_name')
        if result_name == f"卡片{card.card_id}结果":
            updated['save_result_variable_name'] = f"卡片{new_card_id}结果"
        return updated

    def _apply_card_id_mapping(self, id_mapping: Dict[int, int]):
        """严格校验后，一次性提交卡片 ID 和所有显式引用的映射。"""
        if not isinstance(id_mapping, dict) or not id_mapping:
            raise TypeError("卡片 ID 映射必须是非空字典")
        if not isinstance(self.cards, dict):
            raise TypeError("卡片容器必须是字典")

        for old_id, new_id in id_mapping.items():
            if isinstance(old_id, bool) or not isinstance(old_id, int) or old_id < 0:
                raise TypeError("原卡片 ID 必须是非负整数")
            if isinstance(new_id, bool) or not isinstance(new_id, int) or new_id < 0:
                raise TypeError("新卡片 ID 必须是非负整数")
            card = self.cards.get(old_id)
            if not isinstance(card, TaskCard) or card.card_id != old_id:
                raise ValueError(f"原卡片 ID 未登记: {old_id}")

        final_ids = [id_mapping.get(card_id, card_id) for card_id in self.cards]
        if len(final_ids) != len(set(final_ids)):
            raise ValueError("卡片 ID 映射与现有卡片发生冲突")

        remapped_parameters = {
            card: self._remap_card_parameters(card, id_mapping)
            for card in self.cards.values()
        }
        old_cards = dict(self.cards)
        new_cards = {
            id_mapping.get(old_id, old_id): card
            for old_id, card in old_cards.items()
        }

        for old_id, card in old_cards.items():
            card.card_id = id_mapping.get(old_id, old_id)
            card.parameters = remapped_parameters[card]
        self.cards.clear()
        self.cards.update(new_cards)

        flashing_ids = getattr(self, 'flashing_card_ids', None)
        if isinstance(flashing_ids, set):
            self.flashing_card_ids = {id_mapping.get(card_id, card_id) for card_id in flashing_ids}

        panel = getattr(getattr(self, 'main_window', None), 'parameter_panel', None)
        if panel is not None and getattr(panel, 'current_card_id', None) in id_mapping:
            panel.current_card_id = id_mapping[panel.current_card_id]
            selected_card = self.cards[panel.current_card_id]
            panel.current_parameters = selected_card.parameters.copy()

        for card in old_cards.values():
            card.set_display_id(getattr(card, 'sequence_id', None))
        self._refresh_thread_start_custom_names()
        return True
    def _cleanup_jump_target_references(self, deleted_card_id: int):
        """删除卡片时，清除其他卡片对该 ID 的显式跳转引用。"""
        for card_id, card in self.cards.items():
            if card_id == deleted_card_id:
                continue
            if not isinstance(card.parameters, dict):
                raise TypeError(f"卡片 {card_id} 的参数必须是字典")
            updated = card.parameters.copy()
            changed = False
            for line_type, action_key, target_key in (
                ('成功', 'on_success', 'success_jump_target_id'),
                ('失败', 'on_failure', 'failure_jump_target_id'),
            ):
                if updated.get(target_key) != deleted_card_id:
                    continue
                updated[target_key] = None
                if updated.get(action_key) == '跳转到步骤':
                    updated[action_key] = '执行下一步'
                changed = True
            if changed:
                card.parameters = updated
                card.update()

    def _validate_card_references(self):
        """严格校验当前生效的卡片引用，不修改任何数据。"""
        valid_card_ids = set(self.cards)
        for card_id, card in self.cards.items():
            if not isinstance(card, TaskCard) or card.card_id != card_id:
                raise RuntimeError(f"卡片登记不一致: {card_id}")
            if not isinstance(card.parameters, dict):
                raise TypeError(f"卡片 {card_id} 的参数必须是字典")
            for parameter_name in self._reference_parameter_names(card):
                target_id = card.parameters.get(parameter_name)
                if target_id is None:
                    continue
                if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 0:
                    raise TypeError(f"卡片 {card_id} 的引用参数 {parameter_name} 必须是非负整数或 None")
                if self._reference_is_active(card, parameter_name) and target_id not in valid_card_ids:
                    raise ValueError(f"卡片 {card_id} 的引用参数 {parameter_name} 指向不存在的卡片 {target_id}")

            random_weights = card.parameters.get('random_weights')
            if random_weights is not None:
                if not isinstance(random_weights, dict):
                    raise TypeError(f"卡片 {card_id} 的随机跳转权重必须是字典")
                for target_key in random_weights:
                    if not isinstance(target_key, str) or not target_key.isdigit():
                        raise TypeError(f"卡片 {card_id} 的随机跳转目标 ID 必须是数字字符串")
                    if int(target_key) not in valid_card_ids:
                        raise ValueError(f"卡片 {card_id} 的随机跳转权重指向不存在的卡片 {target_key}")

            random_connections = card.parameters.get('_random_connections')
            if random_connections is not None:
                if not isinstance(random_connections, list):
                    raise TypeError(f"卡片 {card_id} 的随机跳转目标清单必须是列表")
                for item in random_connections:
                    if not isinstance(item, dict):
                        raise TypeError(f"卡片 {card_id} 的随机跳转目标项必须是字典")
                    target_id = item.get('card_id')
                    if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 0:
                        raise TypeError(f"卡片 {card_id} 的随机跳转目标 ID 必须是非负整数")
                    if target_id not in valid_card_ids:
                        raise ValueError(f"卡片 {card_id} 的随机跳转目标清单指向不存在的卡片 {target_id}")
        return True
    def _handle_test_card(self, card_id: int):
        """处理测试单个卡片的请求：执行指定卡片一次。"""
        card = self.cards.get(card_id)
        if not card:
            logger.warning("[卡片测试] 卡片不存在 card_id=%s", card_id)
            show_warning_box(self, "错误", f"无法找到卡片 ID: {card_id}")
            return
        logger.info("[卡片测试] 请求执行 card_id=%s", card_id)
        self.test_card_execution_requested.emit(card_id)

    def _handle_test_flow(self, card_id: int):
        """处理测试流程的请求：从指定卡片开始执行整个流程。"""
        card = self.cards.get(card_id)
        if not card:
            logger.warning("[流程测试] 起始卡片不存在 card_id=%s", card_id)
            show_warning_box(self, "错误", f"无法找到卡片 ID: {card_id}")
            return
        logger.info("[流程测试] 请求执行 card_id=%s", card_id)
        self.test_flow_execution_requested.emit(card_id)
