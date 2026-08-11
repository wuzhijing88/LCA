"""多点坐标选择相关文案。"""

MULTI_COORDINATE_BUTTON_TEXT = "点击获取多个坐标"
MULTI_COORDINATE_PLACEHOLDER = "每行一个坐标: x,y\n如: 100,100"

MULTI_COORDINATE_EMPTY_HINT_LINES = (
    "左键逐点获取坐标",
    "右键撤销最后一个点",
    "按 ESC 完成坐标采集",
)

MULTI_COORDINATE_SELECTED_HINT_LINES = (
    "左键继续加点，右键撤销最后一个点",
    "按 ESC 完成坐标采集",
)


def format_multi_coordinate_selected_text(count: int) -> str:
    return f"已选择 {count} 个坐标点"
