# -*- coding: utf-8 -*-
"""测试会话级共享配置。

统一在会话开始时创建 QApplication，避免测试顺序问题：
若某个仅需 QCoreApplication 的测试先运行并创建了非 GUI 应用实例，
后续需要 QWidget 的测试将无法再创建 QApplication，进程会直接崩溃。
"""

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
