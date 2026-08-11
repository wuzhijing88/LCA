from ..parameter_panel_support import *


class ParameterPanelRecordingHotkeyReplayMixin:
    def _register_replay_hotkey(self):
        """注册回放快捷键"""
        if self._replay_hotkey_registered:
            return

        try:
            import keyboard
            # 从父窗口获取回放快捷键配置
            if hasattr(self.parent_window, 'replay_hotkey'):
                replay_key = self.parent_window.replay_hotkey.lower()
                conflicts = {}
                if hasattr(self.parent_window, '_get_hotkey_value'):
                    conflicts = {
                        '启动任务': self.parent_window._get_hotkey_value('start').lower(),
                        '停止任务': self.parent_window._get_hotkey_value('stop').lower(),
                        '暂停/恢复': self.parent_window._get_hotkey_value('pause').lower(),
                    }
                record_key = ''
                if hasattr(self.parent_window, 'record_hotkey'):
                    record_key = self.parent_window.record_hotkey.lower()
                    conflicts['录制'] = record_key
                for name, key in conflicts.items():
                    if key and replay_key == key:
                        QMessageBox.warning(self, "快捷键冲突", f"回放快捷键与{name}快捷键冲突：{replay_key.upper()}")
                        return

                # 注册快捷键
                if replay_key in ['xbutton1', 'xbutton2']:
                    # 鼠标侧键
                    import mouse
                    mouse_button = 'x' if replay_key == 'xbutton1' else 'x2'
                    self._replay_mouse_hook = mouse.on_button(
                        self._on_replay_hotkey,
                        buttons=(mouse_button,),
                        types=('down',)
                    )
                    logger.info(f"回放快捷键已注册: {replay_key.upper()} (鼠标侧键)")
                else:
                    # 键盘快捷键
                    self._replay_hotkey_handle = keyboard.add_hotkey(
                        replay_key,
                        self._on_replay_hotkey,
                        trigger_on_release=False,
                        suppress=True
                    )
                    logger.info(f"回放快捷键已注册: {replay_key.upper()}")

                self._replay_hotkey_registered = True
            else:
                logger.warning("无法获取回放快捷键配置")

        except Exception as e:
            logger.error(f"注册回放快捷键失败: {e}", exc_info=True)

    def _unregister_replay_hotkey(self):
        """注销回放快捷键"""
        if (
            not self._replay_hotkey_registered
            and self._replay_hotkey_handle is None
            and self._replay_mouse_hook is None
        ):
            return

        self._cleanup_recording_hotkey_binding(
            handle_attr="_replay_hotkey_handle",
            mouse_hook_attr="_replay_mouse_hook",
            registered_attr="_replay_hotkey_registered",
            label="回放",
        )

    def _on_replay_hotkey(self):
        """回放快捷键回调"""
        try:
            if QThread.currentThread() != self.thread():
                QTimer.singleShot(0, self, self._on_replay_hotkey)
                return
            if not self._is_recording_panel_active:
                return

            # 触发回放操作
            logger.info("快捷键触发:开始回放")
            self._start_replay()

        except Exception as e:
            logger.error(f"回放快捷键回调失败: {e}", exc_info=True)
