from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPixmap,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_core.hotkey_spec import display_hotkey, is_mouse_hotkey
from app_core.player.hotkey_runtime import PlayerHotkeySession, install_global_player_hotkeys
from app_core.player.loader import prepare_player_search_paths
from app_core.player.package import (
    PlayerPackage,
    expand_script_run_queue,
    has_custom_widgets,
    player_close_hides_to_tray,
    player_should_start_hidden,
    player_should_stay_on_top,
    resolve_player_layout,
    resolve_player_theme,
    resolve_ui_asset_bytes,
)
from app_core.player.runtime import PlayerRuntimeController
from app_core.player.player_ui_state import (
    extract_settings_from_ui,
    load_player_ui_state,
    merge_settings_into_ui,
    save_player_ui_state,
)
from app_core.player.runtime_config import apply_player_ui_hotkeys
from themes import get_theme_manager, theme_color
from ui.player.player_chrome import (
    apply_player_rounded_window,
    apply_schedule_alarms_to_refs,
    apply_script_loops_to_refs,
    apply_script_run_status,
    clear_once_script_checks,
    group_loops_from_refs,
    install_window_controls,
    populate_custom_player_body,
    player_shell_qss,
    schedule_alarms_from_refs,
    script_loops_from_refs,
    selected_script_ids_from_refs,
    set_progress_widget_state,
    set_script_list_locked,
    window_outer_size,
)
from ui.player.player_settings_dialog import PlayerSettingsDialog
from utils.app_paths import get_resource_path
from utils.window.window_activation_utils import show_and_raise_widget
from utils.window.window_coordinate_common import (
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)


