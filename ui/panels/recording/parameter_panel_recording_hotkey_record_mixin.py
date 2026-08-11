from ..parameter_panel_support import *


class ParameterPanelRecordingHotkeyRecordMixin:
    def _check_and_register_record_hotkey(self):
        """检查是否是录制回放卡片,并注册录制和回放快捷键"""
        try:
            # 先注销之前的快捷键
            self._unregister_record_hotkey()
            self._unregister_replay_hotkey()

            # 检查是否是录制回放卡片
            if self.current_task_type and '录制回放' in self.current_task_type:
                self._is_recording_panel_active = True
                self._register_record_hotkey()
                self._register_replay_hotkey()
                logger.info("检测到录制回放卡片,已注册录制和回放快捷键")
            else:
                self._is_recording_panel_active = False
                logger.debug(f"当前卡片类型: {self.current_task_type}, 不是录制回放卡片")

        except Exception as e:
            logger.error(f"检查并注册录制快捷键失败: {e}", exc_info=True)

    def _register_record_hotkey(self):
        """注册录制快捷键"""
        if self._record_hotkey_registered:
            return

        try:
            import keyboard
            # 从父窗口获取录制快捷键配置
            if hasattr(self.parent_window, 'record_hotkey'):
                record_key = self.parent_window.record_hotkey.lower()
                conflicts = {}
                if hasattr(self.parent_window, '_get_hotkey_value'):
                    conflicts = {
                        '启动任务': self.parent_window._get_hotkey_value('start').lower(),
                        '停止任务': self.parent_window._get_hotkey_value('stop').lower(),
                        '暂停/恢复': self.parent_window._get_hotkey_value('pause').lower(),
                    }
                replay_key = ''
                if hasattr(self.parent_window, 'replay_hotkey'):
                    replay_key = self.parent_window.replay_hotkey.lower()
                    conflicts['回放'] = replay_key
                for name, key in conflicts.items():
                    if key and record_key == key:
                        QMessageBox.warning(self, "快捷键冲突", f"录制快捷键与{name}快捷键冲突：{record_key.upper()}")
                        return

                # 注册快捷键
                if record_key in ['xbutton1', 'xbutton2']:
                    # 鼠标侧键
                    import mouse
                    mouse_button = 'x' if record_key == 'xbutton1' else 'x2'
                    self._record_mouse_hook = mouse.on_button(
                        self._on_record_hotkey,
                        buttons=(mouse_button,),
                        types=('down',)
                    )
                    logger.info(f"录制快捷键已注册: {record_key.upper()} (鼠标侧键)")
                else:
                    # 键盘快捷键
                    self._record_hotkey_handle = keyboard.add_hotkey(
                        record_key,
                        self._on_record_hotkey,
                        trigger_on_release=False,
                        suppress=True
                    )
                    logger.info(f"录制快捷键已注册: {record_key.upper()}")

                self._record_hotkey_registered = True
            else:
                logger.warning("无法获取录制快捷键配置")

        except Exception as e:
            logger.error(f"注册录制快捷键失败: {e}", exc_info=True)

    def _unregister_record_hotkey(self):
        """注销录制快捷键"""
        if (
            not self._record_hotkey_registered
            and self._record_hotkey_handle is None
            and self._record_mouse_hook is None
        ):
            return

        self._cleanup_recording_hotkey_binding(
            handle_attr="_record_hotkey_handle",
            mouse_hook_attr="_record_mouse_hook",
            registered_attr="_record_hotkey_registered",
            label="录制",
        )

    def _on_record_hotkey(self):
        """录制快捷键回调"""
        try:
            if QThread.currentThread() != self.thread():
                QTimer.singleShot(0, self, self._on_record_hotkey)
                return
            if not self._is_recording_panel_active:
                return

            logger.debug(f"录制快捷键触发，当前状态: _recording_active={getattr(self, '_recording_active', False)}")

            if getattr(self, '_recording_active', False):
                # 刚开始录制时，忽略短时间内的重复触发，避免立即停止
                start_time = getattr(self, '_recording_start_time', None)
                if start_time is not None and (time.time() - start_time) < 0.5:
                    logger.debug("录制刚开始，忽略本次停止触发")
                    return
                # 正在录制,停止录制 - 停止操作不受防抖限制
                logger.debug("检测到正在录制，将停止录制")
                self._stop_recording()
            else:
                # 未在录制,启动录制 - 开始操作需要防抖
                if hasattr(self, '_recording_state_changing') and self._recording_state_changing:
                    logger.debug("录制状态正在转换中，忽略开始录制请求")
                    return
                logger.debug("检测到未在录制，将启动录制")
                self._start_recording()

        except Exception as e:
            logger.error(f"录制快捷键回调失败: {e}", exc_info=True)
