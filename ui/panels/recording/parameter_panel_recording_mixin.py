from functools import partial

from ..parameter_panel_support import *
from .parameter_panel_recording_replay_thread import ParameterPanelReplayThread
from utils.window.window_activation_utils import resolve_replay_window_offsets_from_config
from utils.window.window_activation_utils import (
    activate_window,
    load_enabled_bound_window_hwnd_from_config,
    resolve_window_activation_hwnd,
    resolve_window_client_offset,
    resolve_window_client_rect,
)
from utils.window.window_activation_utils import show_and_raise_widget
from app_core.hotkey_spec import (
    display_hotkey,
    is_mouse_hotkey,
    mouse_hook_button,
    normalize_hotkey,
    to_keyboard_lib,
)

class ParameterPanelRecordingMixin:

    def _cleanup_recording_hotkey_binding(self, *, handle_attr, mouse_hook_attr, registered_attr, label):
        handle = getattr(self, handle_attr, None)
        mouse_hook = getattr(self, mouse_hook_attr, None)
        if handle is not None:
            import keyboard
            keyboard.remove_hotkey(handle)
            setattr(self, handle_attr, None)
        if mouse_hook is not None:
            import mouse
            mouse.unhook(mouse_hook)
            setattr(self, mouse_hook_attr, None)
        self._resources.forget_cleanup(registered_attr)
        setattr(self, registered_attr, False)

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
        hook = getattr(self, '_combo_seq_recording_hook', None)
        mouse_hooks = getattr(self, '_combo_seq_recording_mouse_hooks', [])
        if hook is not None or mouse_hooks:
            import keyboard
            import mouse
            from tasks.keyboard_input import _cleanup_combo_sequence_recording
            _cleanup_combo_sequence_recording(self, keyboard, mouse)
        else:
            self._combo_seq_recording_active = False
            self._combo_seq_recording_events = []
            self._combo_seq_recording_pressed_keys = set()
            self._combo_seq_block_global_record_hotkey = False
        self._resources.forget_cleanup('combo-recording')

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
                record_key = normalize_hotkey(self.parent_window.record_hotkey)
                conflicts = {}
                if hasattr(self.parent_window, '_get_hotkey_value'):
                    conflicts = {
                        '启动任务': self.parent_window._get_hotkey_value('start'),
                        '停止任务': self.parent_window._get_hotkey_value('stop'),
                        '暂停/恢复': self.parent_window._get_hotkey_value('pause'),
                    }
                replay_key = ''
                if hasattr(self.parent_window, 'replay_hotkey'):
                    replay_key = normalize_hotkey(self.parent_window.replay_hotkey)
                    conflicts['回放'] = replay_key
                for name, key in conflicts.items():
                    if key and record_key == key:
                        QMessageBox.warning(self, "快捷键冲突", f"录制快捷键与{name}快捷键冲突：{display_hotkey(record_key)}")
                        return

                if is_mouse_hotkey(record_key):
                    import mouse
                    mouse_button = mouse_hook_button(record_key)
                    self._record_mouse_hook = mouse.on_button(
                        self._on_record_hotkey,
                        buttons=(mouse_button,),
                        types=('down',)
                    )
                    logger.info(f"录制快捷键已注册: {display_hotkey(record_key)} (鼠标侧键)")
                else:
                    lib_key = to_keyboard_lib(record_key)
                    self._record_hotkey_handle = keyboard.add_hotkey(
                        lib_key,
                        self._on_record_hotkey,
                        trigger_on_release=False,
                        suppress=True
                    )
                    logger.info(f"录制快捷键已注册: {display_hotkey(record_key)}")

                cleanup = self._unregister_record_hotkey
                self._resources.bind_cleanup('_record_hotkey_registered', cleanup)
                self._record_hotkey_registered = True
            else:
                logger.warning("无法获取录制快捷键配置")

        except Exception as e:
            self._unregister_record_hotkey()
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
            from utils.instance_runtime import should_handle_hotkey
            parent = getattr(self, "parent_window", None)
            if not should_handle_hotkey(getattr(parent, "bound_windows", None) if parent else None):
                if parent is not None and hasattr(parent, "_notify_hotkey_routed_away"):
                    parent._notify_hotkey_routed_away()
                return
            if not self._is_recording_panel_active:
                return
            parent = getattr(self, "parent_window", None)
            if parent is not None and hasattr(parent, "is_hotkey_listen_enabled") and not parent.is_hotkey_listen_enabled():
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

    def _register_replay_hotkey(self):
        """注册回放快捷键"""
        if self._replay_hotkey_registered:
            return

        try:
            import keyboard
            # 从父窗口获取回放快捷键配置
            if hasattr(self.parent_window, 'replay_hotkey'):
                replay_key = normalize_hotkey(self.parent_window.replay_hotkey)
                conflicts = {}
                if hasattr(self.parent_window, '_get_hotkey_value'):
                    conflicts = {
                        '启动任务': self.parent_window._get_hotkey_value('start'),
                        '停止任务': self.parent_window._get_hotkey_value('stop'),
                        '暂停/恢复': self.parent_window._get_hotkey_value('pause'),
                    }
                record_key = ''
                if hasattr(self.parent_window, 'record_hotkey'):
                    record_key = normalize_hotkey(self.parent_window.record_hotkey)
                    conflicts['录制'] = record_key
                for name, key in conflicts.items():
                    if key and replay_key == key:
                        QMessageBox.warning(self, "快捷键冲突", f"回放快捷键与{name}快捷键冲突：{display_hotkey(replay_key)}")
                        return

                if is_mouse_hotkey(replay_key):
                    import mouse
                    mouse_button = mouse_hook_button(replay_key)
                    self._replay_mouse_hook = mouse.on_button(
                        self._on_replay_hotkey,
                        buttons=(mouse_button,),
                        types=('down',)
                    )
                    logger.info(f"回放快捷键已注册: {display_hotkey(replay_key)} (鼠标侧键)")
                else:
                    lib_key = to_keyboard_lib(replay_key)
                    self._replay_hotkey_handle = keyboard.add_hotkey(
                        lib_key,
                        self._on_replay_hotkey,
                        trigger_on_release=False,
                        suppress=True
                    )
                    logger.info(f"回放快捷键已注册: {display_hotkey(replay_key)}")

                cleanup = self._unregister_replay_hotkey
                self._resources.bind_cleanup('_replay_hotkey_registered', cleanup)
                self._replay_hotkey_registered = True
            else:
                logger.warning("无法获取回放快捷键配置")

        except Exception as e:
            self._unregister_replay_hotkey()
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
            from utils.instance_runtime import should_handle_hotkey
            parent = getattr(self, "parent_window", None)
            if not should_handle_hotkey(getattr(parent, "bound_windows", None) if parent else None):
                if parent is not None and hasattr(parent, "_notify_hotkey_routed_away"):
                    parent._notify_hotkey_routed_away()
                return
            parent = getattr(self, "parent_window", None)
            if parent is not None and hasattr(parent, "is_hotkey_listen_enabled") and not parent.is_hotkey_listen_enabled():
                return

            if getattr(self, "_replay_active", False):
                logger.info("快捷键触发:停止回放")
                self._stop_replay()
                return
            if not self._is_recording_panel_active:
                return
            logger.info("快捷键触发:开始回放")
            self._start_replay()

        except Exception as e:
            logger.error(f"回放快捷键回调失败: {e}", exc_info=True)

    def _toggle_recording(self):
            """切换录制状态（开始/停止） - 用于按钮点击"""
            if hasattr(self, '_recording_active') and self._recording_active:
                # 正在录制，点击停止 - 停止操作不受防抖限制
                logger.info("按钮点击: 停止录制")
                self._stop_recording()
            else:
                # 未录制，点击开始 - 开始操作需要防抖
                if hasattr(self, '_recording_state_changing') and self._recording_state_changing:
                    logger.warning("录制状态正在转换中，忽略开始录制请求")
                    return
                logger.info("按钮点击: 开始录制")
                self._start_recording()

    _REPLAY_AREA_WINDOW = '窗口录制'

    _REPLAY_MODE_DEFAULT = '绝对坐标'

    _REPLAY_AREA_DEFAULT = '全屏录制'

    def _get_recorded_actions_payload_or_warn(self):
        recorded_data = self.current_parameters.get('recorded_actions', '')
        if not recorded_data:
            logger.warning('没有可回放的录制数据')
            self._show_replay_message(
                QMessageBox.Icon.Warning,
                '提示',
                '没有可回放的录制数据，请先录制操作',
            )
            return None

        try:
            payload = self._parse_recorded_actions_payload(recorded_data)
        except ValueError as e:
            logger.error(f"录制数据格式错误: {e}")
            self._show_replay_message(QMessageBox.Icon.Critical, '错误', str(e))
            return None

        if not payload.get('actions'):
            logger.warning('没有可回放的录制数据')
            self._show_replay_message(
                QMessageBox.Icon.Warning,
                '提示',
                '没有可回放的录制数据，请先录制操作',
            )
            return None
        return payload

    def _parse_recorded_actions_payload(self, recorded_data):
        data = json.loads(recorded_data) if isinstance(recorded_data, str) else recorded_data
        if not isinstance(data, dict) or set(data) != {'actions', 'recording_area', 'recording_mode'}:
            raise ValueError('录制数据必须是现行结构，旧数据请先转换工程格式')
        if not isinstance(data['actions'], list):
            raise ValueError('录制步骤必须是列表')
        if data['recording_area'] not in {'全屏录制', '窗口录制'} or data['recording_mode'] not in {'绝对坐标', '相对位移'}:
            raise ValueError('录制区域或模式无效')
        return {**data, 'raw': recorded_data}

    def _get_recorded_action_count(self) -> int:
        recorded_data = self.current_parameters.get('recorded_actions', '')
        if not recorded_data:
            return 0
        try:
            payload = self._parse_recorded_actions_payload(recorded_data)
            return len(payload['actions'])
        except Exception:
            return 0

    def _show_replay_message(self, icon, title: str, text: str) -> None:
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setWindowModality(Qt.WindowModality.ApplicationModal)
        msg_box.exec()

    _REPLAY_BUTTON_DEFAULT = '测试回放'

    _REPLAY_BUTTON_RUNNING = '停止回放'

    _REPLAY_BUTTON_STOPPING = '正在停止...'

    def _toggle_replay(self):
        if getattr(self, '_replay_active', False):
            self._stop_replay()
        else:
            self._start_replay()

    def _stop_replay(self):
        logger.info('用户请求停止回放')
        thread = getattr(self, '_replay_thread', None)
        if not thread or not thread.isRunning():
            return False
        thread.stop()
        logger.info('已发送回放停止信号')
        self._set_replay_button_stopping_state()
        return True

    def stop_test_replay(self) -> bool:
        """停止测试回放（参数面板或步骤编辑器）。"""
        stopped = False
        thread = getattr(self, "_replay_thread", None)
        if thread is not None and thread.isRunning():
            self._stop_replay()
            stopped = True
        editor = getattr(self, "_action_editor", None)
        stop_editor = getattr(editor, "_stop_active_replay_thread", None)
        if callable(stop_editor):
            stop_editor()
            stopped = True
        return stopped

    def _set_replay_button_running_state(self):
        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setText(self._REPLAY_BUTTON_RUNNING)
            replay_widget.setProperty('class', 'danger')
            replay_widget.setEnabled(True)

    def _set_replay_button_stopping_state(self):
        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setText(self._REPLAY_BUTTON_STOPPING)
            replay_widget.setEnabled(False)

    def _restore_replay_button_default_state(self):
        replay_widget = self.widgets.get('replay_control')
        if not replay_widget:
            return
        replay_widget.setProperty('class', 'primary')
        action_count = self._get_recorded_action_count()
        if action_count > 0:
            replay_widget.setText(f"测试回放 ({action_count}个操作)")
        else:
            replay_widget.setText(self._REPLAY_BUTTON_DEFAULT)
        replay_widget.setEnabled(True)

    @Slot()
    def _on_replay_finished(self):
        if self.sender() is not self._replay_thread:
            return
        try:
            self._replay_active = False
            self._restore_replay_button_default_state()
            logger.info('回放完成，状态标志已清除')
        except Exception as e:
            logger.error(f"处理回放完成失败: {e}", exc_info=True)
            self._replay_active = False

    @Slot()
    def _on_replay_thread_finished(self):
        if self.sender() is self._replay_thread:
            self._replay_thread = None

    def _start_replay(self):
        logger.info('开始回放操作')
        if not self._can_start_replay():
            return

        try:
            payload = self._get_recorded_actions_payload_or_warn()
            if payload is None:
                return

            window_offset_x, window_offset_y = self._resolve_replay_window_offsets(payload['recording_area'])
            if window_offset_x is None or window_offset_y is None:
                self._show_replay_message(
                    QMessageBox.Icon.Warning,
                    '提示',
                    '无法进行窗口回放，请检查绑定窗口配置或目标窗口状态',
                )
                return

            speed, loop_count = self._resolve_replay_runtime_options()
            self._set_replay_button_running_state()
            self._start_replay_thread(
                payload['actions'],
                speed,
                loop_count,
                payload['recording_area'],
                window_offset_x,
                window_offset_y,
                payload['recording_mode'],
            )
        except Exception as e:
            logger.error(f"启动回放失败: {e}", exc_info=True)
            self._show_replay_message(QMessageBox.Icon.Critical, '错误', f"启动回放失败: {e}")
            self._replay_active = False
            self._restore_replay_button_default_state()

    def _can_start_replay(self) -> bool:
        if getattr(self, '_replay_active', False):
            logger.warning('回放正在进行中，禁止重复调用')
            return False
        if getattr(self, '_recording_active', False):
            logger.warning('录制过程中不能使用回放功能')
            return False
        return True

    def _resolve_replay_runtime_options(self):
        import math
        speed = float(self.current_parameters['speed'])
        loop_count = self.current_parameters['loop_count']
        if not math.isfinite(speed) or not 0.1 <= speed <= 10:
            raise ValueError('回放速度必须在 0.1 到 10 之间')
        if isinstance(loop_count, bool) or not isinstance(loop_count, int) or not 1 <= loop_count <= 1000:
            raise ValueError('回放循环次数必须是 1 到 1000 之间的整数')
        return speed, loop_count

    def _start_replay_thread(
        self,
        actions,
        speed,
        loop_count,
        recording_area,
        window_offset_x,
        window_offset_y,
        recording_mode,
    ):
        self._replay_thread = ParameterPanelReplayThread(
            actions,
            speed,
            loop_count,
            recording_area,
            window_offset_x,
            window_offset_y,
            recording_mode,
        )
        self._resources.own_thread(self._replay_thread)
        self._replay_thread.finished_signal.connect(self._on_replay_finished)
        self._replay_thread.finished.connect(self._on_replay_thread_finished)
        self._replay_active = True
        self._replay_thread.start()
        logger.info('回放线程已启动，回放状态标志已设置')

    _REPLAY_WINDOW_LOG_PREFIX = '回放'

    def _resolve_replay_window_offsets(self, recording_area: str):
        return resolve_replay_window_offsets_from_config(
            recording_area,
            log_prefix=self._REPLAY_WINDOW_LOG_PREFIX,
        )

    def _load_enabled_bound_window_hwnd_from_config(self):
        return load_enabled_bound_window_hwnd_from_config()

    def _activate_bound_window(self, hwnd, log_prefix: str = ''):
        return activate_window(hwnd, log_prefix=log_prefix)

    def _resolve_bound_window_activation_hwnd(self, hwnd, log_prefix: str = ''):
        return resolve_window_activation_hwnd(hwnd, log_prefix=log_prefix)

    def _resolve_bound_window_client_rect(self, hwnd, log_prefix: str = ''):
        return resolve_window_client_rect(hwnd, log_prefix=log_prefix)

    def _resolve_bound_window_client_offset(self, hwnd, log_prefix: str = ''):
        return resolve_window_client_offset(hwnd, log_prefix=log_prefix)

    def _begin_recording_start_transition(self):
        self._recording_state_changing = True

    _CAPTURE_PRECISION_MAP = {
        '低 (0.2秒)': 0.2,
        '中 (0.1秒)': 0.1,
        '高 (0.05秒)': 0.05,
        '极高 (0.01秒)': 0.01,
    }

    def _get_capture_recording_options(self):
        recording_precision = self.current_parameters.get('recording_precision', '中 (0.1秒)')
        return {
            'record_mouse': self.current_parameters.get('record_mouse', True),
            'record_keyboard': self.current_parameters.get('record_keyboard', True),
            'recording_area': self.current_parameters.get('recording_area', '全屏录制'),
            'recording_mode': self.current_parameters.get('recording_mode', '绝对坐标'),
            'recording_precision': recording_precision,
            'mouse_move_interval': self._CAPTURE_PRECISION_MAP.get(recording_precision, 0.1),
        }

    def _load_capture_target_hwnd_from_config(self):
        try:
            hwnd = self._load_enabled_bound_window_hwnd_from_config()
            return hwnd, False
        except FileNotFoundError as error:
            config_path = error.args[0] if error.args else get_config_path()
            logger.error(f'未找到配置文件: {config_path}')
            QMessageBox.critical(self, '错误', '未找到配置文件，无法进行窗口录制')
            return None, True
        except Exception as error:
            logger.error(f'从config.json获取窗口句柄失败: {error}', exc_info=True)
            QMessageBox.critical(self, '错误', f'读取窗口配置失败: {error}')
            return None, True

    def _resolve_capture_window_context(self, recording_area: str):
        if recording_area != '窗口录制':
            return recording_area, None, False
        hwnd, abort_start = self._load_capture_target_hwnd_from_config()
        if abort_start:
            return recording_area, None, True
        if not hwnd:
            raise ValueError("没有可用的绑定窗口，无法进行窗口录制")
        import win32gui
        if not win32gui.IsWindow(hwnd):
            raise ValueError("绑定窗口已经失效，无法进行窗口录制")
        self._activate_bound_window(hwnd, log_prefix='录制')
        return recording_area, self._resolve_bound_window_client_rect(hwnd, log_prefix='录制'), False

    def _prepare_recording_widgets_for_active_state(self):
        control_widget = self.widgets.get('record_control')
        if control_widget:
            control_widget.setText('停止录制')
            control_widget.setProperty('class', 'danger')
            control_widget.setEnabled(True)

        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setEnabled(False)
            logger.info('录制状态下已禁用回放按钮')

        edit_widget = self.widgets.get('edit_actions')
        if edit_widget:
            edit_widget.setEnabled(False)
            logger.info('录制状态下已禁用步骤编辑按钮')

    def _hide_windows_for_recording_capture(self):
        self._capture_hidden = True
        self._was_panel_visible = self.isVisible()
        if self._was_panel_visible:
            self.hide()
            logger.info('已隐藏参数面板')

        self._main_window = None
        if self.parent_window:
            self._main_window = self.parent_window
            self._was_main_window_visible = self._main_window.isVisible()
            if self._was_main_window_visible:
                self._main_window.hide()
                logger.info('已隐藏主窗口')

    def _show_recording_control_panel(self):
        try:
            from ui.recording_parts.recording_control_panel import RecordingControlPanel

            logger.info('准备创建录制控制浮窗...')
            self._recording_panel = self._own_parameter_tool(RecordingControlPanel())
            self._recording_panel.stop_requested.connect(self._stop_recording)
            if hasattr(self._record_thread, 'step_count_updated'):
                self._record_thread.step_count_updated.connect(self._recording_panel.update_step_count)
            logger.info('浮窗已创建，准备启动...')
            self._recording_panel.start_recording()
            logger.info('录制控制浮窗已启动')
        except Exception as error:
            logger.error(f'创建录制控制浮窗失败: {error}', exc_info=True)
            raise RuntimeError(f'无法创建录制控制浮窗：{error}') from error

    def _resolve_record_hotkey(self):
        record_hotkey = None
        try:
            if hasattr(self, 'parent_window') and self.parent_window and hasattr(self.parent_window, 'config'):
                record_hotkey = self.parent_window.config.get('record_hotkey')
            if not record_hotkey and hasattr(self, 'parent_window') and self.parent_window:
                record_hotkey = getattr(self.parent_window, 'record_hotkey', None)
        except Exception:
            record_hotkey = None
        return normalize_hotkey(record_hotkey) or record_hotkey

    def _start_recording_capture_thread(self, options: Dict[str, Any], window_rect):
        from ui.recording_parts.hybrid_record_thread import HybridRecordThread

        self._record_thread = HybridRecordThread(
            duration=999999,
            record_mouse=options['record_mouse'],
            record_keyboard=options['record_keyboard'],
            recording_area=options['recording_area'],
            window_rect=window_rect,
            mouse_move_interval=options['mouse_move_interval'],
            recording_mode=options['recording_mode'],
            filter_record_hotkey=self._resolve_record_hotkey(),
        )
        self._resources.own_thread(self._record_thread)
        self._record_thread._panel_card_id = self.current_card_id
        self._record_thread.recording_failed.connect(self._on_recording_failed)
        self._record_thread.recording_finished.connect(self._on_recording_finished)
        self._record_thread.finished.connect(self._on_record_thread_finished)
        self._record_thread.start()
        self._recording_active = True
        self._recording_start_time = time.time()

        logger.info(
            '录制已启动: '
            f'区域={options["recording_area"]}, '
            f'模式={options["recording_mode"]}, '
            f'精度={options["recording_precision"]}'
        )
        logger.info(
            '录制线程状态: '
            f'isRunning={self._record_thread.isRunning()}, '
            f'use_raw_input={self._record_thread.use_raw_input}'
        )

    def _start_recording(self):
        """启动录制"""
        try:
            if self._record_thread is not None and self._record_thread.isRunning():
                raise RuntimeError("上一次录制尚未结束，请等待收尾")
            self._capture_hidden = False
            self._begin_recording_start_transition()
            logger.info('快捷键触发:开始录制')

            options = self._get_capture_recording_options()
            recording_area, window_rect, abort_start = self._resolve_capture_window_context(
                options['recording_area']
            )
            if abort_start:
                return

            options['recording_area'] = recording_area
            self._prepare_recording_widgets_for_active_state()
            self._start_recording_capture_thread(options, window_rect)
            self._hide_windows_for_recording_capture()
            self._show_recording_control_panel()
        except Exception as error:
            logger.error(f'启动录制失败: {error}', exc_info=True)
            thread, self._record_thread = self._record_thread, None
            if thread is not None and thread.isRunning():
                thread.stop()
            self._restore_recording_capture_ui()
            QMessageBox.critical(self, '错误', f'启动录制失败: {error}')
        finally:
            self._recording_state_changing = False

    def _stop_recording(self):
            """停止录制"""
            try:
                logger.info("按钮/快捷键触发:停止录制")

                if self._record_thread and self._record_thread.isRunning():
                    self._record_thread.stop()
                    # 注意：_recording_active 会在 _on_recording_finished 回调中设置为 False
                else:
                    # 录制线程不存在或已停止，直接清理状态
                    self._recording_active = False
                    self._recording_state_changing = False

            except Exception as e:
                # 发生异常时也要清除状态标志
                self._recording_state_changing = False
                self._recording_active = False
                logger.error(f"停止录制失败: {e}", exc_info=True)

    def _open_action_editor(self):
            """打开步骤编辑器"""
            logger.info("打开步骤编辑器")

            # 检查是否正在录制
            if hasattr(self, '_recording_active') and self._recording_active:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "提示", "录制过程中不能编辑步骤，请先停止录制")
                return

            try:
                # 获取当前录制数据（仅接受现行回放载荷）
                recorded_data = self.current_parameters.get('recorded_actions', '')
                actions = []
                recording_area = self.current_parameters['recording_area']
                recording_mode = self.current_parameters['recording_mode']

                if recorded_data:
                    try:
                        payload = self._parse_recorded_actions_payload(recorded_data)
                    except Exception as e:
                        logger.error(f"解析录制数据失败: {e}")
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "错误", f"无法解析录制数据: {e}")
                        return
                    actions = payload['actions']
                    recording_area = payload['recording_area']
                    recording_mode = payload['recording_mode']

                # 导入步骤编辑器对话框
                from ui.dialogs.action_editor_dialog import ActionEditorDialog

                # 创建并显示编辑器（传入录制区域和录制模式信息）
                editor = ActionEditorDialog(actions, recording_area, self, recording_mode)

                # 连接信号
                def on_actions_updated(updated_actions, area=recording_area, mode=recording_mode, card_id=self.current_card_id, workflow_identity=self._runtime_workflow_identity):
                    """步骤更新回调"""
                    try:
                        if self.current_card_id != card_id or self._runtime_workflow_identity != workflow_identity:
                            return
                        import json
                        recording_area, recording_mode = area, mode

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

                self._action_editor = editor
                try:
                    from ui.dialogs.dialog_manager import exec_dialog
                    result = exec_dialog(editor)
                finally:
                    self._action_editor = None

                if result == QDialog.DialogCode.Accepted:
                    logger.info("步骤编辑已保存")
                else:
                    logger.info("步骤编辑已取消")

            except Exception as e:
                logger.error(f"打开步骤编辑器失败: {e}", exc_info=True)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "错误", f"打开步骤编辑器失败: {e}")

    def _on_recording_finished(self, actions):
        thread = self._record_thread
        if thread is None or self.sender() is not thread or thread._panel_card_id != self.current_card_id:
            return
        self._restore_recording_capture_ui()
        if actions:
            payload = {'recording_area': thread.recording_area, 'recording_mode': thread.recording_mode, 'actions': actions}
            self.current_parameters['recorded_actions'] = json.dumps(payload, ensure_ascii=False)
            self.parameters_changed.emit(self.current_card_id, self.current_parameters.copy())
        count = self._get_recorded_action_count()
        for name, text in (('record_control', '开始录制'), ('replay_control', f'测试回放 ({count}个操作)' if count else '测试回放'), ('edit_actions', f'编辑步骤 ({count}个)' if count else '编辑步骤')):
            widget = self.widgets.get(name)
            if widget is not None:
                widget.setText(text)
                widget.setEnabled(True)
                widget.setProperty('class', 'primary' if name != 'edit_actions' else 'secondary')

    def _on_record_thread_finished(self):
        if self.sender() is self._record_thread:
            self._record_thread = None
            self._recording_active = False

    def _restore_recording_capture_ui(self):
        self._recording_active = False
        self._recording_state_changing = False
        panel = getattr(self, "_recording_panel", None)
        self._recording_panel = None
        if panel is not None:
            panel.stop_recording()
            panel.close()
            panel.deleteLater()
        if not getattr(self, "_capture_hidden", False):
            return
        self._capture_hidden = False
        if self._was_panel_visible:
            show_and_raise_widget(self, log_prefix="录制结束")
        if self._main_window is not None and self._was_main_window_visible:
            show_and_raise_widget(self._main_window, log_prefix="录制结束")

    def _on_recording_failed(self, message):
        if self.sender() is not self._record_thread:
            return
        self._restore_recording_capture_ui()
        QMessageBox.warning(self, "录制失败", message)
