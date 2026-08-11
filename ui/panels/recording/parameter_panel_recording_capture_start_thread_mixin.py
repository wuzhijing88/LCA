from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureStartThreadMixin:
    def _resolve_record_hotkey(self):
        record_hotkey = None
        try:
            if hasattr(self, 'parent_window') and self.parent_window and hasattr(self.parent_window, 'config'):
                record_hotkey = self.parent_window.config.get('record_hotkey')
            if not record_hotkey and hasattr(self, 'parent_window') and self.parent_window:
                record_hotkey = getattr(self.parent_window, 'record_hotkey', None)
        except Exception:
            record_hotkey = None
        return record_hotkey

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
            f'录制已启动: '
            f'区域={options["recording_area"]}, '
            f'模式={options["recording_mode"]}, '
            f'精度={options["recording_precision"]}'
        )
        logger.info(
            f'录制线程状态: '
            f'isRunning={self._record_thread.isRunning()}, '
            f'use_raw_input={self._record_thread.use_raw_input}'
        )
