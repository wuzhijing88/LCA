from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureEditorMixin:

    def _open_action_editor(self):
            """打开步骤编辑器"""
            logger.info("打开步骤编辑器")
    
            # 检查是否正在录制
            if hasattr(self, '_recording_active') and self._recording_active:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "提示", "录制过程中不能编辑步骤，请先停止录制")
                return
    
            try:
                # 获取当前录制数据
                recorded_data = self.current_parameters.get('recorded_actions', '')
                actions = []
                recording_area = '全屏录制'  # 默认值
                recording_mode = '绝对坐标'  # 默认值
    
                if recorded_data:
                    import json
                    try:
                        data = json.loads(recorded_data)
    
                        # 兼容新旧格式
                        if isinstance(data, dict) and 'actions' in data:
                            # 新格式：包含元数据
                            actions = data['actions']
                            recording_area = data.get('recording_area', '全屏录制')  # 获取录制区域
                            recording_mode = data.get('recording_mode', '绝对坐标')  # 获取录制模式
                        elif isinstance(data, list):
                            # 旧格式：纯动作列表
                            actions = data
                        else:
                            logger.error("录制数据格式错误")
                            from PySide6.QtWidgets import QMessageBox
                            QMessageBox.warning(self, "错误", "录制数据格式错误")
                            return
                    except Exception as e:
                        logger.error(f"解析录制数据失败: {e}")
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "错误", f"无法解析录制数据: {e}")
                        return
    
                # 导入步骤编辑器对话框
                from ui.dialogs.action_editor_dialog import ActionEditorDialog
    
                # 创建并显示编辑器（传入录制区域和录制模式信息）
                editor = ActionEditorDialog(actions, recording_area, self, recording_mode)
    
                # 连接信号
                def on_actions_updated(updated_actions):
                    """步骤更新回调"""
                    try:
                        # 保留原有的recording_area和recording_mode信息（如果存在）
                        import json
                        recording_area = '全屏录制'  # 默认值
                        recording_mode = '绝对坐标'  # 默认值
                        if recorded_data:
                            original_data = json.loads(recorded_data)
                            if isinstance(original_data, dict):
                                if 'recording_area' in original_data:
                                    recording_area = original_data['recording_area']
                                if 'recording_mode' in original_data:
                                    recording_mode = original_data['recording_mode']
    
                        # 创建包含元数据的新格式
                        recording_data = {
                            'recording_area': recording_area,
                            'recording_mode': recording_mode,
                            'actions': updated_actions
                        }
    
                        # 转换为JSON字符串
                        json_str = json.dumps(recording_data, ensure_ascii=False)
    
                        # 更新当前参数
                        self.current_parameters['recorded_actions'] = json_str
    
                        # 更新隐藏字段
                        if 'recorded_actions' in self.widgets:
                            self.widgets['recorded_actions'].setText(json_str)
    
                        # 更新编辑步骤按钮文本
                        if 'edit_actions' in self.widgets:
                            btn = self.widgets['edit_actions']
                            if updated_actions:
                                btn.setText(f"编辑步骤 ({len(updated_actions)}个)")
                            else:
                                btn.setText("编辑步骤")
    
                        # 更新回放按钮文本
                        if 'replay_control' in self.widgets:
                            btn = self.widgets['replay_control']
                            if updated_actions:
                                btn.setText(f"测试回放 ({len(updated_actions)}个操作)")
                            else:
                                btn.setText("测试回放")
    
                        # 发送参数更新信号
                        self.parameters_changed.emit(self.current_card_id, self.current_parameters.copy())
    
                        logger.info(f"步骤已更新，共 {len(updated_actions)} 个")
    
                    except Exception as e:
                        logger.error(f"更新步骤数据失败: {e}", exc_info=True)
    
                editor.actions_updated.connect(on_actions_updated)
    
                # 显示对话框
                result = editor.exec()
    
                if result == editor.DialogCode.Accepted:
                    logger.info("步骤编辑已保存")
                else:
                    logger.info("步骤编辑已取消")
    
            except Exception as e:
                logger.error(f"打开步骤编辑器失败: {e}", exc_info=True)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "错误", f"打开步骤编辑器失败: {e}")
