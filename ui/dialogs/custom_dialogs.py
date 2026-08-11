import sys
from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, 
                               QSpacerItem, QSizePolicy, QDialogButtonBox, QStyle, QWidget, QMessageBox, QTextEdit)
from PySide6.QtGui import QPixmap, QIcon, QPainter, QPen, QColor, QFont
from PySide6.QtCore import Qt, QSize
from typing import Optional # Use Optional for compatibility

from utils.log_message_translator import translate_log_message

class CustomMessageDialog(QDialog):
    """A custom dialog to replace QMessageBox, ensuring proper background rendering."""

    ICON_MAP = {
        'information': QStyle.StandardPixmap.SP_MessageBoxInformation,
        'warning': QStyle.StandardPixmap.SP_MessageBoxWarning,
        'critical': QStyle.StandardPixmap.SP_MessageBoxCritical,
        'question': QStyle.StandardPixmap.SP_MessageBoxQuestion,
    }

    def __init__(self, 
                 parent: QWidget = None, 
                 icon_type: str = 'information', 
                 title: str = "消息", 
                 text: str = "", 
                 standard_buttons: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.Ok,
                 default_button: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.NoButton):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint) 
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        # 保存文本内容，以便后续可以更新
        self._text = text
        self._informative_text = ""
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # 创建图标标签
        icon_label = QLabel()
        if icon_type == 'critical':
            # 使用自定义的红色圆形X图标
            icon_size = QSize(64, 64)
            pixmap = QPixmap(icon_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # 绘制红色圆形
            painter.setBrush(QColor("#D9452C"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(4, 4, 56, 56)
            
            # 绘制白色X
            painter.setPen(QPen(Qt.GlobalColor.white, 4))
            painter.drawLine(20, 20, 44, 44)
            painter.drawLine(44, 20, 20, 44)
            painter.end()
            
            icon_label.setPixmap(pixmap)
        else:
            # 其他类型的图标使用系统标准图标
            icon_pixmap = self._get_standard_icon(icon_type)
            if icon_pixmap:
                icon_label.setPixmap(icon_pixmap.scaled(QSize(48, 48), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        
        content_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # 文本区域的容器和标签
        self.text_container = QWidget()
        self.text_layout = QVBoxLayout(self.text_container)
        self.text_layout.setContentsMargins(0, 0, 0, 0)
        self.text_layout.setSpacing(8)
        
        # 主标题标签
        self.title_label = QLabel(text)
        self.title_label.setWordWrap(True)
        self.title_label.setObjectName("dialog_title_label")
        self.text_layout.addWidget(self.title_label)
        
        # 内容标签（初始可能为空）
        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setVisible(False)  # 默认隐藏，直到设置文本
        self.text_layout.addWidget(self.content_label)
                
        content_layout.addWidget(self.text_container, 1)
        main_layout.addLayout(content_layout)

        # 按钮区域
        self.button_box = QDialogButtonBox(standard_buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self._clicked_button = QDialogButtonBox.StandardButton.NoButton
        self.button_box.clicked.connect(self._on_button_clicked)

        # 设置标准按钮的中文文本
        button_text_map = {
            QDialogButtonBox.StandardButton.Yes: "是",
            QDialogButtonBox.StandardButton.No: "否",
            QDialogButtonBox.StandardButton.Ok: "确定",
            QDialogButtonBox.StandardButton.Cancel: "取消",
            QDialogButtonBox.StandardButton.Close: "关闭"
        }
        
        # 遍历所有按钮并设置中文文本
        for std_btn, text in button_text_map.items():
            btn = self.button_box.button(std_btn)
            if btn is not None:
                btn.setText(text)
                btn.setMinimumWidth(80)  # 设置最小宽度
        
        # 创建按钮容器并右对齐
        button_container_layout = QHBoxLayout()
        button_container_layout.addStretch(1)
        button_container_layout.addWidget(self.button_box)
        main_layout.addLayout(button_container_layout)

        # 对话框容器不设置硬编码样式，由主题控制

        self.setMinimumWidth(400)
        self.adjustSize()

    def _get_standard_icon(self, icon_type: str) -> Optional[QPixmap]:
        app = QApplication.instance()
        if app is None:
            return None
        style = app.style()
        standard_pixmap = self.ICON_MAP.get(icon_type.lower())
        if standard_pixmap:
            return style.standardIcon(standard_pixmap).pixmap(QSize(64, 64))
        return None

    def _on_button_clicked(self, button):
        """记录被点击的按钮"""
        self._clicked_button = self.button_box.standardButton(button)

    def clicked_button(self) -> QDialogButtonBox.StandardButton:
        # 优先使用记录的按钮
        if self._clicked_button != QDialogButtonBox.StandardButton.NoButton:
            return self._clicked_button

        # 根据对话框结果推断
        if self.result() == QDialog.DialogCode.Accepted:
            if QDialogButtonBox.StandardButton.Ok & self.button_box.standardButtons():
                return QDialogButtonBox.StandardButton.Ok
            elif QDialogButtonBox.StandardButton.Yes & self.button_box.standardButtons():
                return QDialogButtonBox.StandardButton.Yes
        elif self.result() == QDialog.DialogCode.Rejected:
            if QDialogButtonBox.StandardButton.No & self.button_box.standardButtons():
                return QDialogButtonBox.StandardButton.No
            elif QDialogButtonBox.StandardButton.Cancel & self.button_box.standardButtons():
                return QDialogButtonBox.StandardButton.Cancel
            elif QDialogButtonBox.StandardButton.Close & self.button_box.standardButtons():
                return QDialogButtonBox.StandardButton.Close

        return QDialogButtonBox.StandardButton.NoButton

    @staticmethod
    def show_message(parent: QWidget, icon_type: str, title: str, text: str, 
                     buttons: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.Ok,
                     default_button: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.NoButton) -> QDialogButtonBox.StandardButton:
        dialog = CustomMessageDialog(parent, icon_type, title, text, buttons, default_button)
        dialog.exec()
        return dialog.clicked_button()

    @staticmethod
    def information(parent: QWidget, title: str, text: str, 
                   buttons: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.Ok,
                   default_button: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.NoButton) -> QDialogButtonBox.StandardButton:
        return CustomMessageDialog.show_message(parent, 'information', title, text, buttons, default_button)

    @staticmethod
    def warning(parent: QWidget, title: str, text: str, 
                buttons: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.Ok,
                default_button: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.NoButton) -> QDialogButtonBox.StandardButton:
        return CustomMessageDialog.show_message(parent, 'warning', title, text, buttons, default_button)

    @staticmethod
    def critical(parent: QWidget, title: str, text: str, 
                 buttons: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.Ok,
                 default_button: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.NoButton) -> QDialogButtonBox.StandardButton:
        return CustomMessageDialog.show_message(parent, 'critical', title, text, buttons, default_button)

    @staticmethod
    def question(parent: QWidget, title: str, text: str, 
                 buttons: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No,
                 default_button: QDialogButtonBox.StandardButton = QDialogButtonBox.StandardButton.NoButton) -> QDialogButtonBox.StandardButton:
        return CustomMessageDialog.show_message(parent, 'question', title, text, buttons, default_button)

    def setInformativeText(self, text: str):
        """设置解释性文本"""
        self._informative_text = text
        self.content_label.setText(text)
        self.content_label.setVisible(bool(text))  # 只有当有文本时才显示
        self.adjustSize()
        
    def informativeText(self) -> str:
        """获取解释性文本"""
        return self._informative_text

class ErrorMessageBox:
    """
    自定义错误对话框，提供统一的错误显示格式和中文界面
    """
    
    @staticmethod
    def create_dialog(parent=None, title="错误", text="发生错误", 
                     informative_text=None, detailed_text=None,
                     icon_type='critical'):
        """创建一个自定义风格的错误对话框"""
        title = translate_log_message(title)
        text = translate_log_message(text)
        informative_text = translate_log_message(informative_text) if informative_text else informative_text
        detailed_text = translate_log_message(detailed_text) if detailed_text else detailed_text
        
        # 创建对话框
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.Dialog)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        # 主布局
        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 内容布局
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)
        
        # 图标
        icon_label = QLabel()
        
        # 创建红色圆形X图标（与截图一致）
        if icon_type == 'critical':
            icon_size = QSize(48, 48)
            pixmap = QPixmap(icon_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # 绘制红色圆形
            painter.setBrush(QColor("#E95439")) # 更暖的红色
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(4, 4, 40, 40)
            
            # 绘制白色X
            painter.setPen(QPen(Qt.GlobalColor.white, 3))
            painter.drawLine(16, 16, 36, 36)
            painter.drawLine(36, 16, 16, 36)
            painter.end()
            
            icon_label.setPixmap(pixmap)
        
        content_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        
        # 文本容器
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        
        # 标题
        title_label = QLabel(text)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPixelSize(16)
        title_label.setFont(title_font)
        title_label.setWordWrap(True)
        text_layout.addWidget(title_label)
        
        # 详细说明
        if informative_text:
            info_label = QLabel(informative_text)
            info_label.setWordWrap(True)
            text_layout.addWidget(info_label)
        
        content_layout.addWidget(text_container, 1)
        main_layout.addLayout(content_layout)
        
        # 详情文本区域（默认隐藏）
        details_text = QTextEdit(dialog)
        details_text.setReadOnly(True)
        details_text.setVisible(False)
        details_text.setFixedHeight(200)
        if detailed_text:
            details_text.setPlainText(detailed_text)
        main_layout.addWidget(details_text)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        
        # 创建确定按钮
        ok_button = QPushButton("确定")
        ok_button.setMinimumWidth(80)
        ok_button.clicked.connect(dialog.accept)
        
        # 如果有详细内容，添加显示详情按钮
        if detailed_text:
            details_button = QPushButton("显示详情...")
            details_button.setMinimumWidth(100)
            
            # 切换详情显示/隐藏
            details_visible = [False]  # 使用列表包装布尔值，以便在闭包中修改
            
            def toggle_details():
                details_visible[0] = not details_visible[0]
                details_text.setVisible(details_visible[0])
                details_button.setText("隐藏详情" if details_visible[0] else "显示详情...")
                # 让对话框大小适应内容变化
                dialog.adjustSize()
            
            details_button.clicked.connect(toggle_details)
            
            # 添加详情按钮和确定按钮
            button_layout.addWidget(details_button)
            button_layout.addWidget(ok_button)
        else:
            button_layout.addWidget(ok_button)
        
        main_layout.addLayout(button_layout)
        
        # 设置最小宽度，确保其与截图一致
        dialog.setMinimumWidth(400)
        
        # 不再使用硬编码样式，让全局主题控制对话框样式
        dialog.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                min-height: 25px;
            }
        """)
        
        return dialog
    
    @staticmethod
    def show_error(parent=None, title="错误", text="发生错误", 
                  informative_text=None, detailed_text=None):
        """显示错误对话框"""
        dialog = ErrorMessageBox.create_dialog(
            parent=parent,
            title=title,
            text=text,
            informative_text=informative_text,
            detailed_text=detailed_text,
            icon_type='critical'
        )
        return dialog.exec()
    
    @staticmethod
    def show_conflict_error(parent=None, message="发布任务失败：任务冲突"):
        """显示任务冲突错误"""
        return ErrorMessageBox.show_error(
            parent=parent,
            title="任务冲突",
            text="无法创建任务", 
            informative_text=message
        )
    
    @staticmethod
    def show_server_error(parent=None, detailed_error=None):
        """显示服务器错误"""
        return ErrorMessageBox.show_error(
            parent=parent,
            title="服务器错误",
            text="服务器处理请求时出错", 
            informative_text="服务器返回了错误响应，请检查服务器状态或稍后再试。"
        )

    @staticmethod
    def show_connection_error(parent=None, message="无法连接到任务服务器"):
        """显示连接错误对话框"""
        return ErrorMessageBox.show_error(
            parent=parent,
            title="连接失败",
            text="无法加载任务列表", 
            informative_text=message
        )

# 错误包装类，用于替换系统错误对话框确保使用中文显示
class ErrorWrapper:
    """错误包装类，替换系统错误对话框并使用中文显示所有错误消息"""
    
    ERROR_MAP = {
        "AttributeError": "属性错误",
        "ImportError": "导入错误",
        "ModuleNotFoundError": "模块缺失",
        "FileNotFoundError": "文件未找到",
        "KeyError": "键错误",
        "NameError": "名称错误", 
        "SyntaxError": "语法错误",
        "TypeError": "类型错误",
        "ValueError": "值错误",
        "RuntimeError": "运行时错误",
        "Exception": "异常"
    }
    
    @staticmethod
    def _map_error_name(error_type):
        """将异常类型名称映射为中文"""
        error_name = error_type.__name__ if hasattr(error_type, "__name__") else str(error_type)
        return ErrorWrapper.ERROR_MAP.get(error_name, f"错误({error_name})")
    
    @staticmethod
    def show_exception(parent=None, error=None, title=None, context="操作"):
        """显示异常错误对话框，将英文异常转换为中文显示"""
        # 检查是否有QApplication实例
        app_instance = QApplication.instance()
        if app_instance is None:
            # 如果没有QApplication实例，只记录错误，不显示对话框
            import logging
            if error is None:
                error_detail = "未知错误"
            else:
                error_detail = translate_log_message(str(error))
            logging.error(f"ErrorWrapper.show_exception: {context}时出现问题: {error_detail}")
            return

        if error is None:
            error_title = "未知错误"
            error_text = "发生了未知错误"
            error_detail = "无详细信息"
        else:
            error_type = type(error)
            error_title = title or ErrorWrapper._map_error_name(error_type)
            error_text = f"{context}时出现问题"
            error_detail = translate_log_message(str(error))

        return ErrorMessageBox.show_error(
            parent=parent,
            title=error_title,
            text=error_text,
            informative_text=error_detail
        )
