from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_activate_overlay, show_and_raise_widget


class ParameterPanelRecordingCaptureFinishMixin:

    def _on_recording_finished(self, actions):
            """录制完成回调"""
            try:
                logger.info(f"录制完成回调触发，收到 {len(actions)} 个操作")
    
                # 隐藏浮窗
                if hasattr(self, '_recording_panel') and self._recording_panel:
                    self._recording_panel.stop_recording()
                    logger.info("已隐藏录制控制浮窗")
    
                # 恢复参数面板和主窗口
                if hasattr(self, '_was_panel_visible') and self._was_panel_visible:
                    show_and_activate_overlay(self, log_prefix='参数面板恢复', focus=True)
                    logger.info("已恢复参数面板可见性")

                if hasattr(self, '_main_window') and self._main_window and hasattr(self, '_was_main_window_visible') and self._was_main_window_visible:
                    show_and_raise_widget(self._main_window, log_prefix='主窗口恢复')
                    logger.info("已恢复主窗口可见性")
    
                # 清除录制状态
                self._recording_active = False
                self._recording_state_changing = False
    
                # 录制阶段已经根据精度参数控制了记录频率，这里不需要再优化
                # 直接使用录制的数据
                optimized_actions = actions
    
                # 保存数据（包含录制区域信息）
                import json
    
                # 创建包含元数据的录制数据结构
                recording_data = {
                    'recording_area': self.current_parameters.get('recording_area', '全屏录制'),
                    'recording_mode': self.current_parameters.get('recording_mode', '绝对坐标'),
                    'actions': optimized_actions
                }
    
                json_data = json.dumps(recording_data, ensure_ascii=False)
                self.current_parameters['recorded_actions'] = json_data
    
                # 更新录制按钮 - 恢复原始样式
                control_widget = self.widgets.get('record_control')
                if control_widget:
                    control_widget.setText(f"录制完成 ({len(optimized_actions)}个操作)")
                    control_widget.setProperty("class", "primary")
                    control_widget.setEnabled(True)  # 重新启用按钮
    
                # 更新回放按钮 - 显示最新的操作数量
                replay_widget = self.widgets.get('replay_control')
                if replay_widget:
                    replay_widget.setText(f"测试回放 ({len(optimized_actions)}个操作)")
                    replay_widget.setEnabled(True)  # 录制完成后重新启用回放按钮
                    logger.info("录制完成，已重新启用回放按钮")
    
                # 更新编辑步骤按钮 - 显示最新的操作数量
                edit_widget = self.widgets.get('edit_actions')
                if edit_widget:
                    edit_widget.setText(f"编辑步骤 ({len(optimized_actions)}个)")
                    edit_widget.setEnabled(True)  # 录制完成后重新启用编辑步骤按钮
                    logger.info("录制完成，已重新启用步骤编辑按钮")
    
                # 发送参数更改信号
                self.parameters_changed.emit(self.current_card_id, self.current_parameters.copy())
    
                # 统计信息
                mouse_moves = sum(1 for a in optimized_actions if a['type'] == 'mouse_move')
                mouse_moves_relative = sum(1 for a in optimized_actions if a['type'] == 'mouse_move_relative')
                mouse_clicks = sum(1 for a in optimized_actions if a['type'] == 'mouse_click')
                key_presses = sum(1 for a in optimized_actions if a['type'] == 'key_press')
                area_text = self.current_parameters.get('recording_area', '全屏录制')
                mode_text = self.current_parameters.get('recording_mode', '绝对坐标')
                logger.info(f"录制完成 ({area_text}, {mode_text}), 共{len(optimized_actions)}个操作 (绝对移动:{mouse_moves}, 相对移动:{mouse_moves_relative}, 点击:{mouse_clicks}, 按键:{key_presses})")
    
                self._recording_active = False
    
            except Exception as e:
                logger.error(f"处理录制完成失败: {e}", exc_info=True)
