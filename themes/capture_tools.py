"""截图、框选、取色按钮的统一主题属性。"""
def apply_capture_action_buttons(confirm, secondary):
    for button, role in ((confirm, 'primary'), (secondary, 'secondary')):
        button.setProperty('captureAction', role)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()
