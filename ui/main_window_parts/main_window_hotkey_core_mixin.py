import logging

from PySide6.QtCore import QThread, QTimer

logger = logging.getLogger(__name__)


class MainWindowHotkeyCoreMixin:
    def _queue_hotkey_callback(self, callback):
        """将全局钩子回调投递到主窗口所属的 Qt 线程。"""
        if callback is None:
            return

        try:
            if QThread.currentThread() == self.thread():
                callback()
            else:
                QTimer.singleShot(0, self, callback)
        except Exception as exc:
            logger.error("投递热键回调失败: %s", exc)

    def _update_hotkeys(self):
        """更新本地全局快捷键。"""
        try:
            self._update_hotkeys_original_mode()
        except Exception as exc:
            logger.error("更新快捷键失败: %s", exc)
            logger.debug("快捷键更新错误详情", exc_info=True)

    def _get_hotkey_value(self, hotkey_type: str) -> str:
        """获取标准化后的启动、停止或暂停热键值。"""
        if hotkey_type == "start":
            attr = self.start_task_hotkey
            default = "XBUTTON1"
            config_key = "start_task_hotkey"
        elif hotkey_type == "stop":
            attr = self.stop_task_hotkey
            default = "XBUTTON2"
            config_key = "stop_task_hotkey"
        elif hotkey_type == "pause":
            attr = self.pause_workflow_hotkey
            default = "F11"
            config_key = "pause_workflow_hotkey"
        else:
            return "F9"

        if hasattr(attr, "currentData"):
            value = attr.currentData()
            return value.upper() if value else default
        if isinstance(attr, str):
            return attr.upper()
        return self.config.get(config_key, default).upper()

    def _resolve_hotkey_conflicts(self, action_keys: dict, action_names: dict):
        """过滤重复热键，并返回保留项和冲突说明。"""
        preferred_order = ["start", "stop", "pause", "record", "replay"]
        resolved = {}
        seen = {}
        conflicts = []

        for action in preferred_order:
            key = action_keys.get(action)
            if not key:
                continue

            normalized = str(key).upper()
            if normalized in seen:
                conflicts.append(
                    f"{normalized}: "
                    f"{action_names.get(seen[normalized], seen[normalized])} / "
                    f"{action_names.get(action, action)}"
                )
                continue

            seen[normalized] = action
            resolved[action] = key

        for action, key in action_keys.items():
            if action in preferred_order or not key:
                continue

            normalized = str(key).upper()
            if normalized in seen:
                conflicts.append(
                    f"{normalized}: "
                    f"{action_names.get(seen[normalized], seen[normalized])} / "
                    f"{action_names.get(action, action)}"
                )
                continue

            seen[normalized] = action
            resolved[action] = key

        return resolved, conflicts
