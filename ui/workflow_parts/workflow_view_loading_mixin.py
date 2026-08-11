from .workflow_view_common import *


class WorkflowViewLoadingMixin:

    def load_workflow(self, workflow_data: Dict[str, Any]):
        """Loads a workflow from the provided data dictionary."""
        # <<< REMOVED: Ensure all file reading logic is gone >>>
        # (Removed the commented-out try/except block that contained `open(filepath,...)`)
        # -------------------------------------

        logger.info(f"WorkflowView: 开始从数据字典加载工作流...")

        metadata = workflow_data.get("metadata") if isinstance(workflow_data, dict) else {}
        self.workflow_metadata = dict(metadata) if isinstance(metadata, dict) else {}

        # 注释已清理（原注释编码损坏）
        self._loading_workflow = True

        # Clear existing workflow
        self.clear_workflow()

        # 检查是否为模块文件格式
        if 'workflow' in workflow_data and 'cards' not in workflow_data:
            # 这是模块文件格式，提取workflow部分
            actual_workflow = workflow_data['workflow']
            module_info = workflow_data.get('module_info', {})
            logger.info(f"检测到模块文件格式，提取workflow数据: {module_info.get('name', '未知模块')}")
        else:
            # 这是标准工作流格式
            actual_workflow = workflow_data

        # 验证workflow数据完整性
        if not isinstance(actual_workflow, dict):
            logger.error("工作流数据格式错误：不是字典类型")
            return

        if 'cards' not in actual_workflow:
            logger.error("工作流数据缺少cards字段")
            actual_workflow['cards'] = []

        if 'connections' not in actual_workflow:
            logger.warning("工作流数据缺少connections字段，使用空列表")
            actual_workflow['connections'] = []

        # Load Cards from the extracted list
        unavailable_task_types: Dict[str, int] = {}
        card_load_errors: List[str] = []
        for card_data in actual_workflow['cards']:
            logger.debug(f"DEBUG [load_workflow]: LOOP START for card data: {card_data}") # Keep this debug log
            try:
                if not isinstance(card_data, dict):
                    logger.warning(f"跳过无效卡片数据（非字典）: {card_data}")
                    continue

                # Call add_task_card
                # 兼容旧工作流字段：task_type/type, pos_x/x, pos_y/y
                card_type_from_json = str(
                    card_data.get('task_type', card_data.get('type', '未知')) or '未知'
                ).strip()
                if not card_type_from_json:
                    card_type_from_json = '未知'
                logger.debug(f"DEBUG [load_workflow]: Extracted task_type='{card_type_from_json}' (compatible keys)") # Updated log

                raw_card_id = card_data.get('id')
                card_id_value = None
                if raw_card_id is not None:
                    try:
                        card_id_value = int(raw_card_id)
                    except (TypeError, ValueError):
                        logger.warning(f"卡片ID无效，改为自动分配: task_type={card_type_from_json}, id={raw_card_id}")

                raw_x = card_data.get('pos_x', card_data.get('x', 0))
                raw_y = card_data.get('pos_y', card_data.get('y', 0))
                try:
                    pos_x = float(raw_x)
                except (TypeError, ValueError):
                    pos_x = 0.0
                try:
                    pos_y = float(raw_y)
                except (TypeError, ValueError):
                    pos_y = 0.0
                card = self.add_task_card(
                    x=pos_x,
                    y=pos_y,
                    task_type=card_type_from_json, # Pass the extracted type
                    card_id=card_id_value
                )
                logger.debug(f"DEBUG [load_workflow]: Returned from add_task_card. Card object: {card}") # Keep this debug log

                if card is None:
                    unavailable_task_types[card_type_from_json] = unavailable_task_types.get(card_type_from_json, 0) + 1
                    logger.warning(f"卡片类型不可用，已跳过: task_type={card_type_from_json}, id={raw_card_id}")
                    continue

                # --- Parameter Merging (Now directly after card creation) ---
                debug_print(f"DEBUG [load_workflow]: Processing card data for merge: {card_data}")
                if card and isinstance(card_data.get("parameters"), dict):
                    debug_print(f"DEBUG [load_workflow]: Starting parameter merge for card {card.card_id}")
                    loaded_params = card_data["parameters"]
                    debug_print(f"  [LOAD_DEBUG] Loaded params from JSON: {loaded_params}")
                    current_params = card.parameters.copy()
                    debug_print(f"  [LOAD_DEBUG] Default params from card before merge: {current_params}")
                    # --- REVISED Merge Loop: Handle card_selector parsing --- 
                    for key, loaded_value in loaded_params.items():
                        loaded_value = copy.deepcopy(loaded_value)
                        # Get parameter definition to check for hints
                        param_defs = card.param_definitions if isinstance(card.param_definitions, dict) else {}
                        param_def_for_key = param_defs.get(key, {})
                        widget_hint = param_def_for_key.get('widget_hint') if isinstance(param_def_for_key, dict) else None

                        if widget_hint == 'card_selector':
                            # Attempt to parse Card ID from string like "Task Type (ID: 123)"
                            parsed_id = None
                            if isinstance(loaded_value, str):
                                match = re.search(r'\(ID:\s*(\d+)\)', loaded_value)
                                if match:
                                    try:
                                        parsed_id = int(match.group(1))
                                        debug_print(f"    [LOAD_DEBUG] Parsed Card ID {parsed_id} from '{loaded_value}' for key '{key}'.")
                                    except ValueError:
                                        debug_print(f"    [LOAD_DEBUG] WARNING: Could not convert parsed ID '{match.group(1)}' to int for key '{key}'. Setting to None.")
                                elif loaded_value.strip().lower() == 'none' or loaded_value.strip() == "默认 (蓝色连线)": # Handle explicit None/Default strings
                                    debug_print(f"    [LOAD_DEBUG] Loaded value for '{key}' indicates None/Default ('{loaded_value}'). Setting target ID to None.")
                                    parsed_id = None
                                else:
                                    try:
                                        parsed_id = int(loaded_value.strip())
                                        debug_print(f"    [LOAD_DEBUG] Parsed direct integer {parsed_id} from '{loaded_value}' for key '{key}'.")
                                    except (TypeError, ValueError):
                                        debug_print(f"    [LOAD_DEBUG] WARNING: Could not parse Card ID from string '{loaded_value}' for key '{key}'. Setting to None.")
                            elif isinstance(loaded_value, int):
                                parsed_id = loaded_value
                                debug_print(f"    [LOAD_DEBUG] Loaded value for '{key}' is already an integer: {parsed_id}.")
                            elif loaded_value is None:
                                debug_print(f"    [LOAD_DEBUG] Loaded value for '{key}' is None.")
                                parsed_id = None
                            else:
                                debug_print(f"    [LOAD_DEBUG] WARNING: Unexpected type {type(loaded_value)} ('{loaded_value}') for card selector '{key}'. Setting to None.")
                            
                            # Store the parsed ID (or None)
                            current_params[key] = parsed_id
                            debug_print(f"    [LOAD_DEBUG] Merging PARSED ID: '{key}' = {current_params[key]}")

                        elif loaded_value is not None: # Keep original logic for non-card selectors
                            debug_print(f"    [LOAD_DEBUG] Merging STANDARD value: '{key}' = {loaded_value} (Type: {type(loaded_value)}) -> Overwriting default: {current_params.get(key)}")
                            current_params[key] = loaded_value
                        else: # loaded_value is None for non-card selectors
                            debug_print(f"    [LOAD_DEBUG] Skipping merge for key '{key}' because loaded value is None (standard param).")
                    # --- END REVISED Merge Loop ---
                    card.parameters = current_params

                    debug_print(f"  [LOAD_DEBUG] Final card parameters after merge: {card.parameters}")
                elif card and card_data.get("parameters") is not None:
                    logger.warning(
                        f"卡片参数格式无效，已跳过参数恢复: card_id={card.card_id}, type={type(card_data.get('parameters'))}"
                    )

                # --- 恢复自定义名称 ---
                if card and "custom_name" in card_data:
                    custom_name = str(card_data["custom_name"] or "").strip()
                    if custom_name:
                        card.set_custom_name(custom_name)
                        debug_print(f"  [LOAD_DEBUG] 恢复卡片 {card.card_id} 的自定义名称: '{custom_name}'")
                    else:
                        debug_print(f"  [LOAD_DEBUG] 卡片 {card.card_id} 无自定义名称")

                debug_print(f"DEBUG [load_workflow]: Reached end of try block for card {card.card_id if card else 'N/A'}")

            except Exception as e:
                debug_print(f"--- 卡片加载循环发生错误（卡片数据：{card_data}）---")
                # --- ADDED: More detailed exception info --- 
                debug_print(f"  Exception Type: {type(e)}")
                debug_print(f"  Exception Repr: {repr(e)}")
                # --- END ADDED ---
                # --- MODIFIED: Explicitly convert exception to string --- 
                error_message = str(e)
                debug_print(f"警告：加载卡片时发生错误: {error_message}")
                logger.warning(f"加载卡片失败: {error_message}; card_data={card_data}", exc_info=True)
                card_load_errors.append(error_message)

        if unavailable_task_types:
            summary = ", ".join(f"{name} x{count}" for name, count in unavailable_task_types.items())
            logger.warning(f"以下卡片类型未加载（任务模块不可用）: {summary}")
            card_load_errors.append(f"以下卡片类型未加载: {summary}")

        if card_load_errors:
            unique_errors = list(dict.fromkeys(card_load_errors))
            preview = "\n".join(unique_errors[:5])
            if len(unique_errors) > 5:
                preview = f"{preview}\n..."
            QMessageBox.warning(
                self,
                "加载警告",
                f"部分卡片加载失败，共 {len(card_load_errors)} 项。\n{preview}"
            )

        debug_print(f"DEBUG [load_workflow]: Card creation loop finished.")
        self._update_card_render_cache_policy()

        try:
            from task_workflow.workflow_context import import_global_vars, prune_orphan_vars
            variables_data = actual_workflow.get("variables")
            if variables_data is None and isinstance(workflow_data, dict):
                variables_data = workflow_data.get("variables")
            import_global_vars(variables_data)
            prune_orphan_vars(self.cards.keys())
        except Exception as var_err:
            logger.warning(f"恢复工作流变量失败：{var_err}")

        self._register_result_placeholders_after_load()
        self._refresh_container_layouts()

        # --- Restore Connection Loading (using extracted list) ---
        restored_serialized_jump_connections = 0
        debug_print(f"DEBUG [load_workflow]: Starting connection loading ({len(actual_workflow['connections'])} connections).")
        if actual_workflow['connections']:
            for conn_data in actual_workflow['connections']:
                try:
                    start_card_id = conn_data.get('start_card_id') # <-- Get IDs first
                    end_card_id = conn_data.get('end_card_id')
                    start_card = self.cards.get(start_card_id)
                    end_card = self.cards.get(end_card_id)
                    line_type = str(
                        conn_data.get('type', conn_data.get('line_type', conn_data.get('connection_type', ''))) or ''
                    ).strip()

                    # Check if cards exist and line_type is valid before proceeding
                    if start_card and end_card and line_type: # <<< Now line_type should be correct
                        if line_type not in ['sequential', 'success', 'failure', 'random']:
                            debug_print(
                                f"[LOAD_INFO] Skipping unsupported line type '{line_type}' from JSON "
                                f"(ID: {start_card_id} -> {end_card_id})."
                            )
                            continue

                        debug_print(f"  [LOAD_DEBUG] Adding connection: {start_card_id} -> {end_card_id}, Type: {line_type}")
                        restored_connection = self.add_connection(
                            start_card,
                            end_card,
                            line_type,
                            skip_duplicate_check=True
                        )
                        if restored_connection is not None and line_type in ['success', 'failure']:
                            restored_serialized_jump_connections += 1
                    else:
                        # More specific warning
                        warning_reason = []
                        if not start_card: warning_reason.append(f"未找到 start_card_id {start_card_id}")
                        if not end_card: warning_reason.append(f"未找到 end_card_id {end_card_id}")
                        if not line_type: warning_reason.append("line_type missing") # Should no longer happen if 'type' exists
                        debug_print(f"警告：恢复连接时跳过无效数据 ({conn_data}): {', '.join(warning_reason)}")
                except Exception as e:
                    debug_print(f"警告：恢复连接时发生错误 ({conn_data}): {e}")
                    logger.exception(f"恢复连接时发生错误: {e}; conn_data={conn_data}")
                    QMessageBox.warning(self, "加载警告", f"恢复连接时发生错误: {e}")

        # --- 验证和清理无效的跳转参数 ---
        debug_print(f"DEBUG [load_workflow]: Validating jump target parameters...")
        self._validate_and_cleanup_jump_targets()

        # --- Call final update AFTER processing cards and SEQUENTIAL connections from JSON ---
        # This will calculate sequence IDs. Jump lines prefer serialized data when present,
        # and only fall back to parameter rebuild for older workflows that didn't persist them.
        skip_jump_rebuild = restored_serialized_jump_connections > 0
        debug_print(
            f"DEBUG [load_workflow]: Finished loading cards/connections from JSON. "
            f"Calling final update_card_sequence_display(skip_jump_rebuild={skip_jump_rebuild})..."
        )
        self.update_card_sequence_display(skip_jump_rebuild=skip_jump_rebuild)
        self._refresh_thread_start_custom_names()
        try:
            self._sync_connections_with_scene()
            self.cleanup_all_duplicate_connections()
        except Exception:
            pass
        debug_print(f"DEBUG [load_workflow]: Finished final update_card_sequence_display.")

        # --- ADDED: Explicitly set sceneRect before restoring view --- 
        try:
            if self.scene.items():
                items_rect = self.scene.itemsBoundingRect()
                # Add generous padding to ensure center target is well within bounds
                padded_rect = items_rect.adjusted(-FIT_VIEW_PADDING * 2, -FIT_VIEW_PADDING * 2,
                                                FIT_VIEW_PADDING * 2, FIT_VIEW_PADDING * 2)
                debug_print(f"  [LOAD_DEBUG] Calculated items bounding rect (padded): {padded_rect}")
                self.scene.setSceneRect(padded_rect)
                debug_print(f"  [LOAD_DEBUG] Set sceneRect to encompass all items before view restore.")
            else:
                debug_print("  [LOAD_DEBUG] No items found, skipping sceneRect adjustment before view restore.")
        except Exception as e_sr:
            debug_print(f"  [LOAD_DEBUG] Error calculating/setting sceneRect before view restore: {e_sr}")
        # --- END ADDED ---

        # --- View restoration block (already moved to the end) ---
        debug_print(f"DEBUG [load_workflow]: Attempting to restore view transform and center (at the end)...")
        try:
            view_transform_data = workflow_data.get('view_transform') 
            debug_print(f"  [LOAD_DEBUG] Raw view_transform data from file: {view_transform_data}")
            data_exists = bool(view_transform_data)
            is_list = isinstance(view_transform_data, list)
            correct_length = len(view_transform_data) == 9 if is_list else False
            debug_print(f"  [LOAD_DEBUG] Condition checks: Exists={data_exists}, IsList={is_list}, LengthIs9={correct_length}")
            transform_restored = False
            if data_exists and is_list and correct_length:
                saved_transform = QTransform(
                    view_transform_data[0], view_transform_data[1], 0,
                    view_transform_data[3], view_transform_data[4], 0,
                    view_transform_data[6], view_transform_data[7], 1
                )
                self.setTransform(saved_transform)
                transform_restored = True
                debug_print("视图变换 (缩放/平移基点) 已恢复。")
                # 【性能优化】通知连线动画系统当前缩放级别
                self._notify_zoom_level_changed()

                view_center_data = workflow_data.get('view_center')
                debug_print(f"  [LOAD_DEBUG] Raw view_center data from file: {view_center_data}")
                if isinstance(view_center_data, list) and len(view_center_data) == 2:
                    try:
                        saved_center_point = QPointF(view_center_data[0], view_center_data[1])
                        QTimer.singleShot(100, lambda p=saved_center_point: self._deferred_center_view(p))
                        debug_print(f"  [LOAD_DEBUG] Scheduling deferred centering on {saved_center_point}.")
                    except ValueError as center_val_e:
                        logger.warning(f"无法创建中心点 QPointF: {center_val_e}")
                    except Exception as center_e:
                        logger.warning(f"加载视图中心时出错: {center_e}")
                else:
                     logger.warning(f"无法恢复视图中心，数据无效: {view_center_data}")
            else:
                logger.info("未从文件恢复视图变换。") # No valid transform data found

  
        except Exception as e:
            debug_print(f"警告: 恢复视图变换或中心时出错: {e}")
            # --- END ADDED Block ---

        # <<< CORRECTED INDENTATION: Moved INSIDE the main try block >>>
        logger.info(f"工作流已从数据字典加载完成。卡片数: {len(self.cards)}, 连接数: {len(self.connections)}")

        # 【性能优化】移除冗余的验证调用 - update_card_sequence_display 已经做了验证
        # validate_connections 和 cleanup_orphaned_connections 在 update_card_sequence_display 中已调用

        # 无论是否有异常，都要确保清除加载工作流标志
        # 清除加载工作流标志
        self._loading_workflow = False
        debug_print(f"  [UNDO] Cleared loading workflow flag")
        logger.info(f"  [UNDO] Cleared loading workflow flag")

    def _register_result_placeholders_after_load(self):
        """工作流加载完成后批量注册结果变量占位符，避免逐卡阻塞。"""
        if not self.cards:
            return

        placeholder_map: Dict[int, List[str]] = {}
        for card in self.cards.values():
            try:
                name_key = "save_result_variable_name"
                current_name = str(card.parameters.get(name_key, "") or "").strip()
                normalized_name = f"卡片{card.card_id}结果"
                if not current_name:
                    card.parameters[name_key] = normalized_name
                    current_name = normalized_name
                else:
                    is_default_name = False
                    if hasattr(card, "_is_default_result_variable_name"):
                        try:
                            is_default_name = bool(card._is_default_result_variable_name(current_name))
                        except Exception:
                            is_default_name = False
                    if not is_default_name:
                        is_default_name = bool(re.fullmatch(r"卡片\d+结果", current_name))
                    if is_default_name and current_name != normalized_name:
                        card.parameters[name_key] = normalized_name
                        current_name = normalized_name
                suffixes = card._get_result_variable_suffixes() if hasattr(card, "_get_result_variable_suffixes") else []
                placeholder_map[int(card.card_id)] = [f"{current_name}.{suffix}" for suffix in suffixes]
            except Exception:
                continue

        if not placeholder_map:
            return

        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            if hasattr(context, "register_result_placeholders_batch"):
                context.register_result_placeholders_batch(placeholder_map)
            else:
                for card_id, names in placeholder_map.items():
                    context.register_card_result_placeholders(card_id, names)
        except Exception as e:
            logger.warning(f"批量注册结果变量占位符失败: {e}")
