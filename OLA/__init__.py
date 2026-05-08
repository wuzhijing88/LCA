# -*- coding: utf-8 -*-
"""
OLA (欧拉) SDK 包
用于RPA自动化操作的插件SDK
"""

# 导出主要类供外部使用
try:
    from .OLAPlugServer import OLAPlugServer
    from .OLAPlugDLLHelper import OLAPlugDLLHelper

    __all__ = ['OLAPlugServer', 'OLAPlugDLLHelper']
except ImportError:
    # 在某些环境下可能无法导入,忽略错误
    pass

__version__ = '1.0.0-beta.67'
