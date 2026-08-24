"""Compatibility wrapper for the unified custom dropdown implementation."""

from ..widgets.custom_widgets import CustomDropdown


QComboBox = CustomDropdown

__all__ = ["CustomDropdown", "QComboBox"]
