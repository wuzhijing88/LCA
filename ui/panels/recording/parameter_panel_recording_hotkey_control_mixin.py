from ..parameter_panel_support import *


class ParameterPanelRecordingHotkeyControlMixin:
    def _cleanup_recording_hotkey_binding(
        self,
        *,
        handle_attr: str,
        mouse_hook_attr: str,
        registered_attr: str,
        label: str,
    ) -> None:
        """安全清理录制面板快捷键绑定，允许重复调用。"""
        handle = getattr(self, handle_attr, None)
        mouse_hook = getattr(self, mouse_hook_attr, None)
        was_registered = bool(getattr(self, registered_attr, False))

        try:
            if handle is not None:
                try:
                    import keyboard

                    keyboard.remove_hotkey(handle)
                except (KeyError, ValueError) as exc:
                    logger.debug(f"{label}快捷键句柄已失效，按已注销处理: {exc}")
                except Exception as exc:
                    logger.error(f"注销{label}快捷键失败: {exc}", exc_info=True)

            if mouse_hook is not None:
                try:
                    import mouse

                    mouse.unhook(mouse_hook)
                except Exception as exc:
                    logger.debug(f"{label}鼠标钩子已失效，按已注销处理: {exc}")
        finally:
            setattr(self, handle_attr, None)
            setattr(self, mouse_hook_attr, None)
            setattr(self, registered_attr, False)

        if was_registered or handle is not None or mouse_hook is not None:
            logger.info(f"{label}快捷键已注销")

    def _reset_action_control_buttons(self):
        """
        重置动作录制/回放/编辑按钮状态
        """
        record_widget = self.widgets.get('record_control')
        if record_widget:
            record_widget.setText("开始录制")

        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setText("测试回放")
            replay_widget.setEnabled(False)

        edit_widget = self.widgets.get('edit_actions')
        if edit_widget:
            edit_widget.setText("编辑步骤")
            edit_widget.setEnabled(False)

    def _stop_combo_key_sequence_recording(self):
        """停止组合键序列录制（如果正在录制）。"""
        try:
            if not bool(getattr(self, "_combo_seq_recording_active", False)):
                return

            hook = getattr(self, "_combo_seq_recording_hook", None)
            if hook is not None:
                try:
                    import keyboard
                    keyboard.unhook(hook)
                except Exception:
                    pass
        finally:
            setattr(self, "_combo_seq_recording_active", False)
            setattr(self, "_combo_seq_recording_hook", None)
            setattr(self, "_combo_seq_recording_events", [])
            setattr(self, "_combo_seq_recording_pressed_keys", set())
            setattr(self, "_combo_seq_block_global_record_hotkey", False)
