class MainWindowExecutionPersistenceMixin:
    def _convert_status_message_to_user_friendly(self, status_message: str) -> str:
        text = str(status_message or "")
        if "STOP_WORKFLOW" in text:
            return "工作流执行已停止"
        if "用户手动停止" in text:
            return "工作流已被用户停止"
        if "正常停止" in text:
            return "工作流执行正常结束"
        if "执行完成" in text:
            return "工作流执行完成"
        if "执行成功" in text:
            return "工作流执行成功"
        if "执行失败" in text:
            return "工作流执行失败"
        if "错误" in text or "异常" in text:
            return f"工作流执行出现问题：{text}"
        return text
