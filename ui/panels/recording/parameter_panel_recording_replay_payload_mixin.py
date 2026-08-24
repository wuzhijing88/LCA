from ..parameter_panel_support import *


class ParameterPanelRecordingReplayPayloadMixin:
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
            return self._parse_recorded_actions_payload(recorded_data)
        except ValueError as e:
            logger.error(f"录制数据格式错误: {e}")
            self._show_replay_message(QMessageBox.Icon.Critical, '错误', str(e))
            return None

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
