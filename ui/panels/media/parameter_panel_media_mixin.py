from ..parameter_panel_support import *
from utils.window.window_activation_utils import show_and_raise_widget
from .parameter_panel_image_viewer_dialog import ParameterPanelImageViewerDialog
from PySide6.QtGui import QPixmap

class ParameterPanelMediaMixin:

    def _select_file(self, line_edit: QLineEdit, param_def: Dict[str, Any]):
        file_types = param_def.get('file_types')
        if file_types:
            if isinstance(file_types, list):
                file_filter = ';;'.join(file_types)
            else:
                file_filter = file_types
        else:
            file_filter = param_def.get('file_filter', 'All Files (*)')

        filename, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if filename:
            if self._is_yolo_model_param(param_def) and not filename.lower().endswith('.onnx'):
                ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "模型格式提示",
                    f"检测到您选择的是 .{ext} 格式模型?\n\n"
                    "本程序仅支持 ONNX 格式模型，请先将模型转换为 .onnx 格式?"
                )
                return

            param_name = self._get_registered_widget_name(line_edit)
            selected_value = self._normalize_single_image_parameter_value(param_name, filename)
            line_edit.setText(selected_value)
            self._update_current_parameter_from_widget(line_edit, selected_value)
            self._apply_parameters(auto_close=False)

    def _is_yolo_model_param(self, param_def: Dict[str, Any]) -> bool:
        file_types = param_def.get('file_types', [])
        if isinstance(file_types, list):
            for ft in file_types:
                if 'onnx' in ft.lower() or 'yolo' in ft.lower():
                    return True
        elif isinstance(file_types, str):
            if 'onnx' in file_types.lower() or 'yolo' in file_types.lower():
                return True
        return False

    def _open_sub_workflow_for_edit(self, line_edit: QLineEdit):
        workflow_file = line_edit.text().strip()
        if not workflow_file:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先选择工作流文件")
            return

        try:
            if self.main_window and hasattr(self.main_window, 'workflow_tab_widget'):
                tab_widget = self.main_window.workflow_tab_widget
                parent_workflow_file = None
                if hasattr(tab_widget, "_get_current_workflow_filepath"):
                    parent_workflow_file = tab_widget._get_current_workflow_filepath()
                tab_widget.open_sub_workflow(
                    workflow_file,
                    parent_workflow_file=parent_workflow_file,
                )
                logger.info(f"[子工作流] 已请求打开: {workflow_file}")
            else:
                logger.warning("[子工作流] 无法找到主窗口或workflow_tab_widget")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "错误", "无法打开子工作流编辑器")
        except Exception as e:
            logger.error(f"[子工作流] 打开失败: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"打开子工作流失败:\n{e}")

    def _resolve_validated_screenshot_hwnd(self):
        validated_hwnd = self.target_window_hwnd
        if not self.target_window_hwnd or not self.main_window:
            return validated_hwnd
        if self.main_window.is_hwnd_bound(self.target_window_hwnd):
            return validated_hwnd

        logger.warning(
            f"当前 hwnd 已不再绑定，尝试回退: {self.target_window_hwnd}"
        )
        validated_hwnd, _ = self.main_window.validate_hwnd_or_get_first(self.target_window_hwnd)
        return validated_hwnd

    def _warn_no_available_screenshot_window(self):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self,
            "警告",
            "没有可用的绑定窗口。\n\n"
            "请先在全局设置中绑定窗口后再使用截图工具。",
        )

    def _hide_windows_before_screenshot(self):
        self.hide()
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.hide()
            logger.debug('截图前已隐藏主窗口和参数面板')

    def _schedule_screenshot_overlay_start(self, line_edit: QLineEdit, hwnd):
        from PySide6.QtCore import QTimer

        QTimer.singleShot(
            200,
            lambda edit=line_edit, target_hwnd=hwnd: self._start_screenshot_delayed(edit, target_hwnd),
        )

    @staticmethod
    def _is_qt_widget_alive(widget) -> bool:
        if widget is None:
            return False
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False

    def _start_screenshot_for_param(self, line_edit: QLineEdit):
        try:
            logger.info(f"启动截图工具, hwnd={self.target_window_hwnd}")
            validated_hwnd = self._resolve_validated_screenshot_hwnd()
            if not validated_hwnd:
                self._warn_no_available_screenshot_window()
                return

            self._current_screenshot_param_name = self._get_registered_widget_name(line_edit)
            self._current_screenshot_target = line_edit
            self._hide_windows_before_screenshot()
            self._schedule_screenshot_overlay_start(line_edit, validated_hwnd)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动截图工具失败: {exc}", exc_info=True)
            QMessageBox.critical(self, "错误", f"启动截图工具失败: {str(exc)}")

    def _resolve_screenshot_save_dir(self) -> str:
        images_dir = str(getattr(self, "images_dir", "") or "").strip()
        return images_dir or "images"

    def _load_screenshot_format(self):
        screenshot_format = 'bmp'
        try:
            from app_core.config_store import load_config

            config = load_config()
            screenshot_format = config.get('screenshot_format', 'bmp')
        except Exception as exc:
            logger.warning(f"加载截图格式失败，已回退到 BMP: {exc}")
        return screenshot_format

    def _create_screenshot_overlay(self, target_hwnd):
        from ...selectors.screenshot_tool import ScreenshotOverlay

        return ScreenshotOverlay(
            target_hwnd=target_hwnd,
            save_dir=self._resolve_screenshot_save_dir(),
            parent=None,
            screenshot_format=self._load_screenshot_format(),
            card_id=self.current_card_id,
            workflow_id=self._get_active_workflow_file_token(),
        )

    def _connect_screenshot_overlay_signals(self):
        self._screenshot_overlay.screenshot_taken.connect(self._on_screenshot_path_ready)
        self._screenshot_overlay.screenshot_cancelled.connect(self._on_screenshot_cancelled)

    def _start_screenshot_delayed(self, line_edit: QLineEdit, hwnd=None):
        try:
            if self._is_qt_widget_alive(line_edit):
                self._current_screenshot_target = line_edit
                if not getattr(self, "_current_screenshot_param_name", None):
                    self._current_screenshot_param_name = self._get_registered_widget_name(line_edit)
            target_hwnd = hwnd if hwnd is not None else self.target_window_hwnd
            self._screenshot_overlay = self._create_screenshot_overlay(target_hwnd)
            self._connect_screenshot_overlay_signals()
            if self._screenshot_overlay.capture_and_show():
                return

            logger.error('显示截图覆盖层失败')
            self._screenshot_overlay = None
            self._restore_windows_after_screenshot()
            logger.info('截图覆盖层显示失败后已恢复窗口')
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动延迟截图工具失败: {exc}", exc_info=True)
            self._restore_windows_after_screenshot()
            QMessageBox.critical(self, "错误", f"启动截图工具失败: {str(exc)}")

    def _invalidate_screenshot_template_cache(self, filepath: str):
        try:
            from utils.match.template_preloader import get_global_preloader

            get_global_preloader().invalidate_template(filepath)
        except Exception as exc:
            logger.debug(f"使截图模板缓存失效失败: {exc}")
        try:
            from utils.image_paths import get_image_path_resolver

            get_image_path_resolver().invalidate(filepath)
        except Exception as exc:
            logger.debug(f"使截图路径缓存失效失败: {exc}")

    def _resolve_screenshot_target_input(self, param_name: Optional[str]):
        if param_name:
            current = self._get_value_widget(param_name)
            if self._is_qt_widget_alive(current) and isinstance(current, QLineEdit):
                return current
        stale = getattr(self, "_current_screenshot_target", None)
        if self._is_qt_widget_alive(stale) and isinstance(stale, QLineEdit):
            return stale
        return None

    def _refresh_screenshot_preview(self, filepath: str, param_name: Optional[str], target_input=None):
        try:
            preview_key = None
            if self._is_qt_widget_alive(target_input):
                preview_key = target_input.property('preview_key')
            if not preview_key and param_name:
                preview_key = f"{param_name}_preview"
            if not preview_key or preview_key not in self.widgets:
                return
            preview_label = self.widgets[preview_key]
            if isinstance(preview_label, QLabel):
                self._update_image_preview(filepath, preview_label)
        except Exception as exc:
            logger.warning(f"刷新截图预览失败: {exc}")

    def _clear_screenshot_runtime_state(self):
        self._current_screenshot_target = None
        self._current_screenshot_param_name = None
        self._screenshot_overlay = None

    def _import_screenshot_to_parameter(self, filepath: str) -> None:
        param_name = getattr(self, "_current_screenshot_param_name", None)
        target_input = self._resolve_screenshot_target_input(param_name)
        if not param_name and target_input is not None:
            param_name = self._get_registered_widget_name(target_input)
        if not param_name:
            param_name = "image_path"

        normalized_path = self._normalize_single_image_parameter_value(param_name, filepath)
        if not normalized_path:
            normalized_path = filepath

        self._invalidate_screenshot_template_cache(filepath)
        if target_input is not None:
            target_input.blockSignals(True)
            try:
                target_input.setText(str(normalized_path))
            finally:
                target_input.blockSignals(False)
        self._refresh_screenshot_preview(filepath, param_name, target_input)
        self._apply_live_parameter_changes({param_name: normalized_path}, refresh_conditional=False)
        logger.info(f"截图已导入参数 {param_name}: {normalized_path}")

    def _on_screenshot_path_ready(self, filepath: str):
        try:
            if os.path.isfile(filepath):
                self._import_screenshot_to_parameter(filepath)
            else:
                logger.error(f"截图文件未找到，无法导入: {filepath}")
            self._clear_screenshot_runtime_state()
            self._restore_windows_after_screenshot()
        except Exception as exc:
            logger.error(f"处理截图路径失败: {exc}", exc_info=True)
            self._clear_screenshot_runtime_state()
            self._restore_windows_after_screenshot()

    def _restore_windows_after_screenshot(self):
        if hasattr(self, 'main_window') and self.main_window:
            show_and_raise_widget(self.main_window, log_prefix='主窗口恢复')
        show_and_raise_widget(self, log_prefix='参数面板恢复')
        logger.debug('截图完成后已恢复参数面板和主窗口')

    def _on_screenshot_cancelled(self):
        logger.info('截图已取消')
        self._clear_screenshot_runtime_state()
        self._restore_windows_after_screenshot()

    _PREVIEW_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp')

    def _update_image_preview(self, image_path: str, preview_label: QLabel):
        """Update image preview."""
        try:
            self._reset_preview_label(preview_label)
            if not image_path or not image_path.strip():
                self._set_preview_status(preview_label, "未选择图片")
                return

            resolved_path = self._resolve_preview_image_path(image_path)
            self._set_preview_image_property(preview_label, resolved_path)

            validation_message = self._validate_preview_image_path(resolved_path)
            if validation_message:
                self._set_preview_status(preview_label, validation_message)
                return

            pixmap = self._load_preview_pixmap(resolved_path)
            if pixmap is None or pixmap.isNull():
                self._set_preview_status(preview_label, "无法加载图片")
                return

            self._apply_preview_pixmap(preview_label, pixmap)
            preview_label.setToolTip(self._build_preview_tooltip(image_path, resolved_path, pixmap))
            logger.debug(f"图片预览已更新: {resolved_path} ({pixmap.width()}x{pixmap.height()})")
        except Exception as e:
            logger.error(f"更新图片预览失败: {e}", exc_info=True)
            self._set_preview_status(preview_label, f"预览失败: {e}")

    def _reset_preview_label(self, preview_label: QLabel) -> None:
        preview_label.clear()
        preview_label.setToolTip("")

    def _set_preview_status(self, preview_label: QLabel, message: str) -> None:
        preview_label.setText(message)
        preview_label.setProperty("image_path", "")

    def _resolve_preview_image_path(self, image_path: str) -> str:
        if os.path.exists(image_path):
            return image_path
        filename = os.path.basename(str(image_path or "").strip())
        search_roots = []
        if self.images_dir:
            search_roots.append(self.images_dir)
        try:
            from utils.app_paths import get_images_dir

            search_roots.append(get_images_dir("LCA"))
        except Exception:
            pass
        if filename:
            for root in search_roots:
                if not root:
                    continue
                candidate = os.path.join(root, filename)
                if os.path.isfile(candidate):
                    return candidate
        try:
            from tasks.task_utils import get_image_path_resolver

            resolver = get_image_path_resolver()
            if self.images_dir and os.path.exists(self.images_dir):
                resolver.add_search_path(self.images_dir, priority=0)
            resolved_path = resolver.resolve(image_path)
            if resolved_path:
                logger.debug(f"图片路径自动解析: {image_path} -> {resolved_path}")
                return resolved_path
        except Exception as e:
            logger.warning(f"路径解析器调用失败: {e}")
        return image_path

    def _set_preview_image_property(self, preview_label: QLabel, resolved_path: str) -> None:
        preview_label.setProperty(
            "image_path",
            resolved_path if resolved_path and os.path.exists(resolved_path) else "",
        )

    def _validate_preview_image_path(self, resolved_path: str) -> Optional[str]:
        if not os.path.exists(resolved_path):
            return "文件不存在"
        if not resolved_path.lower().endswith(self._PREVIEW_IMAGE_EXTENSIONS):
            return "不是图片文件"
        return None

    def _load_preview_pixmap(self, resolved_path: str) -> Optional[QPixmap]:
        pixmap = QPixmap()
        for _ in range(3):
            try:
                with open(resolved_path, 'rb') as image_file:
                    file_bytes = image_file.read()
                if file_bytes and pixmap.loadFromData(file_bytes):
                    return pixmap
            except Exception:
                pass
            time.sleep(0.03)

        fallback_pixmap = QPixmap(resolved_path)
        if fallback_pixmap.isNull():
            return None
        return fallback_pixmap

    def _apply_preview_pixmap(self, preview_label: QLabel, pixmap: QPixmap) -> None:
        scaled_pixmap = pixmap.scaled(
            max(1, preview_label.width() - 6),
            74,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        preview_label.setPixmap(scaled_pixmap)
        preview_label.setScaledContents(False)

    def _build_preview_tooltip(self, image_path: str, resolved_path: str, pixmap: QPixmap) -> str:
        file_size = os.path.getsize(resolved_path) / 1024
        hint_text = "提示: 双击可查看原图（支持放大缩小）"
        if resolved_path != image_path:
            return (
                f"原路径: {image_path}\n"
                f"解析为: {resolved_path}\n"
                f"尺寸: {pixmap.width()} x {pixmap.height()} 像素\n"
                f"大小: {file_size:.1f} KB\n\n"
                f"{hint_text}"
            )
        return (
            f"路径: {resolved_path}\n"
            f"尺寸: {pixmap.width()} x {pixmap.height()} 像素\n"
            f"大小: {file_size:.1f} KB\n\n"
            f"{hint_text}"
        )

    def _show_image_viewer(self, image_path: str):
        """Show image viewer."""
        try:
            viewer = ParameterPanelImageViewerDialog(image_path, self)
            viewer.exec()
        except Exception as e:
            logger.error(f"显示图片查看器失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"无法打开图片查看器: {e}")

    def _select_multiple_files(self, text_edit: QTextEdit, param_def: Dict[str, Any]):
        """Select multiple files."""
        try:
            file_paths = self._get_multi_image_selected_files(param_def)
            if not file_paths:
                return
            display_text = self._format_image_paths_display(file_paths)
            new_text = self._merge_multi_image_display_text(text_edit.toPlainText().strip(), display_text)
            self._sync_multi_image_text_edit(text_edit, new_text)
            self._update_current_parameter_from_widget(text_edit, new_text)
            logger.info(f"已选择 {len(file_paths)} 个文件")
        except Exception as e:
            logger.error(f"选择多个文件时发生错误: {e}")

    def _select_multiple_files_with_thumbnails(self, param_name: str, text_edit: QTextEdit, param_def: Dict[str, Any]):
        """Select multiple files with thumbnails."""
        try:
            file_paths = self._get_multi_image_selected_files(param_def)
            if not file_paths:
                return
            display_text = self._format_image_paths_display(file_paths)
            new_text = self._merge_multi_image_display_text(text_edit.toPlainText().strip(), display_text)
            self._sync_multi_image_text_edit(text_edit, new_text)
            self._sync_multi_image_parameter_value(param_name, new_text, emit_signal=True)
            logger.info(f"已选择 {len(file_paths)} 个文件")
        except Exception as e:
            logger.error(f"选择多个文件时发生错误: {e}")

    def _get_multi_image_selected_files(self, param_def: Dict[str, Any]):
        file_filter = param_def.get(
            'file_filter',
            '图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*.*)',
        )
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            '选择多个图片文件',
            '',
            file_filter,
        )
        return file_paths

    def _merge_multi_image_display_text(self, current_text: str, display_text: str) -> str:
        if current_text:
            return current_text + "\n" + display_text
        return display_text

    def _sync_multi_image_text_edit(self, text_edit: QTextEdit, new_text: str) -> None:
        text_edit.setPlainText(new_text)

    def _sync_multi_image_parameter_value(self, param_name: str, new_text: str, emit_signal: bool = False) -> None:
        self.current_parameters[param_name] = new_text
        if emit_signal and self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, {param_name: new_text})

    def _delete_single_image(self, param_name: str, image_path: str):
        """Delete single image."""
        try:
            text_edit = self._get_multi_image_text_edit(param_name)
            if text_edit is None:
                return
            current_text = text_edit.toPlainText()
            if not current_text:
                return
            new_text = self._remove_path_from_multi_image_text(current_text, image_path)
            self._sync_multi_image_text_edit(text_edit, new_text)
            self._sync_multi_image_parameter_value(param_name, new_text, emit_signal=True)
            logger.info(f"已删除图片: {os.path.basename(image_path)}")
        except Exception as e:
            logger.error(f"删除图片失败: {e}", exc_info=True)

    def _get_multi_image_text_edit(self, param_name: str):
        text_edit = self.widgets.get(param_name)
        if isinstance(text_edit, QTextEdit):
            return text_edit
        return None

    def _remove_path_from_multi_image_text(self, current_text: str, image_path: str) -> str:
        all_paths = self._parse_image_paths(current_text)
        new_paths = [path for path in all_paths if path != image_path]
        if len(new_paths) == len(all_paths):
            image_filename = os.path.basename(image_path)
            new_paths = [path for path in all_paths if os.path.basename(path) != image_filename]
        if not new_paths:
            return ''
        return self._format_image_paths_display(new_paths)

    def _format_image_paths_display(self, file_paths):
        if not file_paths:
            return ""
        if len(file_paths) == 1:
            return file_paths[0]

        common_dir = self._get_multi_image_common_dir_for_display(file_paths)
        if common_dir and len(common_dir) > 20:
            formatted_lines = self._format_paths_with_common_dir(file_paths, common_dir)
        else:
            formatted_lines = self._format_paths_with_inline_directories(file_paths)
        return "\n".join(formatted_lines)

    def _format_existing_paths_display(self, paths_text):
        if not paths_text or not paths_text.strip():
            return ""
        return paths_text

    def _get_multi_image_common_dir_for_display(self, file_paths):
        try:
            if len(file_paths) > 1:
                return os.path.commonpath(file_paths)
        except ValueError:
            return ""
        return ""

    def _format_paths_with_common_dir(self, file_paths, common_dir):
        formatted_lines = [f"# 共同目录: {common_dir}"]
        for file_path in file_paths:
            formatted_lines.append(os.path.basename(file_path))
        return formatted_lines

    def _format_paths_with_inline_directories(self, file_paths):
        formatted_lines = []
        for file_path in file_paths:
            if len(file_path) > 60:
                filename = os.path.basename(file_path)
                formatted_lines.append(f"{filename}  # {os.path.dirname(file_path)}")
            else:
                formatted_lines.append(file_path)
        return formatted_lines

    def _parse_image_paths(self, paths_text: str) -> list:
        lines = self._split_multi_image_path_lines(paths_text)
        if not lines:
            return []

        resolver = self._create_multi_image_path_resolver()
        common_dir = None
        file_paths = []
        for line in lines:
            common_dir_candidate = self._extract_multi_image_common_dir(line)
            if common_dir_candidate is not None:
                common_dir = common_dir_candidate
                continue
            if self._is_multi_image_comment_line(line):
                continue

            full_path = self._convert_multi_image_line_to_full_path(line, common_dir)
            if not self._is_supported_multi_image_path(full_path):
                continue

            full_path = self._resolve_multi_image_full_path(full_path, line, resolver)
            file_paths.append(full_path)
        return file_paths

    def _convert_display_to_full_paths(self, display_text):
        lines = self._split_multi_image_path_lines(display_text)
        if not lines:
            return ""

        result_paths = []
        common_dir = None
        for line in lines:
            common_dir_candidate = self._extract_multi_image_common_dir(line)
            if common_dir_candidate is not None:
                common_dir = common_dir_candidate
                continue
            if self._is_multi_image_comment_line(line):
                continue
            full_path = self._convert_multi_image_line_to_full_path(line, common_dir)
            result_paths.append(full_path)
        return "\n".join(result_paths)

    _COMMON_DIR_PREFIXES = ("# 共同目录:", "#共同目录:")

    def _split_multi_image_path_lines(self, text):
        if not text or not text.strip():
            return []
        return [line.strip() for line in text.strip().split("\n") if line.strip()]

    def _extract_multi_image_common_dir(self, line):
        for prefix in self._COMMON_DIR_PREFIXES:
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip() if ":" in line else None
        return None

    def _is_multi_image_comment_line(self, line):
        return line.startswith("#")

    def _parse_multi_image_annotated_line(self, line):
        if "  # " not in line:
            return None, None
        filename, directory = line.split("  # ", 1)
        filename = filename.strip()
        directory = directory.strip()
        if not filename or not directory:
            return None, None
        return filename, directory

    def _convert_multi_image_line_to_full_path(self, line, common_dir):
        filename, directory = self._parse_multi_image_annotated_line(line)
        if filename and directory:
            return os.path.join(directory, filename)
        if os.path.isabs(line):
            return line
        if common_dir:
            return os.path.join(common_dir, line)
        return line

    def _is_supported_multi_image_path(self, full_path):
        return full_path.lower().endswith(
            (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp")
        )

    def _create_multi_image_path_resolver(self):
        try:
            from tasks.task_utils import get_image_path_resolver

            resolver = get_image_path_resolver()
            images_dir = getattr(self, "images_dir", None)
            if images_dir and os.path.exists(images_dir):
                resolver.add_search_path(images_dir, priority=0)
            return resolver
        except Exception:
            return None

    def _resolve_multi_image_full_path(self, full_path, original_line, resolver):
        if os.path.exists(full_path) or not resolver:
            return full_path
        resolved = resolver.resolve(full_path)
        if resolved:
            logger.debug(f"Resolved multi image path: {original_line} -> {resolved}")
            return resolved
        return full_path

    def _clear_and_update_display(self, text_edit):
        text_edit.clear()

    def _update_path_count_label(self, label, text_content):
        if not text_content or not text_content.strip():
            label.setText("")
            return

        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        valid_paths = [line for line in lines if not line.startswith('#')]
        count = len(valid_paths)
        if count == 0:
            label.setText("")
        elif count == 1:
            label.setText("1个文件")
        else:
            label.setText(f"{count}个文件")

    def _update_thumbnail_grid(self, param_name: str, paths_text: str):
        """更新缩略图网格显示"""
        try:
            container_key = f"{param_name}_thumbnail_container"
            if container_key not in self.widgets:
                return

            container = self.widgets[container_key]
            layout = container.layout()

            # 清除现有的缩略图
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

            file_paths = self._parse_image_paths(paths_text)

            if not file_paths:
                placeholder = QLabel('点击"选择多个图片..."添加图片')
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(placeholder)
                return

            # 使用网格布局来放置缩略图，支持多行
            grid_widget = QWidget()
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setSpacing(10)

            columns = 3
            for i, path in enumerate(file_paths):
                row = i // columns
                col = i % columns
                thumbnail = ThumbnailWidget(path, size=60)
                thumbnail.clicked.connect(self._show_image_viewer)
                thumbnail.delete_requested.connect(lambda p=path, name=param_name: self._delete_single_image(name, p))
                grid_layout.addWidget(thumbnail, row, col)

            layout.addWidget(grid_widget)
        except Exception as e:
            logger.error(f"更新缩略图网格失败: {e}", exc_info=True)

    def _clear_thumbnails(self, param_name: str, text_edit: QTextEdit):

        """清空缩略图和路径"""

        text_edit.setPlainText("")

        self.current_parameters[param_name] = ""  # 同步更新参数

        # 立即同步到 TaskCard

        if self.current_card_id is not None:

            self.parameters_changed.emit(self.current_card_id, {param_name: ""})

        self._update_thumbnail_grid(param_name, "")

    def _enable_browser_accessibility(self):
        """启用Chrome/Edge浏览器的UIAutomation辅助功能支持"""
        import winreg
        import os
        from PySide6.QtWidgets import QMessageBox

        try:
            success_count = 0

            # 常见浏览器快捷方式路径
            shortcut_paths = [
                os.path.expanduser(r"~\Desktop\Google Chrome.lnk"),
                os.path.expanduser(r"~\Desktop\Microsoft Edge.lnk"),
                r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk",
                r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Microsoft Edge.lnk",
            ]

            # 尝试修改快捷方式添加启动参数
            try:
                from utils.win32com_runtime import prepare_win32com_runtime
                prepare_win32com_runtime()
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")

                for shortcut_path in shortcut_paths:
                    if os.path.exists(shortcut_path):
                        try:
                            shortcut = shell.CreateShortCut(shortcut_path)
                            args = shortcut.Arguments or ""

                            if "--force-renderer-accessibility" not in args:
                                new_args = args + " --force-renderer-accessibility=complete"
                                shortcut.Arguments = new_args.strip()
                                shortcut.Save()
                                success_count += 1
                            else:
                                success_count += 1
                        except Exception:
                            pass
            except ImportError:
                pass

            # 同时设置注册表
            for browser_name, key_path in [
                ("Chrome", r"SOFTWARE\Google\Chrome\Accessibility"),
                ("Edge", r"SOFTWARE\Microsoft\Edge\Accessibility")
            ]:
                for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                    try:
                        key = winreg.CreateKeyEx(hive, key_path, 0, winreg.KEY_SET_VALUE)
                        winreg.SetValueEx(key, "AccessibilityMode", 0, winreg.REG_DWORD, 1)
                        winreg.CloseKey(key)
                        break
                    except Exception:
                        continue

            msg = "已尝试启用浏览器UIAutomation支持。\n\n"
            msg += "重要步骤:\n"
            msg += "1. 完全关闭浏览器（包括后台进程，可在任务管理器中结束）\n"
            msg += "2. 重新打开浏览器\n\n"
            msg += "如仍不生效，请手动在浏览器快捷方式目标后添加:\n"
            msg += "--force-renderer-accessibility=complete"

            QMessageBox.information(self, "设置完成", msg)

        except Exception as e:
            logger.error(f"启用浏览器辅助功能失败: {e}")
            QMessageBox.warning(
                self,
                "提示",
                "请手动在浏览器快捷方式目标后添加:\n"
                "--force-renderer-accessibility=complete\n\n"
                "然后完全关闭浏览器后重新打开。"
            )
