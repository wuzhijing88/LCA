from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                               QWidget, QTextEdit)
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont
from PySide6.QtCore import Qt, QSize

from utils.log_message_translator import translate_log_message


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
