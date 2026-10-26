def format_save_failure(
    stage: str, filepath: str, error: BaseException | str, *, file_written: bool = False,
) -> str:
    reason = str(error).strip() or "具体原因未知"
    details = [f"失败阶段：{stage}", f"目标路径：{filepath or '未指定'}"]
    if isinstance(error, BaseException):
        details.append(f"异常类型：{type(error).__name__}")
    details.append(f"具体原因：{reason}")
    if file_written:
        details.append("保存状态：工程文件已写入，但后续步骤未完成。")
    return "\n".join(details)
