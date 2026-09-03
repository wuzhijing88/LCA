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
            try:
                from utils.instance_runtime import should_handle_hotkey

                parent = getattr(self, "parent_window", None)
                if not should_handle_hotkey(getattr(parent, "bound_windows", None) if parent else None):
                    if parent is not None and hasattr(parent, "_notify_hotkey_routed_away"):
                        parent._notify_hotkey_routed_away()
                    return
            except Exception:
                pass
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
            try:
                from utils.instance_runtime import should_handle_hotkey

                parent = getattr(self, "parent_window", None)
                if not should_handle_hotkey(getattr(parent, "bound_windows", None) if parent else None):
                    if parent is not None and hasattr(parent, "_notify_hotkey_routed_away"):
                        parent._notify_hotkey_routed_away()
                    return
            except Exception:
                pass
            if not self._is_recording_panel_active:
                return
            parent = getattr(self, "parent_window", None)
            if parent is not None and hasattr(parent, "is_hotkey_listen_enabled") and not parent.is_hotkey_listen_enabled():
                return

            # 触发回放操作
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
        recording_area = self._REPLAY_AREA_DEFAULT
        recording_mode = self._REPLAY_MODE_DEFAULT

        if isinstance(data, dict) and 'actions' in data:
            recording_area = data.get('recording_area', self._REPLAY_AREA_DEFAULT)
            recording_mode = data.get('recording_mode', self._REPLAY_MODE_DEFAULT)
            actions = data['actions']
        elif isinstance(data, list):
            actions = data
        else:
            raise ValueError('录制数据格式错误')

        if not isinstance(actions, list):
            raise ValueError('录制数据格式错误')

        return {
            'actions': actions,
            'recording_area': recording_area,
            'recording_mode': recording_mode,
            'raw': recorded_data,
        }

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
            return
        thread.stop()
        logger.info('已发送回放停止信号')
        self._set_replay_button_stopping_state()

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
        try:
            self._replay_active = False
            self._restore_replay_button_default_state()
            logger.info('回放完成，状态标志已清除')
        except Exception as e:
            logger.error(f"处理回放完成失败: {e}", exc_info=True)
            self._replay_active = False

    @Slot()
    def _on_replay_thread_finished(self):
        thread = getattr(self, '_replay_thread', None)
        if not thread:
            return
        self._replay_thread = None
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

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
        speed = float(self.current_parameters.get('speed', 1.0))
        loop_count_raw = self.current_parameters.get('loop_count', 1)
        loop_count = int(loop_count_raw) if loop_count_raw is not None else 1
        if loop_count <= 0:
            loop_count = 1
        logger.info(
            f"[测试回放] 回放参数: speed={speed}, loop_count={loop_count}, raw={loop_count_raw}"
        )
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
        QTimer.singleShot(3000, lambda: setattr(self, '_recording_state_changing', False))

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
        window_rect = None
        if recording_area != '窗口录制':
            return recording_area, window_rect, False

        hwnd, abort_start = self._load_capture_target_hwnd_from_config()
        if abort_start:
            return recording_area, None, True

        if not hwnd:
            logger.warning('窗口录制模式但config.json中没有窗口句柄，自动切换到全屏录制模式')
            return '全屏录制', None, False

        try:
            import win32con
            import win32gui

            if not win32gui.IsWindow(hwnd):
                logger.warning(f'窗口句柄无效: {hwnd}，自动切换到全屏录制模式')
                return '全屏录制', None, False

            try:
                activation_hwnd = self._activate_bound_window(hwnd, log_prefix='录制')
                window_title = win32gui.GetWindowText(activation_hwnd)
                logger.info(
                    '已激活录制目标窗口 '
                    f'(句柄={activation_hwnd}, 标题={window_title})'
                )
            except Exception as error:
                logger.warning(f'激活窗口失败: {error}')
                try:
                    from pynput.keyboard import Controller, Key

                    keyboard_controller = Controller()
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                    keyboard_controller.press(Key.alt)
                    win32gui.SetForegroundWindow(hwnd)
                    keyboard_controller.release(Key.alt)
                    time.sleep(0.2)
                    logger.info('使用备用方法激活窗口')
                except Exception as backup_error:
                    logger.error(f'备用激活方法也失败: {backup_error}')

            window_rect = self._resolve_bound_window_client_rect(hwnd, log_prefix='录制')
            logger.info(f'窗口录制模式: 句柄={hwnd}, 范围={window_rect}')
            return recording_area, window_rect, False
        except Exception as error:
            logger.warning(f'获取窗口信息失败: {error}，自动切换到全屏录制模式')
            return '全屏录制', None, False

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
            self._recording_panel = RecordingControlPanel()
            self._recording_panel.stop_requested.connect(self._stop_recording)
            if hasattr(self._record_thread, 'step_count_updated'):
                self._record_thread.step_count_updated.connect(self._recording_panel.update_step_count)
            logger.info('浮窗已创建，准备启动...')
            self._recording_panel.start_recording()
            logger.info('录制控制浮窗已启动')
        except Exception as error:
            logger.error(f'创建录制控制浮窗失败: {error}', exc_info=True)

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
        self._record_thread.recording_finished.connect(self._on_recording_finished)
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
                # 获取当前录制数据（统一走回放载荷解析器，兼容新旧格式）
                recorded_data = self.current_parameters.get('recorded_actions', '')
                actions = []
                recording_area = self._REPLAY_AREA_DEFAULT
                recording_mode = self._REPLAY_MODE_DEFAULT

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
                    show_and_raise_widget(self, log_prefix='参数面板恢复')
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
