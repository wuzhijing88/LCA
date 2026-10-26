"""画布连线控制器：拓扑登记、原子编辑、参数同步和局部路由。"""
from collections import deque
from shiboken6 import isValid

from .connection_geometry import EdgeRequest, EdgeRoute, LINE_TYPES
from .connection_line import ConnectionLine
from .connection_tracks import OrthogonalRouter
from .task_card import TaskCard


def edge_data(line):
    return {"start_card_id": line.start_item.card_id, "end_card_id": line.end_item.card_id,
            "line_type": line.line_type}


class ConnectionController:
    BRANCH_PARAMETER_KEYS = ("on_success", "success_jump_target_id",
                             "on_failure", "failure_jump_target_id")

    def __init__(self, view):
        self.view = view
        self.router = OrthogonalRouter()
        view.destroyed.connect(self.dispose)

    @staticmethod
    def bounds(card):
        rect = card.mapRectToScene(card.boundingRect())
        return rect.x(), rect.y(), rect.width(), rect.height()

    def request(self, line):
        source, target = line.get_start_pos(), line.get_end_pos()
        return EdgeRequest((line.start_item.card_id, line.end_item.card_id, line.line_type),
                           (source.x(), source.y()), (target.x(), target.y()),
                           self.bounds(line.start_item), self.bounds(line.end_item))

    def plan(self, lines, retained=()):
        requests = {line: self.request(line) for line in lines}
        fixed = [EdgeRoute((line.start_item.card_id, line.end_item.card_id, line.line_type),
                          tuple(line.route_points())) for line in retained if line.route_points()]
        planned = self.router.plan(list(requests.values()), fixed)
        return [(line, planned[request.key].points) for line, request in requests.items()]

    def reroute(self, cards=None):
        view = self.view
        if view._rerouting_connections:
            return
        moving = None if cards is None else set(cards)
        if moving is not None and any(view.cards.get(card.card_id) is not card for card in moving):
            raise ValueError("移动卡片不属于当前工作流")
        lines = list(view.connections)
        affected = lines if moving is None else [line for line in lines if line.start_item in moving or line.end_item in moving or not line.route_points()]
        if not affected:
            return
        changed = set(affected)
        retained = [line for line in lines if line not in changed]
        # 先生成完整批次，再一次提交；规划期间不泵事件、不重入图元事件。
        view._rerouting_connections = True
        try:
            planned = self.plan(affected, retained)
            for line, points in planned:
                line.apply_route_points(points)
            for card in view.cards.values() if moving is None else moving:
                card._last_group_pos = card.pos()
        finally:
            view._rerouting_connections = False

    def validate_endpoints(self, source, target, kind):
        view = self.view
        if not isinstance(source, TaskCard) or not isinstance(target, TaskCard):
            raise TypeError("连线端点必须是任务卡片")
        if kind not in LINE_TYPES:
            raise ValueError(f"不支持的连线类型：{kind}")
        for card in (source, target):
            if not isValid(card) or view.cards.get(card.card_id) is not card or card.scene() is not view.scene:
                raise ValueError("连线端点不属于当前工作流")
        if source is target:
            raise ValueError("卡片不能连接到自身")
        if kind in ("success", "failure") and source.restricted_outputs:
            raise ValueError("卡片不提供成功或失败输出端口")
        if kind == "random" and source.restricted_outputs != "random_only":
            raise ValueError("卡片不提供随机输出端口")
        if source.restricted_outputs == "random_only" and kind != "random":
            raise ValueError("随机跳转卡片只能使用随机输出端口")
        if target.no_input_ports:
            raise ValueError("目标卡片没有输入端口")
        error = view._validate_special_connection_rule(source, target, kind)
        if error:
            raise ValueError(error)

    def errors(self):
        view = self.view
        if not isinstance(view.connections, list) or not isinstance(view.cards, dict):
            raise TypeError("工作流必须使用字典登记卡片、列表登记连线")
        errors, objects, keys, ports = [], set(), set(), set()
        for line in view.connections:
            if not isinstance(line, ConnectionLine):
                errors.append("视图登记了非连线对象")
                continue
            if line in objects:
                errors.append("视图重复登记了同一连线")
                continue
            objects.add(line)
            if not isValid(line):
                errors.append("视图仍登记了已销毁的连线对象")
                continue
            source, target = line.start_item, line.end_item
            if source is None or target is None:
                errors.append("已销毁的连线仍在视图中登记")
                continue
            if not isValid(source) or not isValid(target):
                errors.append("连线登记了已销毁的端点")
                continue
            if view.cards.get(source.card_id) is not source or view.cards.get(target.card_id) is not target:
                errors.append("连线端点未登记")
            if line.scene() is not view.scene or source.scene() is not view.scene or target.scene() is not view.scene:
                errors.append("连线或端点离开了所属场景")
            if not isinstance(source.connections, list) or not isinstance(target.connections, list):
                errors.append("连线端点的连接容器不是列表")
            elif source.connections.count(line) != 1 or target.connections.count(line) != 1:
                errors.append("连线在端点的登记次数不是一次")
            key = (source.card_id, target.card_id, line.line_type)
            port = (source.card_id, line.line_type)
            if key in keys:
                errors.append("存在重复连线")
            if port in ports and line.line_type != "random":
                errors.append("单输出端口登记了多条连线")
            if line.line_type not in LINE_TYPES:
                errors.append("存在未知连线类型")
            keys.add(key)
            ports.add(port)
        for card in view.cards.values():
            if not isinstance(card, TaskCard) or not isValid(card):
                errors.append("视图登记了无效卡片")
                continue
            if not isinstance(card.connections, list):
                errors.append("卡片的连接容器不是列表")
                continue
            for line in card.connections:
                if line not in objects or (line.start_item is not card and line.end_item is not card):
                    errors.append("卡片登记了无关或未挂载的连线")
        return errors

    def assert_registered(self, line):
        view = self.view
        if not isinstance(line, ConnectionLine) or line not in view.connections:
            raise ValueError("连线未在当前视图登记")
        errors = self.errors()
        if errors:
            raise RuntimeError("；".join(errors))
        return line.start_item, line.end_item, line.line_type

    def mount(self, line):
        view = self.view
        line.start_item.connections.append(line)
        line.end_item.connections.append(line)
        view.connections.append(line)
        view.scene.addItem(line)

    def unmount(self, line):
        view = self.view
        line.start_item.connections.remove(line)
        line.end_item.connections.remove(line)
        view.connections.remove(line)
        line.cleanup()
        view.scene.removeItem(line)
        line.deleteLater()

    @staticmethod
    def parameter_change(source, target, kind):
        result = dict(source.parameters)
        if kind in ("success", "failure"):
            result["on_" + kind] = "跳转到步骤"
            result[kind + "_jump_target_id"] = target.card_id
        return result

    def parameter_remove(self, line):
        source, target, kind = line.start_item, line.end_item, line.line_type
        result = dict(source.parameters)
        if kind in ("success", "failure") and result.get(kind + "_jump_target_id") == target.card_id:
            result[kind + "_jump_target_id"] = None
            if "跳转" in str(result.get("on_" + kind) or ""):
                result["on_" + kind] = "执行下一步"
        elif kind == "random":
            from tasks.random_jump import prune_branch_weights
            targets = [other.end_item.card_id for other in source.connections
                       if other is not line and other.start_item is source and other.line_type == "random"]
            result["random_weights"] = prune_branch_weights(result.get("random_weights"), targets)
        return result

    def add(self, source, target, kind):
        view = self.view
        self.validate_endpoints(source, target, kind)
        errors = self.errors()
        if errors:
            raise RuntimeError("；".join(errors))
        existing = [line for line in source.connections if line.start_item is source and line.line_type == kind]
        line = next((line for line in existing if line.end_item is target), None)
        # 加载、粘贴和撤销只还原既有拓扑；互斥规则用于本次连线编辑。
        editing_outputs = (not view._loading_workflow and not view._undoing_operation
                           and not getattr(view, "_pasting_card", False))
        reset_branches = editing_outputs and kind == "sequential" and not source.restricted_outputs
        conflict_kinds = (
            ("success", "failure") if kind == "sequential"
            else ("sequential",) if kind in ("success", "failure") else ()
        )
        conflicts = [other for other in source.connections
                     if other.start_item is source and other.line_type in conflict_kinds] if editing_outputs else []
        parameters = self.parameter_change(source, target, kind)
        if reset_branches:
            for branch_kind in ("success", "failure"):
                parameters["on_" + branch_kind] = "执行下一步"
                parameters[branch_kind + "_jump_target_id"] = None
        branch_changed = reset_branches and any(
            key not in source.parameters or source.parameters[key] != parameters[key]
            for key in self.BRANCH_PARAMETER_KEYS)
        if line is not None and not conflicts and not branch_changed:
            return line
        new_line = line is None
        old = existing[0] if new_line and kind != "random" and existing else None
        removed = ([old] if old is not None else []) + conflicts
        removed_data = [edge_data(other) for other in removed]
        original_parameters = source.parameters
        branch_parameters = {key: original_parameters[key] for key in self.BRANCH_PARAMETER_KEYS
                             if key in original_parameters}
        if new_line:
            line = ConnectionLine(source, target, kind)
        try:
            if new_line:
                if not view._loading_workflow:
                    retained = [other for other in view.connections if other not in removed]
                    for _, points in self.plan([line], retained):
                        line.apply_route_points(points)
                self.mount(line)
            source.parameters = parameters
            view._refresh_connection_parameter_display(source)
        except Exception:
            source.parameters = original_parameters
            if new_line:
                if line in view.connections:
                    self.unmount(line)
                else:
                    line.cleanup()
                    line.deleteLater()
            raise
        # 新线及参数成功提交后，才完整卸载被替换的蓝线和红绿分支。
        for other in removed:
            self.unmount(other)
        if kind in ("success", "failure") and conflicts:
            self.update_sequence()
        for other in removed:
            view.connection_deleted.emit(other)
        if new_line:
            view.connection_added.emit(source, target, kind)
        if not view._loading_workflow and not view._undoing_operation:
            view._mark_workflow_dirty()
            if not view._updating_sequence:
                if conflicts or branch_changed:
                    view._save_undo_state("switch_output_connections", {
                        "connection_data": edge_data(line), "connection_added": new_line,
                        "removed_connections": removed_data, "branch_parameters": branch_parameters,
                    })
                elif old is not None:
                    view._save_undo_state("modify_connection", {"old_connection_data": removed_data[0], "new_connection_data": edge_data(line)})
                elif not getattr(view, "_pasting_card", False):
                    view._save_add_connection_state_for_undo(source, target, kind)
        return line

    def restore_output_connections(self, operation_data):
        """一次撤销输出连线切换；历史只保存连线数据和四个分支参数。"""
        view = self.view
        data = operation_data["connection_data"]
        source = view.cards.get(data["start_card_id"])
        if source is None:
            raise ValueError("撤销输出连线切换失败：源卡片不存在")
        line = next((line for line in source.connections
                     if line.start_item is source and line.end_item.card_id == data["end_card_id"]
                     and line.line_type == data["line_type"]), None)
        if line is None:
            raise ValueError("撤销输出连线切换失败：当前连线不存在")
        self.assert_registered(line)
        restored = []
        for removed in operation_data["removed_connections"]:
            target = view.cards.get(removed["end_card_id"])
            self.validate_endpoints(source, target, removed["line_type"])
            restored.append((target, removed["line_type"]))
        if operation_data["connection_added"]:
            self.remove(line)
        for target, kind in restored:
            self.add(source, target, kind)
        parameters = dict(source.parameters)
        for key in self.BRANCH_PARAMETER_KEYS:
            if key in operation_data["branch_parameters"]:
                parameters[key] = operation_data["branch_parameters"][key]
            else:
                parameters.pop(key, None)
        source.parameters = parameters
        view._refresh_connection_parameter_display(source)

    def remove(self, line):
        view = self.view
        source, _, kind = self.assert_registered(line)
        parameters = self.parameter_remove(line)
        if not (view._deleting_card or view._loading_workflow or view._updating_sequence or view._undoing_operation):
            view._save_connection_state_for_undo(line)
        self.unmount(line)
        source.parameters = parameters
        view._refresh_connection_parameter_display(source)
        view.connection_deleted.emit(line)
        if kind == "sequential":
            self.update_sequence()
        if not view._loading_workflow and not view._undoing_operation:
            view._mark_workflow_dirty()
        return True

    def update_sequence(self):
        view = self.view
        if view._updating_sequence:
            raise RuntimeError("卡片序列更新不能重复进入")
        errors = self.errors()
        if errors:
            raise RuntimeError("；".join(errors))
        view._updating_sequence = True
        try:
            adjacency = {card: [] for card in view.cards.values()}
            for card in adjacency:
                card.set_display_id(None)
            for line in view.connections:
                if line.line_type == "sequential":
                    adjacency[line.start_item].append(line.end_item)
            queue = deque(sorted((card for card in adjacency if view._is_start_task_type(card.task_type)), key=lambda card: card.card_id))
            visited = set()
            while queue:
                card = queue.popleft()
                if card in visited:
                    continue
                card.set_display_id(len(visited))
                visited.add(card)
                queue.extend(sorted(adjacency[card], key=lambda card: card.card_id))
            return len(visited)
        finally:
            view._updating_sequence = False

    def sync_jump_parameters(self, card):
        desired = {}
        for kind in ("success", "failure"):
            target_id = card.parameters.get(kind + "_jump_target_id")
            action = card.parameters.get("on_" + kind)
            if not card.restricted_outputs and "跳转" in str(action or "") and target_id not in (None, ""):
                if type(target_id) is not int:
                    raise ValueError("跳转目标编号必须是整数")
                if target_id not in self.view.cards:
                    raise ValueError(f"跳转目标卡片不存在：{target_id}")
                desired[kind] = self.view.cards[target_id]
            else:
                desired[kind] = None
        # 只有实际改变的端口才替换；参数面板打开不会改变图元或路径。
        for kind, target in desired.items():
            existing = [line for line in card.connections if line.start_item is card and line.line_type == kind]
            if target is None:
                for line in existing:
                    self.unmount(line)
                if existing and not self.view._loading_workflow:
                    self.view._mark_workflow_dirty()
            elif len(existing) != 1 or existing[0].end_item is not target:
                self.add(card, target, kind)

    def dispose(self):
        view = self.view
        self.view = None
        if view is not None and not isValid(view):
            # 父窗口直接销毁时 closeEvent 不一定发生；Qt 负责销毁子对象，
            # 此处解除 Python 容器和多选拖动留下的相互引用。
            for card in view.cards.values():
                TaskCard._gradient_cards.discard(card)
                card.view = None
                card.connections.clear()
                card._other_selected_cards_start_positions = {}
                card._dragging_multi_selection = False
                card._multi_dragging_member = False
                card._is_dragging = False
            TaskCard._stop_gradient_timer_if_idle()
            view._cancel_canvas_panning()
            view.cards.clear()
            view.connections.clear()
            view.undo_stack.clear()
            view.flashing_card_ids.clear()
