from .workflow_view_common import *


class WorkflowViewSerializationMixin:

    def serialize_workflow(self, variables_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Serializes the current workflow (cards, connections, view state) into a dictionary."""
        # 【关键修复】序列化前同步连线列表，确保 self.connections 与场景中的实际连线一致
        self._sync_connections_with_scene()

        metadata = copy.deepcopy(getattr(self, "workflow_metadata", {}) or {})
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.setdefault("created_date", datetime.now().isoformat())
        metadata["engine_version"] = "1.0.0"
        metadata.setdefault("module_versions", {})

        workflow_data = {
            "cards": [],
            "connections": [],
            "view_transform": [],
            "metadata": metadata,
        }

        variables_payload = None
        if isinstance(variables_override, dict):
            variables_payload = variables_override
        else:
            try:
                from task_workflow.workflow_context import export_global_vars
                variables_payload = export_global_vars()
            except Exception as export_err:
                logger.warning(f"导出工作流保存所需全局变量失败：{export_err}")

        if variables_payload is not None:
            workflow_data["variables"] = variables_payload

        # Serialize cards
        for card_id, card in self.cards.items():
            debug_print(f"--- [DEBUG] Saving Card ID: {card_id}, Type: {card.task_type} ---") # DEBUG
            # --- ADDED: Specific log for card ID 0 ---
            if card_id == 0:
                logger.warning(
                    f"    [SERIALIZE] ID 0 卡片序列化: task_type={card.task_type}, parameters={card.parameters}"
                )
            # --- END ADDED ---
            debug_print(f"  Parameters to be saved: {card.parameters}") # <<< ADDED DEBUG PRINT
            card_data = {
                "id": card_id,
                "task_type": card.task_type, # <<< CHANGED FROM 'type' TO 'task_type'
                # --- UNIFIED: Save using 'pos_x' and 'pos_y' ---
                "pos_x": card.x(), # <<< CHANGED FROM 'x' TO 'pos_x'
                "pos_y": card.y(), # <<< CHANGED FROM 'y' TO 'pos_y'
                # --- END UNIFICATION ---
                "container_id": getattr(card, "container_id", None),
                "parameters": card.parameters.copy(), # Assuming parameters are serializable
                "custom_name": card.custom_name # 保存自定义名称
            }

            workflow_data["cards"].append(card_data)

        # Serialize connections
        # 【修复 2025-01-18】保存所有类型的连接（sequential, success, failure）
        # 注释已清理（原注释编码损坏）
        debug_print(f"  [SAVE_DEBUG] Serializing connections...")
        for conn in self.connections:
            if isinstance(conn, ConnectionLine):
                # Ensure start/end items are valid TaskCards before accessing card_id
                if isinstance(conn.start_item, TaskCard) and isinstance(conn.end_item, TaskCard):
                    conn_data = {
                        "start_card_id": conn.start_item.card_id,
                        "end_card_id": conn.end_item.card_id,
                        "type": conn.line_type  # 保存连接类型（sequential/success/failure）
                    }
                    workflow_data["connections"].append(conn_data)
        debug_print(f"  [SAVE_DEBUG] Finished serializing connections. Saved {len(workflow_data['connections'])} lines.")
        # --- END MODIFICATION ---
                
        # Serialize view transform
        transform = self.transform()
        workflow_data["view_transform"] = [
            transform.m11(), transform.m12(), transform.m13(), # m13 usually 0
            transform.m21(), transform.m22(), transform.m23(), # m23 usually 0
            transform.m31(), transform.m32(), transform.m33()  # m31=dx, m32=dy, m33 usually 1
        ]
        # --- ADDED: Debug log for saved transform data ---
        debug_print(f"  [SAVE_DEBUG] Serialized view_transform: {workflow_data['view_transform']}")
        # --- END ADDED ---

        # --- ADDED: Serialize view center point ---
        viewport_center_view = self.viewport().rect().center()
        scene_center_point = self.mapToScene(viewport_center_view)
        workflow_data["view_center"] = [scene_center_point.x(), scene_center_point.y()]
        debug_print(f"  [SAVE_DEBUG] Serialized view_center: {workflow_data['view_center']}")
        # --- END ADDED ---

        logger.info(f"序列化完成：找到 {len(workflow_data['cards'])} 个卡片，{len(workflow_data['connections'])} 个连接。")
        return workflow_data

    def save_workflow(self, filepath: str):
        """DEPRECATED: Logic moved to MainWindow. Use serialize_workflow instead."""
        # This method is likely no longer needed here as MainWindow handles saving.
        # Keep it stubbed or remove it if confirmed unused.
        logger.warning("WorkflowView.save_workflow is deprecated and should not be called.")
        pass
