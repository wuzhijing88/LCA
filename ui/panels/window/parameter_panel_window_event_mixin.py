from ..parameter_panel_support import *


class ParameterPanelWindowEventMixin:

        def event(self, event):

            """重写事件处理，监听窗口激活事件"""

            if event.type() == event.Type.WindowActivate:

                # 当小窗口被激活时，不要自动激活主窗口，让用户能正常输入

                # 只有在用户明确需要时才激活主窗口

                pass

            return super().event(event)





        def changeEvent(self, event):

            """处理窗口状态变化事件"""

            if event.type() == QEvent.Type.ActivationChange:

                # 智能激活同步：保护输入框焦点

                if self.isActiveWindow() and self.parent_window and self._snap_to_parent_enabled:

                    self._smart_activate_main_window()

            super().changeEvent(event)





        def closeEvent(self, event):

            """处理窗口关闭事件"""

            logger.debug(f"参数面板关闭事件 - card_id: {self.current_card_id}")

            self.manually_closed = True  # 标记为用户手动关闭

            self._stop_combo_key_sequence_recording()



            # 停止回放线程

            if hasattr(self, '_replay_thread') and self._replay_thread and self._replay_thread.isRunning():

                try:

                    self._replay_thread.stop()

                except Exception:

                    pass



            # 注销录制和回放快捷键

            self._unregister_record_hotkey()

            self._unregister_replay_hotkey()

            self._is_recording_panel_active = False

            self._clear_favorites_runtime_refs()



            self.panel_closed.emit()

            # 注意：不要在这里重置 current_card_id

            event.accept()