class PlayerWindow(QMainWindow):
    """独立程序运行窗：支持画布 widgets 绝对布局；无 widgets 时回退固定模板。"""

    def __init__(
        self,
        package: PlayerPackage,
        config: dict,
        parent=None,
        *,
        quit_on_close: bool = True,
        persist_binding: bool = True,
        initial_page: str = "",
    ):
        super().__init__(parent)
        self.setObjectName("PlayerWindow")
        self._package = package
        self._config = dict(config or {})
        self.config = self._config
        self._ui_state = load_player_ui_state(getattr(package, "userdata_dir", "") or "")
        ui_seed = merge_settings_into_ui(package.ui, self._ui_state.get("settings"))
        self._ui = apply_player_ui_hotkeys(
            ui_seed,
            getattr(package, "runtime_config", None),
            self._config,
        )
        self._hotkey_session: PlayerHotkeySession | None = None
        self._initial_page = str(initial_page or "").strip()
        self._runtime = PlayerRuntimeController(package, self._config, parent=self)
        self._closing = False
        self._force_quit = False
        self._player_tray = None
        self._quit_on_close = bool(quit_on_close)
        self._persist_binding = bool(persist_binding)
        self._exit_on_finish = bool(self._ui.get("exit_on_finish"))
        self._notify_on_finish = bool(self._ui.get("notify_on_finish", True))
        self._is_running = False
        self._is_paused = False
        self._custom_mode = has_custom_widgets(self._ui)
        self._queue_total = 0
        self._queue_index = 0
        self._run_started_at = 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._tick_progress_elapsed)
        self._persist_loops_timer = QTimer(self)
        self._persist_loops_timer.setSingleShot(True)
        self._persist_loops_timer.setInterval(250)
        self._persist_loops_timer.timeout.connect(self._persist_ui_state)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(15000)
        self._schedule_timer.timeout.connect(self._tick_schedule)
        self._last_schedule_fire = ""

        self._start_button: QPushButton | None = None
        self._pause_button: QPushButton | None = None
        self._stop_button: QPushButton | None = None
        self._bind_button: QPushButton | None = None
        self._status_label: QLabel | None = None
        self._status_dot: QLabel | None = None
        self._status_text_color = theme_color("text")
        self._status_font_size = 12
        self._log_view: QTextEdit | None = None
        self._log_frame: QFrame | None = None
        self._bg_label: QLabel | None = None
        self._start_default_text = "开始"
        self._selected_script_ids: list[str] = []
        self._script_queue: list[tuple] = []
        self._batch_running = False
        self._active_script_id = ""
        self._active_loop_index = 1
        self._active_loop_total = 1
        self._custom_refs: dict = {}

        prepare_player_search_paths(package)
        self._setup_window_chrome()
        if self._custom_mode:
            self._build_custom_body()
        else:
            self._build_legacy_body()
        self._install_bind_button()
        self._install_hotkeys()
        self._apply_layout()
        self._update_bind_status_hint()
        self._update_controls()

    @property
    def package(self) -> PlayerPackage:
        return self._package

    def _resolve_ui_dark(self) -> bool:
        """Use package theme first so chrome matches light/dark even if host theme differs."""
        mode = resolve_player_theme(self._ui)
        if mode == "dark":
            return True
        if mode == "light":
            return False
        try:
            return bool(get_theme_manager().is_dark_mode())
        except Exception:
            return False

    def _setup_window_chrome(self):
        title = str(self._ui.get("title") or self._package.manifest.get("app_name") or "独立程序")
        self.setWindowTitle(title)
        icon_candidates = (
            os.path.join(self._package.package_dir, "icon.ico"),
            os.path.join(self._package.export_root, "resources", "icon.ico"),
            get_resource_path("icon.ico"),
        )
        for icon_path in icon_candidates:
            if os.path.isfile(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break
        # 必须带 Window，否则作为设计器子窗时会嵌进对话框而不是独立弹出
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if player_should_stay_on_top(resolve_player_layout(self._ui)):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        apply_player_rounded_window(self)

        available = get_available_geometry_for_widget(self)
        if self._custom_mode:
            window = self._ui.get("window") if isinstance(self._ui.get("window"), dict) else {}
            body_w = int(window.get("width") or 460)
            body_h = int(window.get("height") or 360)
            pref_w, pref_h = window_outer_size(body_w, body_h)
        else:
            show_log = bool(self._ui.get("show_log"))
            pref_w, pref_h = 460, 520 if show_log else 240
            body_w, body_h = pref_w, pref_h
        width, height = clamp_preferred_window_size(pref_w, pref_h, available)

        container = QWidget(self)
        container.setObjectName("PlayerRoot")
        dark = self._resolve_ui_dark()
        container.setStyleSheet(player_shell_qss(dark=dark))
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._body = QWidget(container)
        self._body.setObjectName("PlayerBody")
        self._win_controls = None
        self._drag_offset = None
        if self._custom_mode:
            self._body.setFixedSize(body_w, body_h)
            layout.addWidget(self._body, 0)
            self.setFixedSize(width, height)
        else:
            layout.addWidget(self._body, 1)
            self.resize(width, height)
        self.setCentralWidget(container)
        apply_player_rounded_window(self)
        # 最小化/关闭叠在设计区右上角，不另占一层标题栏
        self._win_controls = install_window_controls(
            self._body,
            show_minimize=True,
            on_minimize=self.showMinimized,
            on_close=self.close,
            dark=dark,
        )

    def _load_pixmap(self, path: str) -> QPixmap:
        data = resolve_ui_asset_bytes(self._package, path)
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                return pix
        if path and os.path.isfile(path):
            return QPixmap(path)
        return QPixmap()

    def _on_scripts_changed(self, script_ids: list[str]):
        self._selected_script_ids = [str(item) for item in (script_ids or []) if item]

    def _schedule_persist_ui_state(self):
        self._persist_loops_timer.start()

    def _persist_ui_state(self):
        settings = extract_settings_from_ui(self._ui)
        settings["notify_on_finish"] = bool(self._notify_on_finish)
        prev = dict(self._ui_state or {})
        state = {
            "group_loops": group_loops_from_refs(self._custom_refs) or self._group_loops_from_ui(),
            "loops_by_id": script_loops_from_refs(self._custom_refs) or self._loops_from_ui(),
            "settings": settings,
            "schedule_alarms": schedule_alarms_from_refs(self._custom_refs),
            "list_order": list(prev.get("list_order") or self._ui.get("list_order") or []),
            "list_order_mode": str(prev.get("list_order_mode") or self._ui.get("list_order_mode") or "fixed"),
            "list_item_order": dict(prev.get("list_item_order") or {}),
            "list_order_modes": dict(prev.get("list_order_modes") or {}),
            "window_width": int(prev.get("window_width") or 0),
            "window_height": int(prev.get("window_height") or 0),
        }
        self._ui_state = state
        try:
            save_player_ui_state(self._package.userdata_dir, state)
        except Exception:
            logger.debug("保存独立程序 UI 状态失败", exc_info=True)

    def open_userdata_dir(self):
        path = str(getattr(self._package, "userdata_dir", "") or "").strip()
        if not path or not os.path.isdir(path):
            path = str(getattr(self._package, "export_root", "") or "").strip()
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _tick_schedule(self):
        if self._is_running or self._closing:
            return
        alarms = schedule_alarms_from_refs(self._custom_refs)
        if not alarms:
            return
        now = time.localtime()
        stamp = time.strftime("%Y-%m-%d %H:%M", now)
        if stamp == self._last_schedule_fire:
            return
        for alarm in alarms:
            if not alarm.get("enabled"):
                continue
            if int(alarm.get("hour") or -1) != now.tm_hour:
                continue
            if int(alarm.get("minute") or -1) != now.tm_min:
                continue
            self._last_schedule_fire = stamp
            self._append_log("信息", f"定时到达 {now.tm_hour:02d}:{now.tm_min:02d}，自动开始")
            QTimer.singleShot(0, self.safe_start_tasks)
            return

    def open_settings_dialog(self):
        from PySide6.QtWidgets import QDialog

        from ui.player.player_chrome import apply_player_rounded_window, window_outer_size

        dialog = PlayerSettingsDialog(
            self,
            ui=self._ui,
            state=self._ui_state,
            on_bind=self.open_window_binding_dialog,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.settings_payload()
        self._ui = merge_settings_into_ui(self._ui, payload)
        self._exit_on_finish = bool(self._ui.get("exit_on_finish"))
        self._notify_on_finish = bool(self._ui.get("notify_on_finish", True))
        order_state = dialog.result_state()
        self._ui_state = dict(self._ui_state or {})
        self._ui_state.update(order_state)
        alarms = order_state.get("schedule_alarms")
        if isinstance(alarms, list):
            self._ui_state["schedule_alarms"] = alarms
            editor = (self._custom_refs or {}).get("schedule_editor")
            if editor is not None and hasattr(editor, "set_alarms"):
                try:
                    editor.set_alarms(alarms)
                    self._custom_refs["schedule_alarms"] = alarms
                    self._custom_refs["schedule_alarm_rows"] = editor.alarm_rows()
                except RuntimeError:
                    pass
        width = int(order_state.get("window_width") or 0)
        height = int(order_state.get("window_height") or 0)
        if width > 0 and height > 0 and self._custom_mode:
            window = dict(self._ui.get("window") or {})
            window["width"] = width
            window["height"] = height
            self._ui["window"] = window
            pref_w, pref_h = window_outer_size(width, height)
            available = get_available_geometry_for_widget(self)
            out_w, out_h = clamp_preferred_window_size(pref_w, pref_h, available)
            if self._body is not None:
                self._body.setFixedSize(width, height)
            self.setFixedSize(out_w, out_h)
            apply_player_rounded_window(self)
        self._persist_ui_state()
        self._install_hotkeys()
        self._append_log("信息", "设置已保存")

    def _elapsed_text(self) -> str:
        if self._run_started_at <= 0:
            return "0:00"
        seconds = max(0, int(time.time() - self._run_started_at))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _refresh_progress_widget(self, *, idle: bool = False, prefix: str = "执行中"):
        if idle or not self._is_running:
            set_progress_widget_state(
                self._custom_refs, text="待命", value=0, maximum=100, indeterminate=False
            )
            return
        title = self._script_title(self._active_script_id) if self._active_script_id else "脚本"
        parts = [f"{prefix} · {title}"]
        if self._queue_total > 0 and self._queue_index > 0:
            parts.append(f"队列 {self._queue_index}/{self._queue_total}")
        if self._active_loop_total > 1:
            parts.append(f"循环 {self._active_loop_index}/{self._active_loop_total}")
        parts.append(f"已用 {self._elapsed_text()}")
        text = " · ".join(parts)
        if self._queue_total > 0:
            set_progress_widget_state(
                self._custom_refs,
                text=text,
                value=self._queue_index,
                maximum=self._queue_total,
                indeterminate=False,
            )
        else:
            set_progress_widget_state(
                self._custom_refs, text=text, value=0, maximum=100, indeterminate=True
            )

    def _tick_progress_elapsed(self):
        if self._is_running:
            self._refresh_progress_widget(
                prefix="已暂停" if self._is_paused else "执行中"
            )

    def _notify_finished(self, success: bool, message: str):
        if not self._notify_on_finish:
            return
        title = self.windowTitle() or "独立程序"
        body = message or ("执行完成" if success else "已停止")
        try:
            if self._ensure_player_tray() and self._player_tray is not None:
                tray = getattr(self._player_tray, "_icon", None)
                show = getattr(tray, "showMessage", None) if tray is not None else None
                if callable(show):
                    show(title, body)
                    return
        except Exception:
            logger.debug("托盘完成通知失败", exc_info=True)
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            if QSystemTrayIcon.isSystemTrayAvailable():
                # 无托盘会话时用瞬时图标提示一次
                icon = self.windowIcon()
                tip = QSystemTrayIcon(icon, self)
                tip.show()
                tip.showMessage(title, body)
                QTimer.singleShot(4000, tip.hide)
        except Exception:
            logger.debug("系统完成通知失败", exc_info=True)

    def _build_custom_body(self):
        refs = populate_custom_player_body(
            self._body,
            self._ui,
            load_pixmap=self._load_pixmap,
            on_link=self._open_link,
            on_start=self.safe_start_tasks,
            on_pause=self._on_pause_clicked,
            on_stop=self.safe_stop_tasks,
            on_bind=self.open_window_binding_dialog,
            on_settings=self.open_settings_dialog,
            on_scripts_changed=self._on_scripts_changed,
            on_loops_changed=self._schedule_persist_ui_state,
            on_open_log_dir=self.open_userdata_dir,
            on_schedule_changed=self._schedule_persist_ui_state,
            interactive_buttons=True,
            initial_page=self._initial_page,
        )
        self._custom_refs = refs
        apply_script_loops_to_refs(
            refs,
            loops_by_id=self._ui_state.get("loops_by_id") or {},
            group_loops=self._ui_state.get("group_loops"),
        )
        saved_alarms = self._ui_state.get("schedule_alarms") or []
        if saved_alarms:
            apply_schedule_alarms_to_refs(refs, saved_alarms)
        if refs.get("schedule_alarm_rows"):
            self._schedule_timer.start()
        self._bg_label = refs.get("bg_label")
        self._start_button = refs.get("start_button")
        self._pause_button = refs.get("pause_button")
        self._stop_button = refs.get("stop_button")
        self._bind_button = refs.get("bind_button")
        self._status_label = refs.get("status_label")
        self._status_dot = refs.get("status_dot")
        self._log_view = refs.get("log_view")
        self._log_frame = refs.get("log_frame")
        self._start_default_text = str(refs.get("start_default_text") or "开始")
        self._status_text_color = str(refs.get("status_text_color") or theme_color("text"))
        self._status_font_size = int(refs.get("status_font_size") or 12)
        self._selected_script_ids = selected_script_ids_from_refs(refs)
        set_progress_widget_state(refs, text="待命", value=0, maximum=100)

        if self._status_label is None:
            self._status_label = QLabel("", self._body)
            self._status_label.hide()
        if self._status_dot is None:
            self._status_dot = QLabel("", self._body)
            self._status_dot.hide()
        if self._log_view is None:
            self._log_view = QTextEdit(self._body)
            self._log_view.hide()
        if self._win_controls is not None:
            self._win_controls.reposition(self._body)
            self._win_controls.raise_()

    def _open_link(self, url: str):
        text = str(url or "").strip()
        if not (text.startswith("http://") or text.startswith("https://")):
            return
        QDesktopServices.openUrl(QUrl(text))

    def _build_legacy_body(self):
        self._body.setObjectName("PlayerBodyLegacy")
        layout = QVBoxLayout(self._body)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        about = str(self._ui.get("about") or self._package.manifest.get("description") or "").strip()
        if about:
            about_label = QLabel(about)
            about_label.setObjectName("PlayerAbout")
            about_label.setWordWrap(True)
            layout.addWidget(about_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("PlayerStatusDot")
        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("PlayerStatusLabel")
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label, 1)
        layout.addLayout(status_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self._start_button = QPushButton("开始")
        self._start_button.setObjectName("PlayerStartButton")
        self._start_button.setProperty("primary", True)
        self._start_button.setMinimumHeight(36)
        self._start_button.clicked.connect(self.safe_start_tasks)
        self._start_default_text = "开始"

        self._pause_button = QPushButton("暂停")
        self._pause_button.setObjectName("PlayerPauseButton")
        self._pause_button.setMinimumHeight(36)
        self._pause_button.clicked.connect(self._on_pause_clicked)

        self._stop_button = QPushButton("停止")
        self._stop_button.setObjectName("PlayerStopButton")
        self._stop_button.setMinimumHeight(36)
        self._stop_button.clicked.connect(self.safe_stop_tasks)

        self._bind_button = QPushButton("绑定窗口")
        self._bind_button.setObjectName("PlayerBindButton")
        self._bind_button.setMinimumHeight(36)
        self._bind_button.clicked.connect(self.open_window_binding_dialog)

        button_row.addWidget(self._start_button, 1)
        button_row.addWidget(self._pause_button, 1)
        button_row.addWidget(self._stop_button, 1)
        button_row.addWidget(self._bind_button, 1)
        layout.addLayout(button_row)

        self._log_frame = QFrame(self._body)
        self._log_frame.setObjectName("PlayerLogFrame")
        log_layout = QVBoxLayout(self._log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        log_title = QLabel("运行日志")
        log_title.setObjectName("PlayerLogTitle")
        self._log_view = QTextEdit()
        self._log_view.setObjectName("PlayerLogView")
        self._log_view.setReadOnly(True)
        log_layout.addWidget(log_title)
        log_layout.addWidget(self._log_view, 1)
        layout.addWidget(self._log_frame, 1)

        if not bool(self._ui.get("show_log")):
            self._log_frame.hide()

        hotkey_text = "  ·  ".join(
            part
            for part in (
                f"开始 {display_hotkey(self._ui.get('start_hotkey'))}",
                f"停止 {display_hotkey(self._ui.get('stop_hotkey'))}",
                f"暂停 {display_hotkey(self._ui.get('pause_hotkey'))}",
            )
            if part
        )
        hotkey_label = QLabel(hotkey_text)
        hotkey_label.setObjectName("PlayerHotkeyHint")
        hotkey_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hotkey_label)

    def _install_hotkeys(self):
        old = self._hotkey_session
        self._hotkey_session = None
        if old is not None:
            try:
                old.release()
            except Exception:
                logger.debug("重装热键前注销失败", exc_info=True)
        mapping = {
            "start": (self._ui.get("start_hotkey"), self.safe_start_tasks),
            "stop": (self._ui.get("stop_hotkey"), self.safe_stop_tasks),
            "pause": (self._ui.get("pause_hotkey"), self._on_pause_clicked),
        }
        if self._quit_on_close:
            session = install_global_player_hotkeys(
                self,
                {action: str(spec or "") for action, (spec, _cb) in mapping.items()},
                {action: cb for action, (_spec, cb) in mapping.items()},
            )
            self._hotkey_session = session
            if session.keyboard_active:
                # 全局钩子已接管键盘；鼠标侧键也只能走钩子
                return
        for action, (key, callback) in mapping.items():
            text = str(key or "").strip()
            if not text or is_mouse_hotkey(text):
                continue
            shortcut = QShortcut(QKeySequence(text), self)
            # 开发态挂在编辑器里时，热键只在本窗生效，避免抢走编辑器 F9/F10/F11
            shortcut.setContext(
                Qt.ShortcutContext.ApplicationShortcut
                if self._quit_on_close
                else Qt.ShortcutContext.WindowShortcut
            )
            shortcut.activated.connect(callback)

    def _install_bind_button(self) -> None:
        """自定义界面未画「绑定窗口」按钮时，在内容区左下角补一个入口。"""
        if self._bind_button is not None:
            return
        self._bind_button = QPushButton("绑定窗口", self._body)
        self._bind_button.setObjectName("PlayerBindButtonFloating")
        self._bind_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bind_button.setFixedHeight(28)
        self._bind_button.adjustSize()
        self._bind_button.clicked.connect(self.open_window_binding_dialog)
        self._bind_button.move(10, max(10, self._body.height() - 38))
        self._bind_button.raise_()
        self._body.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            obj is self._body
            and self._bind_button is not None
            and self._bind_button.objectName() == "PlayerBindButtonFloating"
            and event is not None
            and event.type() == QEvent.Type.Resize
        ):
            self._bind_button.move(10, max(10, self._body.height() - 38))
        return super().eventFilter(obj, event)

    def open_window_binding_dialog(self) -> None:
        from ui.player.player_window_binding_dialog import open_player_window_binding_dialog

        def _on_saved(updated: dict) -> None:
            self._config = dict(updated or {})
            self.config = self._config
            self._runtime.update_config(self._config)
            self._update_bind_status_hint()

        from app_core.player.window_resolution import required_client_size

        required_width, required_height = required_client_size(
            package=self._package, config=self._config
        )
        open_player_window_binding_dialog(
            self,
            self._config,
            on_saved=_on_saved,
            persist_config=self._persist_binding,
            required_client_width=required_width,
            required_client_height=required_height,
        )

    def _update_bind_status_hint(self) -> None:
        if self._is_running or self._status_label is None:
            return
        windows = list(self._config.get("bound_windows") or [])
        if not windows:
            self._set_status("未绑定窗口", running=False)
            return
        from utils.window.hwnd_utils import as_hwnd
        from utils.window.window_identity import is_window_alive, refresh_bound_windows

        refresh_bound_windows(windows)
        alive = sum(1 for item in windows if isinstance(item, dict) and is_window_alive(as_hwnd(item.get("hwnd"))))
        from app_core.player.window_resolution import find_resolution_mismatches, required_client_size

        required_width, required_height = required_client_size(
            package=self._package, config=self._config
        )
        mismatches = find_resolution_mismatches(windows, required_width, required_height)
        title = ""
        if windows and isinstance(windows[0], dict):
            title = str(windows[0].get("title") or "").strip()
        if mismatches:
            self._set_status("分辨率不符合要求", running=False)
            return
        if len(windows) == 1 and title:
            short = title if len(title) <= 24 else title[:21] + "..."
            self._set_status(f"已绑定: {short}", running=False)
        else:
            self._set_status(f"已绑定 {alive}/{len(windows)} 个窗口", running=False)

    def _apply_layout(self):
        layout = resolve_player_layout(self._ui)
        if player_should_start_hidden(layout, tray_available=self._ensure_player_tray()):
            self.hide()
            return
        show_and_raise_widget(self, log_prefix="独立程序窗口")

    def _ensure_player_tray(self) -> bool:
        if getattr(self, "system_tray_manager", None) is not None:
            return True
        if self._player_tray is not None:
            return True
        from ui.player.player_tray import PlayerTraySession

        session = PlayerTraySession(self)
        if not session.install():
            return False
        self._player_tray = session
        return True

    def _cleanup_player_tray(self) -> None:
        session = self._player_tray
        self._player_tray = None
        if session is None:
            return
        try:
            session.cleanup()
        except Exception:
            logger.debug("关闭独立程序托盘失败", exc_info=True)

    def request_quit(self):
        self._force_quit = True
        self.close()

    def handle_task_state_change(self, *_args):
        return None

    def safe_start_tasks(self):
        if self._is_running and self._is_paused:
            self._runtime.toggle_pause()
            self._is_paused = False
            self._set_status(self._running_status_text("执行中"), running=True)
            self._refresh_script_run_status(state="running")
            self._append_log("信息", "已恢复执行")
            self._update_controls()
            return
        if self._is_running:
            return
        windows = list(self._config.get("bound_windows") or [])
        if not windows:
            reply = QMessageBox.question(
                self,
                "未绑定窗口",
                "尚未绑定目标窗口，是否现在绑定？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.open_window_binding_dialog()
            return
        try:
            if self._log_view is not None:
                self._log_view.clear()
            queue = self._resolve_run_scripts()
            if queue == []:
                QMessageBox.warning(self, "无法启动", "请至少勾选一项可用脚本。")
                return
            if queue:
                # queue 已是展开后的执行队列（含多列表/随机）
                if queue and len(queue[0]) >= 4:
                    self._script_queue = list(queue)
                else:
                    loops_by_id = script_loops_from_refs(self._custom_refs)
                    if not loops_by_id:
                        loops_by_id = self._loops_from_ui()
                    self._script_queue = expand_script_run_queue(
                        queue,
                        loops_by_id=loops_by_id,
                        group_loops=group_loops_from_refs(self._custom_refs)
                        or self._group_loops_from_ui(),
                    )
                self._batch_running = True
                self._queue_total = len(self._script_queue)
                self._queue_index = 0
                self._run_started_at = time.time()
                self._persist_ui_state()
                self._start_next_queued_script()
                return
            self._batch_running = False
            self._active_script_id = ""
            self._queue_total = 1
            self._queue_index = 1
            self._run_started_at = time.time()
            self._persist_ui_state()
            self._runtime.start(
                on_started=self._on_started,
                on_finished=self._on_finished,
                on_step_log=self._on_step_log,
            )
        except Exception as exc:
            self._clear_script_queue()
            logger.error("独立程序启动失败: %s", exc, exc_info=True)
            QMessageBox.critical(self, "无法启动", str(exc))

    def _script_title(self, script_id: str) -> str:
        sid = str(script_id or "").strip()
        if not sid:
            return "脚本"
        for widget in self._ui.get("widgets") or []:
            if not isinstance(widget, dict) or widget.get("type") != "script_list":
                continue
            for item in widget.get("items") or []:
                if isinstance(item, dict) and str(item.get("id") or "") == sid:
                    return str(item.get("title") or sid)
        for item in self._package.manifest.get("scripts") or []:
            if isinstance(item, dict) and str(item.get("id") or "") == sid:
                return str(item.get("title") or sid)
        return sid

    def _loops_from_ui(self) -> dict[str, int]:
        from app_core.player.package import normalize_script_loop_count

        loops: dict[str, int] = {}
        for widget in self._ui.get("widgets") or []:
            if not isinstance(widget, dict) or widget.get("type") != "script_list":
                continue
            for item in widget.get("items") or []:
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("id") or "").strip()
                if sid:
                    loops[sid] = normalize_script_loop_count(item.get("loops"), 1)
        return loops

    def _group_loops_from_ui(self) -> int:
        from app_core.player.package import normalize_script_loop_count

        for widget in self._ui.get("widgets") or []:
            if isinstance(widget, dict) and widget.get("type") == "script_list":
                return normalize_script_loop_count(widget.get("group_loops"), 1)
        return 1

    def _waiting_script_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in self._script_queue:
            if not item:
                continue
            sid = str(item[0] or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                ids.append(sid)
        return ids

    def _refresh_script_run_status(self, *, state: str = "idle"):
        apply_script_run_status(
            self._custom_refs,
            active_id=self._active_script_id if state != "idle" else "",
            loop_index=self._active_loop_index,
            loop_total=self._active_loop_total,
            state=state,
            waiting_ids=self._waiting_script_ids() if state != "idle" else [],
        )

    def _resolve_run_scripts(self) -> list[tuple] | None:
        """有脚本列表时返回展开后的执行队列；无列表或包内无脚本则返回 None。"""
        from ui.player.player_chrome import selected_script_ids_by_list_from_refs
        from ui.player.script_run_order import build_run_queue_parts

        has_list = bool(self._custom_refs.get("script_lists")) or bool(
            self._custom_refs.get("script_list_widget")
        ) or bool(self._custom_refs.get("script_checkboxes"))
        if not has_list:
            return None
        self._selected_script_ids = selected_script_ids_from_refs(self._custom_refs)
        available = dict(self._package.scripts or {})
        if not available:
            return None
        by_list = selected_script_ids_by_list_from_refs(self._custom_refs)
        if not any(by_list.values()):
            return []
        loops_by_id = script_loops_from_refs(self._custom_refs)
        if not loops_by_id:
            loops_by_id = self._loops_from_ui()
        state = getattr(self, "_ui_state", None) or {}
        return build_run_queue_parts(
            self._ui,
            selected_by_list=by_list,
            scripts=available,
            state=state if isinstance(state, dict) else {},
            loops_by_id=loops_by_id,
        )

    def _clear_script_queue(self):
        self._script_queue = []
        self._batch_running = False
        self._active_script_id = ""
        self._active_loop_index = 1
        self._active_loop_total = 1
        self._queue_total = 0
        self._queue_index = 0
        self._refresh_script_run_status(state="idle")

    def _start_next_queued_script(self):
        if not self._script_queue:
            self._clear_script_queue()
            return
        item = self._script_queue.pop(0)
        if len(item) >= 4:
            sid, data, loop_index, loop_total = item[0], item[1], int(item[2]), int(item[3])
        else:
            sid, data = item[0], item[1]
            loop_index, loop_total = 1, 1
        self._active_script_id = sid
        self._active_loop_index = max(1, loop_index)
        self._active_loop_total = max(1, loop_total)
        if self._queue_total > 0:
            self._queue_index = min(
                self._queue_total,
                self._queue_total - len(self._script_queue),
            )
        title = self._script_title(sid)
        remain = len(self._script_queue)
        extra = f"（其后还有 {remain} 项）" if remain else ""
        if self._active_loop_total > 1:
            extra = f"（第 {self._active_loop_index}/{self._active_loop_total} 次）{extra}"
        self._append_log("信息", f"开始执行「{title}」{extra}")
        self._refresh_script_run_status(state="running")
        self._refresh_progress_widget(prefix="执行中")
        self._runtime.start(
            on_started=self._on_started,
            on_finished=self._on_batch_script_finished,
            on_step_log=self._on_step_log,
            workflow_data=data,
            script_id=sid,
        )

    def _on_batch_script_finished(self, success: bool, message: str):
        self._runtime.release()
        if self._closing:
            self._clear_script_queue()
            return
        title = self._script_title(self._active_script_id)
        if success and self._script_queue:
            self._append_log("完成", f"「{title}」执行完成")
            QTimer.singleShot(0, self._run_next_queued_script_safe)
            return
        self._clear_script_queue()
        if success:
            self._on_finished(True, message or "全部脚本执行完成")
            return
        self._on_finished(False, message or f"「{title}」已停止")

    def _run_next_queued_script_safe(self):
        try:
            self._start_next_queued_script()
        except Exception as exc:
            self._clear_script_queue()
            logger.error("独立程序切换脚本失败: %s", exc, exc_info=True)
            self._on_finished(False, str(exc))

    def safe_stop_tasks(self):
        self._script_queue = []
        self._runtime.stop(force=True)

    def _on_pause_clicked(self):
        if not self._is_running:
            return
        self._runtime.toggle_pause()
        self._is_paused = not self._is_paused
        if self._is_paused:
            self._set_status(self._running_status_text("已暂停"), running=False, paused=True)
            self._refresh_script_run_status(state="paused")
            self._refresh_progress_widget(prefix="已暂停")
            self._append_log("信息", "已暂停")
        else:
            self._set_status(self._running_status_text("执行中"), running=True)
            self._refresh_script_run_status(state="running")
            self._refresh_progress_widget(prefix="执行中")
            self._append_log("信息", "已恢复执行")
        self._update_controls()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        apply_player_rounded_window(self)
        from themes.rounded_popup import apply_native_window_corners

        apply_native_window_corners(self)

    def restore_main_window(self):
        if resolve_player_layout(self._ui) == "tray":
            self.showNormal()
        show_and_raise_widget(self, log_prefix="独立程序窗口")

    def _running_status_text(self, prefix: str = "执行中") -> str:
        title = self._script_title(self._active_script_id) if self._active_script_id else ""
        if not title:
            return prefix
        if self._active_loop_total > 1:
            return f"{prefix} · {title} {self._active_loop_index}/{self._active_loop_total}"
        return f"{prefix} · {title}"

    def _on_started(self):
        self._is_running = True
        self._is_paused = False
        if self._run_started_at <= 0:
            self._run_started_at = time.time()
        if not self._progress_timer.isActive():
            self._progress_timer.start()
        self._set_status(self._running_status_text("执行中"), running=True)
        self._refresh_script_run_status(state="running")
        self._refresh_progress_widget(prefix="执行中")
        if not self._batch_running:
            self._append_log("信息", "工作流开始执行")
        self._update_controls()

    def _on_finished(self, success: bool, message: str):
        self._is_running = False
        self._is_paused = False
        self._progress_timer.stop()
        self._runtime.release()
        self._refresh_script_run_status(state="idle")
        self._refresh_progress_widget(idle=True)
        if success:
            self._set_status("执行完成", running=False)
            self._append_log("完成", message or "执行完成")
        else:
            self._set_status("已停止", running=False)
            self._append_log("停止", message or "已停止")
        self._update_controls()
        self._notify_finished(success, message or ("执行完成" if success else "已停止"))
        clear_once_script_checks(self._custom_refs)
        self._on_scripts_changed(selected_script_ids_from_refs(self._custom_refs))
        self._run_started_at = 0.0
        self._queue_total = 0
        self._queue_index = 0
        if self._exit_on_finish and not self._closing:
            QTimer.singleShot(300, self.close)

    def _on_step_log(self, card_type: str, message: str, success: bool):
        status = "成功" if success else "失败"
        if "开始执行" in str(message or "") and "执行成功" not in str(message or ""):
            status = "信息"
        text = f"{card_type}: {message}" if message else str(card_type or "")
        self._append_log(status, text)
        if self._is_running and not self._is_paused and self._status_label is not None:
            heading = self._running_status_text("执行中")
            short = text if len(text) <= 24 else text[:21] + "..."
            self._status_label.setText(f"{heading} · {short}" if short else heading)

    def _append_log(self, status: str, message: str):
        if self._log_view is None or not self._log_view.isVisible():
            # 隐藏日志时仍允许写入（若控件存在）
            if self._log_view is None:
                return
        stamp = time.strftime("%H:%M:%S")
        self._log_view.append(f"[{stamp}] [{status}] {message}")
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_status(self, text: str, *, running: bool = False, paused: bool = False):
        size = int(self._status_font_size or 12)
        color = str(self._status_text_color or theme_color("text"))
        if self._status_label is not None:
            self._status_label.setText(text)
            self._status_label.setStyleSheet(
                f"color:{color}; font-size:{size}px; background:transparent; border:none;"
            )
        if self._status_dot is None:
            return
        if paused:
            self._status_dot.setProperty("state", "paused")
            dot_color = theme_color("warning")
        elif running:
            self._status_dot.setProperty("state", "running")
            dot_color = theme_color("accent")
        else:
            self._status_dot.setProperty("state", "idle")
            dot_color = theme_color("success")
        self._status_dot.setStyleSheet(
            f"color:{dot_color}; font-size:{size}px; background:transparent; border:none;"
        )
        style = self._status_dot.style()
        if style is not None:
            style.unpolish(self._status_dot)
            style.polish(self._status_dot)

    def _update_controls(self):
        start = self._start_button
        pause = self._pause_button
        stop = self._stop_button
        set_script_list_locked(self._custom_refs, self._is_running)
        for _sid, box in self._custom_refs.get("script_checkboxes") or []:
            try:
                box.setEnabled(not self._is_running)
            except RuntimeError:
                continue
        if start is None and pause is None and stop is None:
            return
        if self._is_running and self._is_paused:
            if start is not None:
                start.setText("恢复")
                start.setEnabled(True)
            if pause is not None:
                pause.setEnabled(False)
            if stop is not None:
                stop.setEnabled(True)
            return
        if self._is_running:
            if start is not None:
                start.setText(self._start_default_text)
                start.setEnabled(False)
            if pause is not None:
                pause.setEnabled(True)
            if stop is not None:
                stop.setEnabled(True)
            return
        if start is not None:
            start.setText(self._start_default_text)
            start.setEnabled(True)
        if pause is not None:
            pause.setEnabled(False)
        if stop is not None:
            stop.setEnabled(False)

    def maybe_auto_start(self):
        if bool(self._ui.get("auto_start")):
            QTimer.singleShot(400, self.safe_start_tasks)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._custom_mode:
            from ui.player.player_chrome import apply_player_background_geometry

            apply_player_background_geometry(
                self._body, self._bg_label, self._ui.get("background") or {}
            )
        if self._win_controls is not None:
            self._win_controls.reposition(self._body)
            self._win_controls.raise_()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # 无边框窗口：空白处拖拽移动
            child = self.childAt(event.position().toPoint())
            from ui.player.player_chrome import PlayerWindowControls

            if child is None or isinstance(child, (QLabel,)) and child.objectName() in ("PlayerBg", "PlayerBgFill", ""):
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
            if isinstance(child, PlayerWindowControls):
                self._drag_offset = None
                super().mousePressEvent(event)
                return
        self._drag_offset = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent):
        layout = resolve_player_layout(self._ui)
        if (
            not self._force_quit
            and player_close_hides_to_tray(layout, quit_on_close=self._quit_on_close)
            and self._ensure_player_tray()
        ):
            event.ignore()
            self.hide()
            return
        self._closing = True
        self._progress_timer.stop()
        self._schedule_timer.stop()
        try:
            self._persist_ui_state()
        except Exception:
            logger.debug("关闭前保存 UI 状态失败", exc_info=True)
        self._cleanup_player_tray()
        self._clear_script_queue()
        session = self._hotkey_session
        self._hotkey_session = None
        if session is not None:
            try:
                session.release()
            except Exception:
                logger.debug("关闭独立程序时注销热键失败", exc_info=True)
        try:
            self._runtime.stop(force=True)
        except Exception:
            logger.debug("关闭独立程序时停止工作流失败", exc_info=True)
        if self._quit_on_close:
            app = QApplication.instance()
            if app is not None:
                app.quit()
        event.accept()
