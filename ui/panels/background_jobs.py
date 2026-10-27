"""参数面板后台读取任务；结果只投递给仍在存活的所属面板。"""
from threading import Event, Lock

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal, Slot, Qt


class _JobSignals(QObject):
    finished = Signal(str, int, object, object)
    progress = Signal(str, int, object)


class _CancellationState:
    def __init__(self):
        self.jobs = {}
        self.tasks = {}

    def cancel(self):
        for event in self.jobs.values():
            event.set()
        for task in self.tasks.values():
            task.work = None
        self.jobs.clear()
        self.tasks.clear()


_pool = None
_job_count = 0
_job_lock = Lock()


def reserve_background_job():
    global _job_count
    with _job_lock:
        if _job_count >= 512:
            raise RuntimeError("界面后台读取任务已达上限，请等待已有任务结束")
        _job_count += 1


def release_background_job():
    global _job_count
    with _job_lock:
        _job_count -= 1


def _job_pool():
    global _pool
    if _pool is None:
        _pool = QThreadPool(QCoreApplication.instance())
        _pool.setMaxThreadCount(2)
        _pool.setExpiryTimeout(1000)
    return _pool


class _PanelJob(QRunnable):
    def __init__(self, key, generation, work, cancelled, resource_dirs):
        super().__init__()
        reserve_background_job()
        self.key = key
        self.generation = generation
        self.work = work
        self.resource_dirs = resource_dirs
        self.cancelled = cancelled
        self.signals = _JobSignals(_job_pool())

    def _progress(self, value):
        if not self.cancelled.is_set():
            self.signals.progress.emit(self.key, self.generation, value)

    def run(self):
        from task_workflow.resource_context import bind_resource_dirs, current_resource_dirs
        previous_dirs = current_resource_dirs()
        try:
            bind_resource_dirs(self.resource_dirs)
            if self.cancelled.is_set():
                return
            result, error = None, None
            try:
                result = self.work(self.cancelled, self._progress)
            except Exception as exc:
                error = exc
            if not self.cancelled.is_set():
                self.signals.finished.emit(self.key, self.generation, result, error)
        finally:
            bind_resource_dirs(previous_dirs)
            self.work = None
            release_background_job()
            self.signals.deleteLater()


class PanelBackgroundJobs(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._state = _CancellationState()
        self._callbacks = {}
        self._generation = 0
        self.destroyed.connect(self._state.cancel)
        self.destroyed.connect(self._callbacks.clear)

    def submit(self, key, work, on_success, on_error, on_progress=None):
        self.cancel(key)
        if len(self._callbacks) >= 256:
            raise RuntimeError("参数面板后台任务过多")
        self._generation += 1
        generation = self._generation
        cancelled = Event()
        from task_workflow.resource_context import resource_dirs_from_mapping
        job = _PanelJob(key, generation, work, cancelled, resource_dirs_from_mapping(self.parent()))
        self._state.jobs[key] = cancelled
        self._state.tasks[key] = job
        self._callbacks[key] = (generation, on_success, on_error, on_progress)
        job.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        _job_pool().start(job)
        return cancelled

    def cancel(self, key):
        event = self._state.jobs.pop(key, None)
        if event is not None:
            event.set()
        task = self._state.tasks.pop(key, None)
        if task is not None:
            task.work = None
        self._callbacks.pop(key, None)

    def cancel_all(self):
        self._state.cancel()
        self._callbacks.clear()

    @Slot(str, int, object, object)
    def _finished(self, key, generation, result, error):
        callbacks = self._callbacks.get(key)
        if callbacks is None or callbacks[0] != generation:
            return
        self._state.jobs.pop(key, None)
        self._state.tasks.pop(key, None)
        self._callbacks.pop(key)
        callbacks[2](error) if error is not None else callbacks[1](result)

    @Slot(str, int, object)
    def _progress(self, key, generation, value):
        callbacks = self._callbacks.get(key)
        if callbacks is not None and callbacks[0] == generation and callbacks[3] is not None:
            callbacks[3](value)
