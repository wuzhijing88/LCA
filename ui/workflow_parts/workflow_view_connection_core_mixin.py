from .workflow_view_common import *


class WorkflowViewConnectionCoreMixin:
    """连线的唯一创建、替换和删除入口。"""

    _VALID_CONNECTION_TYPES = frozenset(("sequential", "success", "failure", "random"))
    _JUMP_PARAMETER_KEYS = {
        "success": ("on_success", "success_jump_target_id"),
        "failure": ("on_failure", "failure_jump_target_id"),
    }

    def _validate_connection_endpoints(self, start_card, end_card, line_type):
        if not isinstance(start_card, TaskCard) or not isinstance(end_card, TaskCard):
            raise TypeError("连线两端必须是 TaskCard")
        if line_type not in self._VALID_CONNECTION_TYPES:
            raise ValueError(f"不支持的连线类型: {line_type!r}")
        if self.cards.get(start_card.card_id) is not start_card:
            raise ValueError("连线起点不属于当前工作流")
        if self.cards.get(end_card.card_id) is not end_card:
            raise ValueError("连线终点不属于当前工作流")
        if start_card.scene() is not self.scene or end_card.scene() is not self.scene:
            raise ValueError("连线两端必须挂载在当前场景")
        if not isinstance(start_card.connections, list) or not isinstance(end_card.connections, list):
            raise TypeError("卡片连接容器必须是列表")
        if line_type in ("success", "failure") and start_card.restricted_outputs:
            raise ValueError(f"卡片 {start_card.card_id} 的 {line_type} 输出端口不可用")
        if line_type == "random" and start_card.restricted_outputs != "random_only":
            raise ValueError(f"卡片 {start_card.card_id} 没有随机输出端口")
        if end_card.no_input_ports:
            raise ValueError(f"卡片 {end_card.card_id} 没有输入端口")
        rule_error = self._validate_special_connection_rule(start_card, end_card, line_type)
        if rule_error:
            raise ValueError(rule_error)

    def _validate_connection_contract(self, connection, *, require_scene=True):
        if not isinstance(connection, ConnectionLine):
            raise TypeError("连接对象必须是 ConnectionLine")
        start_card = connection.start_item
        end_card = connection.end_item
        line_type = connection.line_type
        if start_card is None or end_card is None:
            raise ValueError("连接必须同时包含起点和终点卡片")
        if line_type not in self._VALID_CONNECTION_TYPES:
            raise ValueError(f"不支持的连线类型: {line_type!r}")
        if self.cards.get(getattr(start_card, "card_id", None)) is not start_card:
            raise ValueError("连线起点不属于当前工作流")
        if self.cards.get(getattr(end_card, "card_id", None)) is not end_card:
            raise ValueError("连线终点不属于当前工作流")
        if self.connections.count(connection) != 1:
            raise ValueError("连接在视图列表中的登记次数必须为 1")
        if start_card.connections.count(connection) != 1:
            raise ValueError("连接在起点卡片中的登记次数必须为 1")
        if end_card.connections.count(connection) != 1:
            raise ValueError("连接在终点卡片中的登记次数必须为 1")
        if require_scene and connection.scene() is not self.scene:
            raise ValueError("连接未挂载在当前场景")
        return start_card, end_card, line_type

    def _registered_connections_for_port(self, start_card, line_type):
        matches = []
        for connection in self.connections:
            if not isinstance(connection, ConnectionLine):
                raise TypeError("视图连接列表中存在非 ConnectionLine 对象")
            if connection.start_item is start_card and connection.line_type == line_type:
                matches.append(connection)
        return matches

    def _refresh_connection_parameter_display(self, start_card):
        start_card.update_port_restrictions()
        start_card._tooltip_needs_update = True
        start_card.update()

        main_window = getattr(self, "main_window", None)
        panel = getattr(main_window, "parameter_panel", None) if main_window is not None else None
        if panel is None or not panel.is_panel_open() or panel.current_card_id != start_card.card_id:
            return
        panel.current_parameters = start_card.parameters.copy()
        panel._rebuild_parameter_widgets()

    def _update_card_parameters_on_connection_create(self, start_card, end_card, line_type):
        parameter_keys = self._JUMP_PARAMETER_KEYS.get(line_type)
        if parameter_keys is None:
            return False
        if not isinstance(start_card.parameters, dict):
            raise TypeError("起点卡片 parameters 必须是字典")

        action_key, target_key = parameter_keys
        updated_parameters = start_card.parameters.copy()
        updated_parameters[action_key] = "跳转到步骤"
        updated_parameters[target_key] = end_card.card_id
        if updated_parameters == start_card.parameters:
            return False

        start_card.parameters = updated_parameters
        self._refresh_connection_parameter_display(start_card)
        return True

    def _clear_jump_parameters_for_connection(self, connection):
        start_card = connection.start_item
        end_card = connection.end_item
        line_type = connection.line_type
        if not isinstance(start_card, TaskCard):
            raise TypeError("连线起点必须是 TaskCard")
        if not isinstance(end_card, TaskCard):
            raise TypeError("连线终点必须是 TaskCard")
        if not isinstance(start_card.parameters, dict):
            raise TypeError("起点卡片 parameters 必须是字典")

        parameter_keys = self._JUMP_PARAMETER_KEYS.get(line_type)
        if parameter_keys is not None:
            action_key, target_key = parameter_keys
            if start_card.parameters.get(target_key) != end_card.card_id:
                return False
            updated_parameters = start_card.parameters.copy()
            updated_parameters[target_key] = None
            if updated_parameters.get(action_key) == "跳转到步骤":
                updated_parameters[action_key] = "执行下一步"
            if updated_parameters == start_card.parameters:
                return False
            start_card.parameters = updated_parameters
            self._refresh_connection_parameter_display(start_card)
            return True

        if line_type == "random":
            from tasks.random_jump import prune_branch_weights

            valid_target_ids = []
            for other in self.connections:
                if other is connection:
                    continue
                if not isinstance(other, ConnectionLine):
                    raise TypeError("视图连接列表中存在非 ConnectionLine 对象")
                if (
                    other.start_item is start_card
                    and other.line_type == "random"
                    and isinstance(other.end_item, TaskCard)
                ):
                    valid_target_ids.append(other.end_item.card_id)
            updated_weights = prune_branch_weights(
                start_card.parameters.get("random_weights"),
                valid_target_ids,
            )
            if updated_weights == start_card.parameters.get("random_weights"):
                return False
            updated_parameters = start_card.parameters.copy()
            updated_parameters["random_weights"] = updated_weights
            start_card.parameters = updated_parameters
            self._refresh_connection_parameter_display(start_card)
            return True
        return False

    def _mount_connection(self, connection):
        start_card = connection.start_item
        end_card = connection.end_item
        self.scene.addItem(connection)
        if connection.scene() is not self.scene:
            raise RuntimeError("连接未能挂载到当前场景")
        start_card.connections.append(connection)
        if end_card is not start_card:
            end_card.connections.append(connection)
        self.connections.append(connection)

    def _unmount_connection(self, connection):
        start_card = connection.start_item
        end_card = connection.end_item
        start_card.connections.remove(connection)
        if end_card is not start_card:
            end_card.connections.remove(connection)
        self.connections.remove(connection)
        self.scene.removeItem(connection)
        connection.start_item = None
        connection.end_item = None

    def _create_registered_connection(self, start_card, end_card, line_type):
        connection = ConnectionLine(start_card, end_card, line_type)
        try:
            self._mount_connection(connection)
        except Exception:
            if connection.scene() is self.scene:
                self.scene.removeItem(connection)
            if connection in start_card.connections:
                start_card.connections.remove(connection)
            if end_card is not start_card and connection in end_card.connections:
                end_card.connections.remove(connection)
            if connection in self.connections:
                self.connections.remove(connection)
            connection.start_item = None
            connection.end_item = None
            raise
        return connection

    def add_connection(self, start_card: TaskCard, end_card: TaskCard, line_type: str, skip_duplicate_check: bool = False):
        """创建连线；已有输出线时显式替换，不扫描、不补登记、不重试。"""
        del skip_duplicate_check  # 所有入口使用同一套严格校验。
        if not self.editing_enabled or self._block_edit_if_running("添加连线"):
            return None

        try:
            self._validate_connection_endpoints(start_card, end_card, line_type)
            state_errors = self._connection_state_errors()
            if state_errors:
                raise RuntimeError("；".join(state_errors))

            existing_connections = self._registered_connections_for_port(start_card, line_type)
            allow_multiple = line_type == "random" and start_card.task_type == "随机跳转"
            if allow_multiple:
                for existing in existing_connections:
                    if existing.end_item is end_card:
                        return existing
                old_connection = None
            else:
                if len(existing_connections) > 1:
                    raise RuntimeError(
                        f"卡片 {start_card.card_id} 的 {line_type} 输出端存在多条连接"
                    )
                old_connection = existing_connections[0] if existing_connections else None
                if old_connection is not None and old_connection.end_item is end_card:
                    return old_connection

            old_connection_data = None
            if old_connection is not None:
                self._validate_connection_contract(old_connection)
                old_connection_data = (
                    old_connection.start_item,
                    old_connection.end_item,
                    old_connection.line_type,
                )

            new_connection = self._create_registered_connection(start_card, end_card, line_type)
            try:
                self._update_card_parameters_on_connection_create(start_card, end_card, line_type)
                if old_connection is not None:
                    self._unmount_connection(old_connection)
            except Exception:
                self._unmount_connection(new_connection)
                raise

            if old_connection_data is not None:
                self.connection_deleted.emit(old_connection)
            self.connection_added.emit(start_card, end_card, line_type)
            if not self._loading_workflow and not self._updating_sequence and not self._undoing_operation:
                if old_connection_data is None and not getattr(self, "_pasting_card", False):
                    self._save_add_connection_state_for_undo(start_card, end_card, line_type)
                elif old_connection_data is not None:
                    old_start, old_end, old_type = old_connection_data
                    old_connection.start_item = old_start
                    old_connection.end_item = old_end
                    self._save_modify_connection_state_for_undo(
                        old_connection,
                        start_card,
                        end_card,
                        line_type,
                    )
                    old_connection.start_item = None
                    old_connection.end_item = None
            return new_connection
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.debug(
                "创建连线被拒绝: %s -> %s (%s): %s",
                getattr(start_card, "card_id", None),
                getattr(end_card, "card_id", None),
                line_type,
                exc,
            )
            return None

    def remove_connection(self, connection):
        """严格删除一条已完整登记的连线。"""
        if not self.editing_enabled or self._block_edit_if_running("删除连线"):
            return False
        try:
            start_card, _, line_type = self._validate_connection_contract(connection)
            if not self._deleting_card and not self._loading_workflow and not self._updating_sequence and not self._undoing_operation:
                self._save_connection_state_for_undo(connection)
            self._clear_jump_parameters_for_connection(connection)
            self._unmount_connection(connection)
            if line_type == "sequential":
                self.update_card_sequence_display()
            self.connection_deleted.emit(connection)
            return True
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.error("删除连线失败：%s", exc)
            return False
