from enum import Enum


class TaskState(Enum):
    """任务状态枚举"""
    IDLE = "等待开始"
    STARTING = "正在启动"
    RUNNING = "正在运行"
    STOPPING = "正在停止"
    STOPPED = "已中断"
    COMPLETED = "已完成"
    FAILED = "执行失败"
