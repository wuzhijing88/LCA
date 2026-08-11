import logging
import threading

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class MainWindowScreenshotEngineMixin:
    def _schedule_runtime_screenshot_engine_switch(self, requested_engine: str):

        engine = str(requested_engine or "").strip().lower()

        if not engine:

            return

        with self._runtime_engine_switch_lock:

            self._runtime_engine_switch_target = engine

            if self._runtime_engine_switch_running:

                logger.info("截图引擎切换已在进行，已更新目标引擎为: %s", engine)

                return

            self._runtime_engine_switch_running = True

        def _worker():

            try:

                from utils.screenshot_helper import set_screenshot_engine, get_screenshot_engine

                while True:

                    with self._runtime_engine_switch_lock:

                        target_engine = str(self._runtime_engine_switch_target or "").strip().lower()

                        self._runtime_engine_switch_target = ""

                    if not target_engine:

                        break

                    try:

                        actual_engine = str(get_screenshot_engine() or "").strip().lower()

                        if target_engine and target_engine == actual_engine:

                            logger.info(f"截图引擎未变更，跳过切换: {actual_engine}")

                            continue

                        switch_ok = bool(set_screenshot_engine(target_engine))

                        actual_engine = str(get_screenshot_engine() or "").strip().lower()

                        if switch_ok and actual_engine == target_engine:

                            logger.info(f"截图引擎已切换到: {actual_engine}")

                        else:

                            logger.warning(

                                "截图引擎切换请求=%s, 实际=%s（目标引擎不可用或受限）",

                                target_engine,

                                actual_engine,

                            )

                    except Exception as exc:

                        logger.error(f"切换截图引擎失败: {exc}")

            finally:

                pending_target = ""

                with self._runtime_engine_switch_lock:

                    self._runtime_engine_switch_running = False

                    pending_target = str(self._runtime_engine_switch_target or "").strip().lower()

                if pending_target:

                    self._schedule_runtime_screenshot_engine_switch(pending_target)

        worker = threading.Thread(

            target=_worker,

            name="lca-runtime-screenshot-engine-switch",

            daemon=True,

        )

        self._runtime_engine_switch_thread = worker

        worker.start()

    def _schedule_startup_screenshot_engine_init(self, requested_engine: str):

        engine = str(requested_engine or "").strip().lower()

        if not engine:

            return

        if self._startup_engine_init_running:

            return

        self._startup_engine_init_target = engine

        self._startup_engine_init_running = True

        QTimer.singleShot(0, self, self._start_startup_screenshot_engine_init_worker)

    def _start_startup_screenshot_engine_init_worker(self):

        if self._startup_engine_init_thread and self._startup_engine_init_thread.is_alive():

            return

        requested_engine = str(self._startup_engine_init_target or "").strip().lower()

        if not requested_engine:

            self._startup_engine_init_running = False

            return

        def _worker():

            try:

                from utils.screenshot_helper import set_screenshot_engine, get_screenshot_engine

                switch_ok = bool(set_screenshot_engine(requested_engine))

                actual_engine = str(get_screenshot_engine() or "").strip().lower()

                if switch_ok and actual_engine == requested_engine:

                    logger.info(f"截图引擎已初始化: {actual_engine}")

                else:

                    logger.warning(

                        "截图引擎初始化请求=%s, 实际=%s（目标引擎不可用或受限）",

                        requested_engine,

                        actual_engine,

                    )

            except Exception as e:

                logger.error(f"初始化截图引擎失败: {e}")

            finally:

                self._startup_engine_init_running = False

        worker = threading.Thread(

            target=_worker,

            name="lca-screenshot-engine-init",

            daemon=True,

        )

        self._startup_engine_init_thread = worker

        worker.start()
