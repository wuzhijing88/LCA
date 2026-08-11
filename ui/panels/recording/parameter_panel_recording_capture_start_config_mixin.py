from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureStartConfigMixin:
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
                    f'已激活录制目标窗口 '
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
