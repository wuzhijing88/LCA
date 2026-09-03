import logging
from PySide6.QtCore import QThread, QTimer

from app_core.config_sections import DEFAULT_HOTKEYS
from app_core.hotkey_spec import (
    display_hotkey,
    first_conflict,
    is_hotkey_capture_active,
    is_mouse_hotkey,
    mouse_hook_button,
    normalize_hotkey,
    spec_from_keyboard_event,
    to_keyboard_lib,
)

logger = logging.getLogger(__name__)

_HOTKEY_FIELDS = {
    "start": "start_task_hotkey",
    "stop": "stop_task_hotkey",
    "pause": "pause_workflow_hotkey",
    "record": "record_hotkey",
    "replay": "replay_hotkey",
    "close_listen": "close_listen_hotkey",
}

class MainWindowHotkeyMixin:

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
        """获取标准化后的热键值。"""
        config_key = _HOTKEY_FIELDS.get(hotkey_type)
        if not config_key:
            return DEFAULT_HOTKEYS["start_task_hotkey"]

        default = DEFAULT_HOTKEYS[config_key]
        attr = getattr(self, config_key, None)
        raw = None
        if hasattr(attr, "key_value"):
            raw = attr.key_value()
        elif hasattr(attr, "currentData"):
            raw = attr.currentData()
        elif isinstance(attr, str):
            raw = attr
        else:
            raw = self.config.get(config_key, default)
        return normalize_hotkey(raw) or default

    def is_hotkey_listen_enabled(self) -> bool:
        return bool(getattr(self, "_hotkey_listen_enabled", True))

    def _resolve_hotkey_conflicts(self, action_keys: dict, action_names: dict):
        """过滤重复热键，并返回保留项和冲突说明。"""
        return first_conflict(
            action_keys,
            action_names,
            ["close_listen", "start", "stop", "pause", "record", "replay"],
        )

    def _update_hotkeys_original_mode(self):

        """原有模式的热键更新 - 使用keyboard/mouse库（优化版）

        优化点：

        1. 使用 keyboard.hook 低级钩子替代 add_hotkey，更可靠

        2. 避免 suppress=True 可能导致的问题

        3. 添加热键状态监控和自动恢复机制

        4. 使用独立的热键处理线程

        """

        try:

            import keyboard

            import time

            # 清除之前注册的热键（只清除我们自己注册的）

            try:

                # 保存当前的钩子引用，用于后续清理

                if hasattr(self, '_keyboard_hooks'):

                    for hook in self._keyboard_hooks:

                        try:

                            keyboard.unhook(hook)

                        except Exception:

                            pass

                self._keyboard_hooks = []

                # 清除之前的热键

                if hasattr(self, '_registered_hotkeys'):

                    for hotkey in self._registered_hotkeys:

                        try:

                            keyboard.remove_hotkey(hotkey)

                        except Exception:

                            pass

                self._registered_hotkeys = []

                logger.info("已清除之前注册的键盘快捷键")

                time.sleep(0.02)

            except Exception as e:

                logger.warning(f"清除键盘快捷键失败: {e}，继续设置新快捷键")

            # 获取快捷键设置

            start_key = self._get_hotkey_value('start')

            stop_key = self._get_hotkey_value('stop')

            pause_key = self._get_hotkey_value('pause')

            record_key = self._get_hotkey_value('record')

            replay_key = self._get_hotkey_value('replay')

            close_listen_key = self._get_hotkey_value('close_listen')

            action_names = {

                'start': '启动任务',

                'stop': '停止任务',

                'pause': '暂停/恢复',

                'record': '录制',

                'replay': '回放',

                'close_listen': '关闭监听',

            }

            action_keys = {

                'start': start_key,

                'stop': stop_key,

                'pause': pause_key,

                'record': record_key,

                'replay': replay_key,

                'close_listen': close_listen_key,

            }

            action_keys, conflict_messages = self._resolve_hotkey_conflicts(action_keys, action_names)

            start_key = action_keys.get('start')

            stop_key = action_keys.get('stop')

            pause_key = action_keys.get('pause')

            record_key = action_keys.get('record')

            replay_key = action_keys.get('replay')

            close_listen_key = action_keys.get('close_listen')

            failed_hotkeys = []

            if conflict_messages:

                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(

                    self,

                    "快捷键冲突",

                    "以下快捷键被多个功能同时使用，已保留优先项，其他冲突项已忽略：\n\n"

                    f"{chr(10).join(conflict_messages)}\n\n请修改为不同快捷键。"

                )

            # 鼠标侧键处理

            mouse_keys = {action: key for action, key in action_keys.items() if is_mouse_hotkey(key)}

            self._setup_mouse_hotkeys(mouse_keys, failed_hotkeys)

            # 键盘热键处理 - 使用更可靠的方法

            keyboard_keys = {

                action: key for action, key in action_keys.items() if key and not is_mouse_hotkey(key)

            }

            # 使用低级钩子方式注册热键（更可靠）

            self._setup_keyboard_hotkeys_robust(keyboard_keys, failed_hotkeys)

            logger.info(

                f"✓ 快捷键系统已更新 - 启动: {display_hotkey(start_key)}, 停止: {display_hotkey(stop_key)}, "

                f"暂停: {display_hotkey(pause_key)}, 录制: {display_hotkey(record_key)}, "

                f"回放: {display_hotkey(replay_key)}, 关闭监听: {display_hotkey(close_listen_key)}"

            )

            # 如果有快捷键注册失败，提示用户

            if failed_hotkeys:

                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(

                    self,

                    "快捷键注册失败",

                    f"以下快捷键可能被其他程序占用，注册失败：\n\n{', '.join(failed_hotkeys)}\n\n请尝试更换其他快捷键。"

                )

        except ImportError:

            logger.warning("keyboard库不可用，无法设置全局快捷键")

        except Exception as e:

            logger.error(f"更新快捷键失败: {e}")

            import traceback

            logger.debug(f"快捷键更新错误详情: {traceback.format_exc()}")

    def _setup_keyboard_hotkeys_robust(self, keyboard_keys: dict, failed_hotkeys: list):

        """使用更可靠的方式注册键盘热键

        使用 keyboard.hook 低级钩子来监听按键，这种方式比 add_hotkey 更可靠，

        不容易被其他程序干扰。

        """

        import keyboard

        callback_map = {

            'start': self._on_start_task_hotkey,

            'stop': self._on_stop_task_hotkey,

            'pause': self._on_pause_workflow_hotkey,

            'record': self._on_record_hotkey,

            'replay': self._on_replay_hotkey,

            'close_listen': self._on_close_listen_hotkey,

        }

        action_names = {

            'start': '启动任务',

            'stop': '停止任务',

            'pause': '暂停/恢复',

            'record': '录制',

            'replay': '回放',

            'close_listen': '关闭监听',

        }

        key_to_action = {}

        for action, key in keyboard_keys.items():

            spec = normalize_hotkey(key)

            if not spec:

                continue

            key_to_action[spec] = action

        self._hotkey_pressed_state = {}

        def on_key_event(event):

            """低级键盘事件处理"""

            try:

                if is_hotkey_capture_active():

                    return

                if event.event_type == 'up':

                    base = normalize_hotkey(getattr(event, 'name', ''))

                    if base:

                        for spec in list(self._hotkey_pressed_state):

                            if spec == base or spec.endswith('+' + base):

                                self._hotkey_pressed_state[spec] = False

                    return

                spec = spec_from_keyboard_event(event)

                if not spec or spec not in key_to_action:

                    return

                action = key_to_action[spec]

                if action != 'close_listen' and not self.is_hotkey_listen_enabled():

                    return

                if self._hotkey_pressed_state.get(spec, False):

                    return

                self._hotkey_pressed_state[spec] = True

                callback = callback_map.get(action)

                if callback:

                    self._queue_hotkey_callback(callback)

            except Exception as e:

                logger.debug(f"热键事件处理异常: {e}")

        try:

            hook = keyboard.hook(on_key_event, suppress=False)

            self._keyboard_hooks.append(hook)

            for action, key in keyboard_keys.items():

                if key:

                    logger.info(f"{action_names.get(action, action)}快捷键已设置: {display_hotkey(key)} (低级钩子模式)")

        except Exception as e:

            logger.warning(f"低级钩子注册失败: {e}，尝试传统方式")

            self._setup_keyboard_hotkeys_fallback(keyboard_keys, failed_hotkeys)

    def _setup_mouse_hotkeys(self, mouse_keys, failed_hotkeys):

        """设置鼠标侧键热键"""

        try:

            import mouse

            # 清除之前的鼠标钩子

            if hasattr(self, '_mouse_hooks'):

                for hook in self._mouse_hooks:

                    try:

                        mouse.unhook(hook)

                    except Exception:

                        pass

            self._mouse_hooks = []

            callback_map = {

                'start': self._on_start_task_hotkey,

                'stop': self._on_stop_task_hotkey,

                'pause': self._on_pause_workflow_hotkey,

                'record': self._on_record_hotkey,

                'replay': self._on_replay_hotkey,

                'close_listen': self._on_close_listen_hotkey,

            }

            action_names = {
                'start': '启动任务',
                'stop': '停止任务',
                'pause': '暂停/恢复',
                'record': '录制',
                'replay': '回放',
                'close_listen': '关闭监听',
            }

            def make_mouse_callback(action, callback):

                def _handler(*args, **kwargs):

                    if is_hotkey_capture_active():

                        return

                    if action != 'close_listen' and not self.is_hotkey_listen_enabled():

                        return

                    self._queue_hotkey_callback(callback)

                return _handler

            for action, key in mouse_keys.items():

                if not key:

                    continue

                try:

                    mouse_button = mouse_hook_button(key)

                    callback = callback_map.get(action)

                    if callback and mouse_button:

                        hook = mouse.on_button(

                            make_mouse_callback(action, callback),

                            buttons=(mouse_button,),

                            types=('down',)

                        )

                        self._mouse_hooks.append(hook)

                        logger.info(f"{action_names.get(action, action)}快捷键已设置: {display_hotkey(key)} (鼠标侧键)")

                except Exception as e:

                    failed_hotkeys.append(f"{action_names.get(action, action)}({display_hotkey(key)})")

                    logger.error(f"设置{action_names.get(action, action)}鼠标侧键失败: {e}")

        except ImportError:

            logger.warning("mouse库不可用，无法设置鼠标侧键热键")

        except Exception as e:

            logger.error(f"设置鼠标侧键热键失败: {e}")

    def _disable_main_window_hotkeys(self):

        """禁用主窗口的快捷键（中控软件打开时）"""

        try:

            logger.info("禁用主窗口快捷键")

            import keyboard

            if hasattr(self, '_keyboard_hooks'):

                for hook in self._keyboard_hooks:

                    try:

                        keyboard.unhook(hook)

                    except Exception:

                        pass

                self._keyboard_hooks = []

            if hasattr(self, '_registered_hotkeys'):

                for hotkey in self._registered_hotkeys:

                    try:

                        keyboard.remove_hotkey(hotkey)

                    except Exception:

                        pass

                self._registered_hotkeys = []

            logger.info("主窗口快捷键已禁用")

        except Exception as e:

            logger.error(f"禁用主窗口快捷键失败: {e}")

    def _setup_keyboard_hotkeys_fallback(self, keyboard_keys: dict, failed_hotkeys: list):

        """回退方式：使用传统的 add_hotkey"""

        import keyboard

        callback_map = {

            'start': self._on_start_task_hotkey,

            'stop': self._on_stop_task_hotkey,

            'pause': self._on_pause_workflow_hotkey,

            'record': self._on_record_hotkey,

            'replay': self._on_replay_hotkey,

            'close_listen': self._on_close_listen_hotkey,

        }

        action_names = {
            'start': '启动任务',
            'stop': '停止任务',
            'pause': '暂停/恢复',
            'record': '录制',
            'replay': '回放',
            'close_listen': '关闭监听',
        }

        for action, key in keyboard_keys.items():

            lib_key = to_keyboard_lib(key)

            if not lib_key:

                continue

            try:

                callback = callback_map.get(action)

                if callback:

                    hotkey = keyboard.add_hotkey(

                        lib_key,

                        lambda cb=callback, act=action: (
                            None
                            if is_hotkey_capture_active()
                            or (act != "close_listen" and not self.is_hotkey_listen_enabled())
                            else self._queue_hotkey_callback(cb)
                        ),

                        trigger_on_release=False,

                        suppress=False

                    )

                    self._registered_hotkeys.append(hotkey)

                    logger.info(f"{action_names.get(action, action)}快捷键已设置: {display_hotkey(key)} (传统模式)")

            except Exception as e:

                failed_hotkeys.append(f"{action_names.get(action, action)}({display_hotkey(key)})")

                logger.error(f"设置{action_names.get(action, action)}快捷键失败: {e}")

    def _instance_should_handle_hotkey(self, notify: bool = True):
        try:
            from utils.instance_runtime import should_handle_hotkey

            owned = should_handle_hotkey(getattr(self, "bound_windows", None))
        except Exception:
            return True
        if not owned and notify:
            self._notify_hotkey_routed_away()
        return owned

    def _notify_hotkey_routed_away(self):
        import time

        now = time.monotonic()
        last = float(getattr(self, "_last_hotkey_route_hint_ts", 0.0) or 0.0)
        if now - last < 4.0:
            return
        self._last_hotkey_route_hint_ts = now
        message = "快捷键已由另一份 LCA 处理（当前焦点不在本实例）"
        logger.info(message)
        if hasattr(self, "_update_step_details"):
            try:
                self._update_step_details(message)
            except Exception:
                pass
        if self.isVisible() and not self.isMinimized():
            return
        tray = getattr(self, "system_tray_manager", None)
        if tray is not None and hasattr(tray, "show_message"):
            try:
                tray.show_message("LCA", message)
            except Exception:
                pass

    def _on_close_listen_hotkey(self):
        """关闭/重新开启全局快捷键监听。该键在关闭监听后仍有效。"""
        try:
            if QThread.currentThread() != self.thread():
                QTimer.singleShot(0, self, self._on_close_listen_hotkey)
                return
            import time

            current_time = time.time()
            last = float(getattr(self, "_last_close_listen_hotkey_time", 0.0) or 0.0)
            if current_time - last < 0.4:
                return
            self._last_close_listen_hotkey_time = current_time
            self._hotkey_listen_enabled = not self.is_hotkey_listen_enabled()
            key_text = display_hotkey(self._get_hotkey_value("close_listen"))
            if self._hotkey_listen_enabled:
                message = f"快捷键监听已开启（{key_text} 可关闭）"
            else:
                message = f"快捷键监听已关闭（{key_text} 重新开启，该快捷键除外）"
            logger.info(message)
            if hasattr(self, "_update_step_details"):
                try:
                    self._update_step_details(message)
                except Exception:
                    pass
            tray = getattr(self, "system_tray_manager", None)
            if tray is not None and hasattr(tray, "show_message"):
                try:
                    tray.show_message("LCA", message)
                except Exception:
                    pass
        except Exception as e:
            logger.error("关闭监听快捷键处理失败: %s", e)

    def _on_record_hotkey(self):
        """录制快捷键回调"""
        try:
            if QThread.currentThread() != self.thread():
                QTimer.singleShot(0, self, self._on_record_hotkey)
                return
            if not self._instance_should_handle_hotkey():
                return
            # 防抖：检查是否在短时间内重复触发
            import time
            current_time = time.time()
            if hasattr(self, '_last_record_hotkey_time'):
                if current_time - self._last_record_hotkey_time < 0.5:  # 500ms 防抖
                    logger.debug(f"录制快捷键防抖：忽略重复触发（距上次 {current_time - self._last_record_hotkey_time:.3f}s）")
                    return
            self._last_record_hotkey_time = current_time
            record_hotkey = self._get_hotkey_value('record')
            logger.info(f"✓ 检测到录制快捷键: {record_hotkey}")
            # 查找参数面板中的录制功能
            try:
                # 获取当前活动的参数面板
                param_panel = getattr(self, 'param_panel', None)
                if param_panel is None:
                    param_panel = getattr(self, 'parameter_panel', None)
                if param_panel and hasattr(param_panel, '_is_recording_panel_active'):
                    # 组合键可编辑序列录制时，屏蔽主窗口全局录制快捷键，避免干扰录制按键内容
                    if bool(getattr(param_panel, '_combo_seq_block_global_record_hotkey', False)):
                        logger.info("组合键录制进行中，忽略全局录制快捷键触发")
                        return
                    if param_panel._is_recording_panel_active:
                        # 触发参数面板的录制功能
                        if hasattr(param_panel, '_on_record_hotkey'):
                            param_panel._on_record_hotkey()
                            logger.info("✓ 已触发参数面板的录制功能")
                        else:
                            logger.warning("参数面板未实现录制功能")
                    else:
                        logger.info("提示：请先打开录制回放参数面板才能使用录制功能")
                else:
                    logger.info("提示：录制功能需要在参数面板中使用")
            except Exception as e:
                logger.error(f"触发录制功能失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"录制快捷键处理失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _on_replay_hotkey(self):
        """回放快捷键回调"""
        try:
            if QThread.currentThread() != self.thread():
                QTimer.singleShot(0, self, self._on_replay_hotkey)
                return
            if not self._instance_should_handle_hotkey():
                return
            # 防抖：检查是否在短时间内重复触发
            import time
            current_time = time.time()
            if hasattr(self, '_last_replay_hotkey_time'):
                if current_time - self._last_replay_hotkey_time < 0.5:  # 500ms 防抖
                    logger.debug(f"回放快捷键防抖：忽略重复触发（距上次 {current_time - self._last_replay_hotkey_time:.3f}s）")
                    return
            self._last_replay_hotkey_time = current_time
            replay_hotkey = self._get_hotkey_value('replay')
            logger.info(f"✓ 检测到回放快捷键: {replay_hotkey}")
            # 查找参数面板中的回放功能
            try:
                # 获取当前活动的参数面板
                param_panel = getattr(self, 'param_panel', None)
                if param_panel and hasattr(param_panel, '_is_recording_panel_active'):
                    if param_panel._is_recording_panel_active:
                        # 触发参数面板的回放功能
                        if hasattr(param_panel, '_on_replay_hotkey'):
                            param_panel._on_replay_hotkey()
                            logger.info("✓ 已触发参数面板的回放功能")
                        else:
                            logger.warning("参数面板未实现回放功能")
                    else:
                        logger.info("提示：请先打开录制回放参数面板才能使用回放功能")
                else:
                    logger.info("提示：回放功能需要在参数面板中使用")
            except Exception as e:
                logger.error(f"触发回放功能失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"回放快捷键处理失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _on_start_task_hotkey(self):
        """启动任务快捷键回调 - 通过信号确保线程安全"""
        try:
            if not self._instance_should_handle_hotkey():
                return
            # 防抖：检查是否在短时间内重复触发
            import time
            current_time = time.time()
            if hasattr(self, '_last_start_hotkey_time'):
                if current_time - self._last_start_hotkey_time < 0.5:  # 500ms 防抖
                    logger.debug(f"快捷键防抖：忽略重复触发（距上次 {current_time - self._last_start_hotkey_time:.3f}s）")
                    return
            self._last_start_hotkey_time = current_time
            # 获取当前热键值
            hotkey_value = self._get_hotkey_value('start')
            logger.info(f"检测到启动任务快捷键: {hotkey_value}")
            # 直接启动任务
            self.hotkey_start_signal.emit()
            logger.info("快捷键回调：已发射 hotkey_start_signal 信号")
        except Exception as e:
            logger.error(f"启动任务快捷键处理失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _on_stop_task_hotkey(self):
        """停止任务快捷键回调 - 通过信号确保线程安全"""
        try:
            if not self._instance_should_handle_hotkey():
                return
            # 防抖：检查是否在短时间内重复触发
            import time
            current_time = time.time()
            if hasattr(self, '_last_stop_hotkey_time'):
                if current_time - self._last_stop_hotkey_time < 0.5:  # 500ms 防抖
                    logger.debug(f"快捷键防抖：忽略重复触发（距上次 {current_time - self._last_stop_hotkey_time:.3f}s）")
                    return
            self._last_stop_hotkey_time = current_time
            # 获取当前热键值
            hotkey_value = self._get_hotkey_value('stop')
            logger.info(f"检测到停止任务快捷键: {hotkey_value}")
            logger.info("=" * 50)
            logger.info("强制停止：开始执行停止操作")
            # 直接调用停止方法
            logger.info("✓ 强制停止：调用 safe_stop_tasks()")
            self.safe_stop_tasks()
            logger.info("=" * 50)
        except Exception as e:
            logger.error(f"停止任务快捷键处理失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _on_pause_workflow_hotkey(self):
        """暂停/恢复工作流快捷键回调"""
        try:
            if not self._instance_should_handle_hotkey():
                return
            # 防抖：检查是否在短时间内重复触发
            import time
            current_time = time.time()
            if hasattr(self, '_last_pause_hotkey_time'):
                if current_time - self._last_pause_hotkey_time < 0.5:  # 500ms 防抖
                    logger.debug(f"暂停快捷键防抖：忽略重复触发（距上次 {current_time - self._last_pause_hotkey_time:.3f}s）")
                    return
            self._last_pause_hotkey_time = current_time
            hotkey_value = self._get_hotkey_value('pause')
            logger.info(f"检测到暂停工作流快捷键: {hotkey_value}")
            # 切换暂停/恢复状态
            self.toggle_pause_workflow()
        except Exception as e:
            logger.error(f"暂停工作流快捷键处理失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _safe_start_from_hotkey(self):
        """在主线程中安全启动任务（供快捷键调用）"""
        try:
            logger.info("快捷键触发：在主线程中启动任务")
            self.safe_start_tasks()
        except Exception as e:
            logger.error(f"快捷键启动任务失败: {e}")

    def _safe_stop_from_hotkey(self):
        """在主线程中安全停止任务（供快捷键调用）"""
        try:
            logger.info("快捷键触发：在主线程中停止任务")
            self.safe_stop_tasks()
        except Exception as e:
            logger.error(f"快捷键停止任务失败: {e}")
