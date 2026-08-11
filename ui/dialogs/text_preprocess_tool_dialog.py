# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PySide6.QtCore import QSignalBlocker, QSize, Qt, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from themes import get_theme_manager

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

    MULTIMEDIA_AVAILABLE = True
except Exception:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QVideoSink = None  # type: ignore[assignment]
    MULTIMEDIA_AVAILABLE = False


VIDEO_EXTENSIONS = {
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wmv",
    ".flv",
    ".m4v",
    ".webm",
}


class TextPreprocessToolDialog(QDialog):
    """用于固定文字场景的视频/图片预处理调试工具。"""

    def __init__(self, parent=None, *, initial_path: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("文字预处理工具")
        self.setMinimumSize(1180, 760)
        self.resize(1320, 860)

        self._source_path = ""
        self._current_source_bgr: Optional[np.ndarray] = None
        self._processed_bgr: Optional[np.ndarray] = None
        self._processed_mask: Optional[np.ndarray] = None

        self._media_player = None
        self._video_sink = None
        self._audio_output = None
        self._duration_ms = 0

        self._source_path_edit = QLineEdit()
        self._source_path_edit.setReadOnly(True)
        self._source_type_label = QLabel("未加载")
        self._video_position_label = QLabel("00:00.000 / 00:00.000")
        self._video_slider = QSlider(Qt.Orientation.Horizontal)
        self._video_slider.setRange(0, 0)
        self._video_slider.setEnabled(False)
        self._play_pause_button = QPushButton("播放")
        self._play_pause_button.setEnabled(False)
        self._open_button = QPushButton("打开图片/视频")
        self._save_button = QPushButton("保存处理图")
        self._copy_color_button = QPushButton("复制颜色过滤")
        self._copy_summary_button = QPushButton("复制处理摘要")

        self._original_label = QLabel("原始画面")
        self._processed_label = QLabel("处理结果")
        self._original_image_label = self._create_preview_label()
        self._processed_image_label = self._create_preview_label()

        self._polarity_combo = QComboBox()
        self._polarity_combo.addItems(["自动判断", "亮字", "暗字"])
        self._threshold_combo = QComboBox()
        self._threshold_combo.addItems(["自动阈值(Otsu)", "固定阈值"])
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(0, 255)
        self._threshold_spin.setValue(160)
        self._threshold_spin.setEnabled(False)
        self._scale_spin = QSpinBox()
        self._scale_spin.setRange(100, 600)
        self._scale_spin.setValue(200)
        self._scale_spin.setSuffix("%")
        self._blur_spin = QSpinBox()
        self._blur_spin.setRange(0, 15)
        self._blur_spin.setSingleStep(2)
        self._blur_spin.setValue(3)
        self._morphology_combo = QComboBox()
        self._morphology_combo.addItems(["无", "开运算", "闭运算"])
        self._kernel_spin = QSpinBox()
        self._kernel_spin.setRange(1, 15)
        self._kernel_spin.setSingleStep(2)
        self._kernel_spin.setValue(3)
        self._min_area_spin = QSpinBox()
        self._min_area_spin.setRange(0, 100000)
        self._min_area_spin.setValue(12)
        self._invert_check = QCheckBox("结果反相")
        self._show_mask_check = QCheckBox("仅显示二值结果")
        self._show_mask_check.setChecked(True)

        self._recommended_color_edit = QLineEdit()
        self._recommended_color_edit.setReadOnly(True)
        self._recommended_bbox_edit = QLineEdit()
        self._recommended_bbox_edit.setReadOnly(True)
        self._component_summary = QTextEdit()
        self._component_summary.setReadOnly(True)
        self._component_summary.setMinimumHeight(180)

        self._build_ui()
        self._apply_styles()
        self._connect_signals()

        if initial_path:
            self.load_source(initial_path)

    @staticmethod
    def _create_preview_label() -> QLabel:
        label = QLabel()
        label.setObjectName("text_preprocess_preview")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(420, 300)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        label.setWordWrap(True)
        label.setText("等待加载")
        return label

    def _build_ui(self) -> None:
        self._video_slider.hide()
        self._play_pause_button.hide()
        self._video_position_label.hide()

        source_header_layout = QHBoxLayout()
        source_header_layout.setContentsMargins(0, 0, 0, 0)
        source_header_layout.setSpacing(8)
        source_header_layout.addWidget(QLabel("当前文件"))
        source_header_layout.addWidget(self._source_path_edit, 1)
        source_header_layout.addWidget(self._source_type_label)
        source_header_layout.addWidget(self._open_button)

        video_control_layout = QHBoxLayout()
        video_control_layout.setContentsMargins(0, 0, 0, 0)
        video_control_layout.setSpacing(8)
        video_control_layout.addWidget(self._play_pause_button)
        video_control_layout.addWidget(self._video_slider, 1)
        video_control_layout.addWidget(self._video_position_label)

        preview_grid = QGridLayout()
        preview_grid.setContentsMargins(0, 0, 0, 0)
        preview_grid.setSpacing(12)
        preview_grid.addWidget(self._original_label, 0, 0)
        preview_grid.addWidget(self._processed_label, 0, 1)
        preview_grid.addWidget(self._original_image_label, 1, 0)
        preview_grid.addWidget(self._processed_image_label, 1, 1)

        preview_frame = QFrame()
        preview_frame.setObjectName("text_preprocess_card")
        preview_frame.setLayout(preview_grid)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)
        form_layout.addRow("文字极性", self._polarity_combo)
        form_layout.addRow("阈值模式", self._threshold_combo)
        form_layout.addRow("固定阈值", self._threshold_spin)
        form_layout.addRow("放大比例", self._scale_spin)
        form_layout.addRow("模糊核", self._blur_spin)
        form_layout.addRow("形态处理", self._morphology_combo)
        form_layout.addRow("结构核大小", self._kernel_spin)
        form_layout.addRow("最小连通域", self._min_area_spin)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(12)
        checkbox_layout.addWidget(self._invert_check)
        checkbox_layout.addWidget(self._show_mask_check)
        checkbox_layout.addStretch()

        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(10)
        control_layout.addLayout(form_layout)
        control_layout.addLayout(checkbox_layout)
        control_layout.addStretch()
        control_layout.addWidget(self._save_button)
        control_layout.addWidget(self._copy_color_button)
        control_layout.addWidget(self._copy_summary_button)

        control_frame = QFrame()
        control_frame.setObjectName("text_preprocess_card")
        control_frame.setLayout(control_layout)
        control_frame.setFixedWidth(280)

        result_layout = QFormLayout()
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(10)
        result_layout.addRow("推荐颜色过滤", self._recommended_color_edit)
        result_layout.addRow("推荐文字包围框", self._recommended_bbox_edit)
        result_layout.addRow("处理摘要", self._component_summary)

        result_frame = QFrame()
        result_frame.setObjectName("text_preprocess_card")
        result_frame.setLayout(result_layout)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(preview_frame, 1)
        content_layout.addWidget(control_frame, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(source_header_layout)
        layout.addLayout(video_control_layout)
        layout.addLayout(content_layout, 1)
        layout.addWidget(result_frame, 0)

    def _apply_styles(self) -> None:
        theme_manager = get_theme_manager()
        background = theme_manager.get_color("background")
        card = theme_manager.get_color("card")
        surface = theme_manager.get_color("surface")
        border = theme_manager.get_color("border")
        border_light = theme_manager.get_color("border_light")
        text = theme_manager.get_color("text")
        text_secondary = theme_manager.get_color("text_secondary")
        hover = theme_manager.get_color("hover")

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {background};
                color: {text};
            }}
            QFrame#text_preprocess_card {{
                background-color: {card};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 10px;
            }}
            QLabel#text_preprocess_preview {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: 8px;
                color: {text_secondary};
            }}
            QLineEdit, QTextEdit, QComboBox, QSpinBox {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px;
                color: {text};
            }}
            QPushButton {{
                min-height: 34px;
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                border-color: {border_light};
                background-color: {hover};
            }}
            """
        )

    def _connect_signals(self) -> None:
        self._open_button.clicked.connect(self._choose_source_file)
        self._save_button.clicked.connect(self._save_processed_image)
        self._copy_color_button.clicked.connect(self._copy_recommended_color)
        self._copy_summary_button.clicked.connect(self._copy_summary_text)
        self._play_pause_button.clicked.connect(self._toggle_play_pause)
        self._video_slider.sliderReleased.connect(self._seek_video_from_slider)

        self._threshold_combo.currentIndexChanged.connect(self._handle_threshold_mode_changed)
        self._polarity_combo.currentIndexChanged.connect(self._apply_processing)
        self._threshold_spin.valueChanged.connect(self._apply_processing)
        self._scale_spin.valueChanged.connect(self._apply_processing)
        self._blur_spin.valueChanged.connect(self._apply_processing)
        self._morphology_combo.currentIndexChanged.connect(self._apply_processing)
        self._kernel_spin.valueChanged.connect(self._apply_processing)
        self._min_area_spin.valueChanged.connect(self._apply_processing)
        self._invert_check.checkStateChanged.connect(self._apply_processing)
        self._show_mask_check.checkStateChanged.connect(self._apply_processing)

    def _handle_threshold_mode_changed(self) -> None:
        use_fixed = self._threshold_combo.currentText() == "固定阈值"
        self._threshold_spin.setEnabled(use_fixed)
        self._apply_processing()

    def _choose_source_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片或视频",
            self._source_path or "",
            (
                "支持的媒体 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.mp4 *.avi *.mov *.mkv *.wmv *.flv *.m4v *.webm);;"
                "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;"
                "视频 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.m4v *.webm)"
            ),
        )
        if file_path:
            self.load_source(file_path)

    def load_source(self, source_path: str) -> None:
        normalized_path = os.path.abspath(str(source_path or "").strip())
        if not normalized_path or not os.path.exists(normalized_path):
            QMessageBox.warning(self, "文件不存在", f"未找到文件：\n{normalized_path}")
            return

        self._source_path = normalized_path
        self._source_path_edit.setText(normalized_path)

        file_ext = os.path.splitext(normalized_path)[1].lower()
        if file_ext in VIDEO_EXTENSIONS:
            self._load_video_source(normalized_path)
        else:
            self._load_image_source(normalized_path)

    def _load_image_source(self, image_path: str) -> None:
        self._teardown_media_player()
        self._source_type_label.setText("图片")
        self._video_slider.hide()
        self._play_pause_button.hide()
        self._video_position_label.hide()

        try:
            image = QImage(image_path)
            if image.isNull():
                raise ValueError("图片读取失败")
            self._current_source_bgr = self._qimage_to_bgr(image)
            self._update_preview_label(self._original_image_label, self._current_source_bgr)
            self._apply_processing()
        except Exception as exc:
            QMessageBox.critical(self, "加载失败", f"图片加载失败：{exc}")

    def _load_video_source(self, video_path: str) -> None:
        if not MULTIMEDIA_AVAILABLE:
            QMessageBox.warning(
                self,
                "缺少多媒体组件",
                "当前环境未启用 Qt 多媒体模块，暂时无法直接加载视频。\n你仍然可以先把视频截帧后再用本工具处理图片。",
            )
            return

        self._teardown_media_player()
        self._source_type_label.setText("视频")
        self._video_slider.show()
        self._play_pause_button.show()
        self._video_position_label.show()
        self._play_pause_button.setText("播放")
        self._play_pause_button.setEnabled(True)
        self._video_slider.setEnabled(True)

        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setMuted(True)
        self._media_player.setAudioOutput(self._audio_output)
        self._video_sink = QVideoSink(self)
        self._media_player.setVideoSink(self._video_sink)

        self._media_player.durationChanged.connect(self._handle_duration_changed)
        self._media_player.mediaStatusChanged.connect(self._handle_media_status_changed)
        self._media_player.positionChanged.connect(self._handle_position_changed)
        self._video_sink.videoFrameChanged.connect(self._handle_video_frame_changed)

        self._media_player.setSource(QUrl.fromLocalFile(video_path))
        self._media_player.pause()

    def _teardown_media_player(self) -> None:
        if self._media_player is not None:
            try:
                self._media_player.stop()
            except Exception:
                pass
            self._media_player.deleteLater()
            self._media_player = None
        if self._video_sink is not None:
            try:
                self._video_sink.deleteLater()
            except Exception:
                pass
            self._video_sink = None
        if self._audio_output is not None:
            try:
                self._audio_output.deleteLater()
            except Exception:
                pass
            self._audio_output = None
        self._duration_ms = 0
        with QSignalBlocker(self._video_slider):
            self._video_slider.setRange(0, 0)
            self._video_slider.setValue(0)
        self._video_slider.setEnabled(False)

    def _toggle_play_pause(self) -> None:
        if self._media_player is None:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            self._play_pause_button.setText("播放")
        else:
            self._media_player.play()
            self._play_pause_button.setText("暂停")

    def _seek_video_from_slider(self) -> None:
        if self._media_player is None:
            return
        self._media_player.setPosition(int(self._video_slider.value()))

    def _handle_duration_changed(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        with QSignalBlocker(self._video_slider):
            self._video_slider.setRange(0, self._duration_ms)
        self._update_video_position_label(int(self._video_slider.value()))

    def _handle_position_changed(self, position_ms: int) -> None:
        with QSignalBlocker(self._video_slider):
            self._video_slider.setValue(max(0, int(position_ms)))
        self._update_video_position_label(position_ms)

    def _handle_media_status_changed(self, status) -> None:
        if self._media_player is None:
            return
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._media_player.setPosition(0)

    def _handle_video_frame_changed(self, frame) -> None:
        try:
            image = frame.toImage()
            if image.isNull():
                return
            self._current_source_bgr = self._qimage_to_bgr(image)
            self._update_preview_label(self._original_image_label, self._current_source_bgr)
            self._apply_processing()
        except Exception as exc:
            self._component_summary.setPlainText(f"视频帧转换失败：{exc}")

    def _update_video_position_label(self, position_ms: int) -> None:
        self._video_position_label.setText(
            f"{self._format_ms(position_ms)} / {self._format_ms(self._duration_ms)}"
        )

    @staticmethod
    def _format_ms(value_ms: int) -> str:
        total_ms = max(0, int(value_ms))
        minutes, remainder = divmod(total_ms, 60000)
        seconds, ms = divmod(remainder, 1000)
        return f"{minutes:02d}:{seconds:02d}.{ms:03d}"

    def _apply_processing(self) -> None:
        if self._current_source_bgr is None:
            self._processed_bgr = None
            self._processed_mask = None
            self._processed_image_label.setText("等待加载")
            self._recommended_color_edit.clear()
            self._recommended_bbox_edit.clear()
            self._component_summary.clear()
            return

        try:
            import cv2
            from tasks.dict_ocr_task import _analyze_dict_ocr_hints_from_image
        except Exception as exc:
            self._component_summary.setPlainText(f"当前环境缺少预处理依赖，无法实时处理：{exc}")
            return

        source_bgr = self._current_source_bgr.copy()
        scale_ratio = max(1.0, float(self._scale_spin.value()) / 100.0)
        if abs(scale_ratio - 1.0) > 1e-6:
            source_bgr = cv2.resize(
                source_bgr,
                None,
                fx=scale_ratio,
                fy=scale_ratio,
                interpolation=cv2.INTER_CUBIC,
            )

        gray = cv2.cvtColor(source_bgr, cv2.COLOR_BGR2GRAY)
        blur_value = int(self._blur_spin.value())
        if blur_value > 0:
            if blur_value % 2 == 0:
                blur_value += 1
            gray = cv2.GaussianBlur(gray, (blur_value, blur_value), 0)

        threshold_mode = self._threshold_combo.currentText()
        polarity_mode = self._polarity_combo.currentText()
        morphology_mode = self._morphology_combo.currentText()
        kernel_size = max(1, int(self._kernel_spin.value()))
        if kernel_size % 2 == 0:
            kernel_size += 1
        min_area = max(0, int(self._min_area_spin.value()))

        best_mask, polarity_text, threshold_text, component_stats = self._build_best_mask(
            gray,
            threshold_mode=threshold_mode,
            polarity_mode=polarity_mode,
            fixed_threshold=int(self._threshold_spin.value()),
            min_area=min_area,
            morphology_mode=morphology_mode,
            kernel_size=kernel_size,
        )

        if self._invert_check.isChecked():
            best_mask = cv2.bitwise_not(best_mask)

        self._processed_mask = best_mask
        if self._show_mask_check.isChecked():
            display_bgr = cv2.cvtColor(best_mask, cv2.COLOR_GRAY2BGR)
        else:
            display_bgr = cv2.bitwise_and(source_bgr, source_bgr, mask=best_mask)
        self._processed_bgr = display_bgr
        self._update_preview_label(self._processed_image_label, display_bgr)

        derived_color, derived_bbox, component_metrics = _analyze_dict_ocr_hints_from_image(source_bgr)
        self._recommended_color_edit.setText(derived_color or "")
        if derived_bbox:
            self._recommended_bbox_edit.setText(
                f"X1={derived_bbox[0]}, Y1={derived_bbox[1]}, X2={derived_bbox[2]}, Y2={derived_bbox[3]}"
            )
        else:
            self._recommended_bbox_edit.clear()

        summary_lines = [
            f"当前来源: {self._source_path or '未加载'}",
            f"放大比例: {self._scale_spin.value()}%",
            f"阈值模式: {threshold_mode}",
            f"文字极性: {polarity_text}",
            f"最终阈值: {threshold_text}",
            f"形态处理: {morphology_mode}",
            f"最小连通域: {min_area}",
            f"前景像素占比: {component_stats.get('foreground_ratio', 0.0):.4f}",
            f"连通域数量: {component_stats.get('component_count', 0)}",
        ]
        if component_metrics:
            summary_lines.extend(
                [
                    f"平均字宽: {component_metrics.get('avg_width', 0.0):.2f}",
                    f"平均字高: {component_metrics.get('avg_height', 0.0):.2f}",
                    f"平均宽高比: {component_metrics.get('avg_aspect', 0.0):.2f}",
                ]
            )
        if derived_color:
            summary_lines.append(f"推荐颜色过滤: {derived_color}")
        self._component_summary.setPlainText("\n".join(summary_lines))

    def _build_best_mask(
        self,
        gray: np.ndarray,
        *,
        threshold_mode: str,
        polarity_mode: str,
        fixed_threshold: int,
        min_area: int,
        morphology_mode: str,
        kernel_size: int,
    ) -> Tuple[np.ndarray, str, str, Dict[str, float]]:
        import cv2

        polarity_candidates = []
        if polarity_mode == "亮字":
            polarity_candidates = [("亮字", cv2.THRESH_BINARY)]
        elif polarity_mode == "暗字":
            polarity_candidates = [("暗字", cv2.THRESH_BINARY_INV)]
        else:
            polarity_candidates = [("亮字", cv2.THRESH_BINARY), ("暗字", cv2.THRESH_BINARY_INV)]

        best_candidate = None
        for candidate_name, threshold_flag in polarity_candidates:
            if threshold_mode == "固定阈值":
                threshold_value = int(fixed_threshold)
                _, mask = cv2.threshold(gray, threshold_value, 255, threshold_flag)
                threshold_text = str(threshold_value)
            else:
                threshold_value, mask = cv2.threshold(
                    gray,
                    0,
                    255,
                    threshold_flag | cv2.THRESH_OTSU,
                )
                threshold_text = f"Otsu={int(threshold_value)}"

            mask = self._apply_mask_postprocess(
                mask,
                min_area=min_area,
                morphology_mode=morphology_mode,
                kernel_size=kernel_size,
            )
            stats = self._calculate_mask_stats(mask)
            score = stats["component_count"] * 4.0 + min(stats["foreground_ratio"] * 120.0, 20.0)
            if best_candidate is None or score > best_candidate[0]:
                best_candidate = (score, mask, candidate_name, threshold_text, stats)

        assert best_candidate is not None
        return best_candidate[1], best_candidate[2], best_candidate[3], best_candidate[4]

    @staticmethod
    def _apply_mask_postprocess(
        mask: np.ndarray,
        *,
        min_area: int,
        morphology_mode: str,
        kernel_size: int,
    ) -> np.ndarray:
        import cv2

        processed = mask.copy()
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        if morphology_mode == "开运算":
            processed = cv2.morphologyEx(processed, cv2.MORPH_OPEN, kernel)
        elif morphology_mode == "闭运算":
            processed = cv2.morphologyEx(processed, cv2.MORPH_CLOSE, kernel)

        if min_area <= 0:
            return processed

        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(processed, 8)
        filtered = np.zeros_like(processed)
        for component_index in range(1, component_count):
            area = int(stats[component_index, cv2.CC_STAT_AREA])
            if area >= min_area:
                filtered[labels == component_index] = 255
        return filtered

    @staticmethod
    def _calculate_mask_stats(mask: np.ndarray) -> Dict[str, float]:
        import cv2

        foreground_pixels = int(np.count_nonzero(mask))
        total_pixels = int(mask.size) if mask.size else 1
        component_count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        valid_components = 0
        for component_index in range(1, component_count):
            if int(stats[component_index, cv2.CC_STAT_AREA]) > 0:
                valid_components += 1
        return {
            "foreground_ratio": float(foreground_pixels / max(total_pixels, 1)),
            "component_count": float(valid_components),
        }

    def _save_processed_image(self) -> None:
        if self._processed_bgr is None:
            QMessageBox.information(self, "没有可保存内容", "请先加载图片或视频并完成处理。")
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存处理图",
            os.path.join(os.path.dirname(self._source_path or ""), "processed_preview.png"),
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not output_path:
            return

        try:
            import cv2

            if not cv2.imwrite(output_path, self._processed_bgr):
                raise ValueError("cv2.imwrite 返回失败")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"处理图保存失败：{exc}")

    def _copy_recommended_color(self) -> None:
        color_text = self._recommended_color_edit.text().strip()
        if not color_text:
            QMessageBox.information(self, "没有可复制内容", "当前还没有推导出推荐颜色过滤。")
            return
        QApplication.clipboard().setText(color_text)

    def _copy_summary_text(self) -> None:
        summary_text = self._component_summary.toPlainText().strip()
        if not summary_text:
            QMessageBox.information(self, "没有可复制内容", "当前还没有处理摘要。")
            return
        QApplication.clipboard().setText(summary_text)

    def _update_preview_label(self, label: QLabel, bgr_image: Optional[np.ndarray]) -> None:
        if bgr_image is None or getattr(bgr_image, "size", 0) == 0:
            label.setPixmap(QPixmap())
            label.setText("无图像")
            return

        image = self._bgr_to_qimage(bgr_image)
        pixmap = QPixmap.fromImage(image)
        scaled_pixmap = pixmap.scaled(
            label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled_pixmap)
        label.setText("")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview_label(self._original_image_label, self._current_source_bgr)
        self._update_preview_label(self._processed_image_label, self._processed_bgr)

    @staticmethod
    def _qimage_to_bgr(image: QImage) -> np.ndarray:
        converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width = converted.width()
        height = converted.height()
        bits = converted.bits()
        array = np.frombuffer(bits, dtype=np.uint8).reshape((height, width, 4)).copy()
        return array[:, :, :3][:, :, ::-1]

    @staticmethod
    def _bgr_to_qimage(bgr_image: np.ndarray) -> QImage:
        rgb_image = np.ascontiguousarray(bgr_image[:, :, ::-1])
        height, width = rgb_image.shape[:2]
        bytes_per_line = int(rgb_image.strides[0])
        return QImage(
            rgb_image.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        ).copy()
