import logging

logger = logging.getLogger(__name__)


class MainWindowHotkeySetupMixin:

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

            start_key = self._get_hotkey_value('start').lower()

            stop_key = self._get_hotkey_value('stop').lower()

            pause_key = self._get_hotkey_value('pause').lower()

            record_key = self.config.get('record_hotkey', 'F11').lower()

            replay_key = self.config.get('replay_hotkey', 'F12').lower()

            action_names = {

                'start': '启动任务',

                'stop': '停止任务',

                'pause': '暂停/恢复',

                'record': '录制',

                'replay': '回放',

            }

            action_keys = {

                'start': start_key,

                'stop': stop_key,

                'pause': pause_key,

                'record': record_key,

                'replay': replay_key,

            }

            action_keys, conflict_messages = self._resolve_hotkey_conflicts(action_keys, action_names)

            start_key = action_keys.get('start')

            stop_key = action_keys.get('stop')

            pause_key = action_keys.get('pause')

            record_key = action_keys.get('record')

            replay_key = action_keys.get('replay')

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

            needs_mouse = any(k in ['xbutton1', 'xbutton2'] for k in [start_key, stop_key, pause_key, record_key, replay_key])

            if needs_mouse:

                self._setup_mouse_hotkeys(start_key, stop_key, pause_key, record_key, replay_key, failed_hotkeys)

            # 键盘热键处理 - 使用更可靠的方法

            keyboard_keys = {

                'start': start_key if start_key not in ['xbutton1', 'xbutton2'] else None,

                'stop': stop_key if stop_key not in ['xbutton1', 'xbutton2'] else None,

                'pause': pause_key if pause_key not in ['xbutton1', 'xbutton2'] else None,

                'record': record_key if record_key not in ['xbutton1', 'xbutton2'] else None,

                'replay': replay_key if replay_key not in ['xbutton1', 'xbutton2'] else None,

            }

            # 使用低级钩子方式注册热键（更可靠）

            self._setup_keyboard_hotkeys_robust(keyboard_keys, failed_hotkeys)

            logger.info(

                f"✓ 快捷键系统已更新 - 启动: {(start_key or '-').upper()}, 停止: {(stop_key or '-').upper()}, "

                f"暂停: {(pause_key or '-').upper()}, 录制: {(record_key or '-').upper()}, 回放: {(replay_key or '-').upper()}"

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

        # 按键映射 - 统一转换为 keyboard 库使用的格式

        key_name_map = {

            'f1': 'f1', 'f2': 'f2', 'f3': 'f3', 'f4': 'f4',

            'f5': 'f5', 'f6': 'f6', 'f7': 'f7', 'f8': 'f8',

            'f9': 'f9', 'f10': 'f10', 'f11': 'f11', 'f12': 'f12',

            'home': 'home', 'end': 'end',

            'insert': 'insert', 'delete': 'delete',

            'pageup': 'page up', 'pagedown': 'page down',

            'printscreen': 'print screen', 'scrolllock': 'scroll lock', 'pause': 'pause',

            'numlock': 'num lock',

            'num0': 'num 0', 'num1': 'num 1', 'num2': 'num 2', 'num3': 'num 3',

            'num4': 'num 4', 'num5': 'num 5', 'num6': 'num 6', 'num7': 'num 7',

            'num8': 'num 8', 'num9': 'num 9',

            'nummultiply': 'num *', 'numadd': 'num +', 'numsubtract': 'num -',

            'numdivide': 'num /', 'numdecimal': 'num .',

        }

        # 回调映射

        callback_map = {

            'start': self._on_start_task_hotkey,

            'stop': self._on_stop_task_hotkey,

            'pause': self._on_pause_workflow_hotkey,

            'record': self._on_record_hotkey,

            'replay': self._on_replay_hotkey,

        }

        action_names = {

            'start': '启动任务',

            'stop': '停止任务',

            'pause': '暂停/恢复',

            'record': '录制',

            'replay': '回放',

        }

        def _normalize_keypad_event_name(name: str) -> str:

            """Normalize keypad event names to match our key map."""

            if not name:

                return name

            keypad_nav_map = {

                'end': 'num 1',

                'down': 'num 2',

                'page down': 'num 3',

                'pagedown': 'num 3',

                'left': 'num 4',

                'clear': 'num 5',

                'right': 'num 6',

                'home': 'num 7',

                'up': 'num 8',

                'page up': 'num 9',

                'pageup': 'num 9',

                'insert': 'num 0',

                'delete': 'num .',

            }

            if name in keypad_nav_map:

                return keypad_nav_map[name]

            if len(name) == 1 and name.isdigit():

                return f"num {name}"

            if name in ('+', '-', '*', '/'):

                return f"num {name}"

            if name in ('decimal', '.', 'separator'):

                return "num ."

            return name

        # 创建按键到动作的映射

        key_to_action = {}

        for action, key in keyboard_keys.items():

            if not key:

                continue

            if key in key_name_map:

                normalized_key = key_name_map[key]

                key_to_action[normalized_key] = action

            else:

                failed_hotkeys.append(f"{action_names.get(action, action)}({key.upper()})")

                logger.warning(f"不支持的快捷键配置: {action} -> {key}")

        # 保存按键状态，用于防止重复触发

        self._hotkey_pressed_state = {}

        def on_key_event(event):

            """低级键盘事件处理"""

            try:

                key_name = event.name.lower() if event.name else ''

                if getattr(event, 'is_keypad', False):

                    key_name = _normalize_keypad_event_name(key_name)

                if key_name in key_to_action:

                    action = key_to_action[key_name]

                    if event.event_type == 'down':

                        # 检查是否已经按下（防止重复触发）

                        if not self._hotkey_pressed_state.get(key_name, False):

                            self._hotkey_pressed_state[key_name] = True

                            callback = callback_map.get(action)

                            if callback:

                                self._queue_hotkey_callback(callback)

                    elif event.event_type == 'up':

                        self._hotkey_pressed_state[key_name] = False

            except Exception as e:

                logger.debug(f"热键事件处理异常: {e}")

        # 注册低级钩子

        try:

            hook = keyboard.hook(on_key_event, suppress=False)

            self._keyboard_hooks.append(hook)

            # 记录已注册的热键

            for action, key in keyboard_keys.items():

                if key and key in key_name_map:

                    logger.info(f"{action_names.get(action, action)}快捷键已设置: {key.upper()} (低级钩子模式)")

        except Exception as e:

            # 回退到传统方式

            logger.warning(f"低级钩子注册失败: {e}，尝试传统方式")

            self._setup_keyboard_hotkeys_fallback(keyboard_keys, failed_hotkeys)

    def _setup_mouse_hotkeys(self, start_key, stop_key, pause_key, record_key, replay_key, failed_hotkeys):

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

            mouse_keys = {

                'start': start_key if start_key in ['xbutton1', 'xbutton2'] else None,

                'stop': stop_key if stop_key in ['xbutton1', 'xbutton2'] else None,

                'pause': pause_key if pause_key in ['xbutton1', 'xbutton2'] else None,

                'record': record_key if record_key in ['xbutton1', 'xbutton2'] else None,

                'replay': replay_key if replay_key in ['xbutton1', 'xbutton2'] else None,

            }

            callback_map = {

                'start': self._on_start_task_hotkey,

                'stop': self._on_stop_task_hotkey,

                'pause': self._on_pause_workflow_hotkey,

                'record': self._on_record_hotkey,

                'replay': self._on_replay_hotkey,

            }

            action_names = {'start': '启动任务', 'stop': '停止任务', 'pause': '暂停/恢复', 'record': '录制', 'replay': '回放'}

            def make_mouse_callback(callback):

                def _handler(*args, **kwargs):

                    self._queue_hotkey_callback(callback)

                return _handler

            for action, key in mouse_keys.items():

                if not key:

                    continue

                try:

                    mouse_button = 'x' if key == 'xbutton1' else 'x2'

                    callback = callback_map.get(action)

                    if callback:

                        hook = mouse.on_button(

                            make_mouse_callback(callback),

                            buttons=(mouse_button,),

                            types=('down',)

                        )

                        self._mouse_hooks.append(hook)

                        logger.info(f"{action_names.get(action, action)}快捷键已设置: {key.upper()} (鼠标侧键)")

                except Exception as e:

                    failed_hotkeys.append(f"{action_names.get(action, action)}({key.upper()})")

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

        }

        action_names = {'start': '启动任务', 'stop': '停止任务', 'pause': '暂停/恢复', 'record': '录制', 'replay': '回放'}

        for action, key in keyboard_keys.items():

            if not key:

                continue

            try:

                callback = callback_map.get(action)

                if callback:

                    # 不使用 suppress，避免和其他程序冲突

                    hotkey = keyboard.add_hotkey(

                        key,

                        lambda cb=callback: self._queue_hotkey_callback(cb),

                        trigger_on_release=False,

                        suppress=False

                    )

                    self._registered_hotkeys.append(hotkey)

                    logger.info(f"{action_names.get(action, action)}快捷键已设置: {key.upper()} (传统模式)")

            except Exception as e:

                failed_hotkeys.append(f"{action_names.get(action, action)}({key.upper()})")

                logger.error(f"设置{action_names.get(action, action)}快捷键失败: {e}")
