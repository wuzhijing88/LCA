import unittest
from unittest import mock

from services import worker_process_cleanup


class _FakeProcess:
    def __init__(self, pid, returncode=None):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


class WorkerProcessCleanupTests(unittest.TestCase):
    def setUp(self):
        with worker_process_cleanup._REGISTRY_LOCK:
            worker_process_cleanup._REGISTERED_WORKERS.clear()

    def tearDown(self):
        with worker_process_cleanup._REGISTRY_LOCK:
            worker_process_cleanup._REGISTERED_WORKERS.clear()

    def test_cleanup_terminates_only_registered_matching_workers(self):
        ocr_process = _FakeProcess(901)
        match_process = _FakeProcess(902)
        worker_process_cleanup.register_worker_process(ocr_process, "--ocr-worker")
        worker_process_cleanup.register_worker_process(match_process, "--match-worker")

        with mock.patch(
            "services.worker_process_cleanup._kill_registered_process",
            return_value=True,
        ) as kill_mock:
            cleaned = worker_process_cleanup.cleanup_worker_processes(("--ocr-worker",))

        self.assertEqual(cleaned, 1)
        self.assertEqual(kill_mock.call_count, 1)
        self.assertEqual(kill_mock.call_args.args[0].pid, 901)
        self.assertEqual(
            worker_process_cleanup.get_registered_worker_pids(("--match-worker",)),
            (902,),
        )

    def test_duplicate_pid_registration_is_rejected(self):
        worker_process_cleanup.register_worker_process(_FakeProcess(903), "--ocr-worker")

        with self.assertRaises(RuntimeError):
            worker_process_cleanup.register_worker_process(_FakeProcess(903), "--ocr-worker")

    def test_failed_cleanup_keeps_registration_and_raises(self):
        worker_process_cleanup.register_worker_process(_FakeProcess(904), "--ocr-worker")

        with mock.patch(
            "services.worker_process_cleanup._kill_registered_process",
            return_value=False,
        ):
            with self.assertRaises(worker_process_cleanup.WorkerProcessCleanupError) as raised:
                worker_process_cleanup.cleanup_worker_processes(("--ocr-worker",))

        self.assertEqual(raised.exception.failed_pids, (904,))
        self.assertEqual(
            worker_process_cleanup.get_registered_worker_pids(("--ocr-worker",)),
            (904,),
        )

    def test_unregister_reports_whether_process_was_registered(self):
        process = _FakeProcess(905)
        worker_process_cleanup.register_worker_process(process, "--ocr-worker")

        self.assertTrue(worker_process_cleanup.unregister_worker_process(process))
        self.assertFalse(worker_process_cleanup.unregister_worker_process(905))

    def test_invalid_or_duplicate_flags_are_rejected(self):
        with self.assertRaises(ValueError):
            worker_process_cleanup.cleanup_worker_processes(())
        with self.assertRaises(ValueError):
            worker_process_cleanup.cleanup_worker_processes(
                ("--ocr-worker", "--OCR-WORKER")
            )

    def test_cleanup_all_registered_workers_covers_every_worker_type(self):
        worker_process_cleanup.register_worker_process(_FakeProcess(906), "--ocr-worker")
        worker_process_cleanup.register_worker_process(_FakeProcess(907), "--workflow-worker")

        with mock.patch(
            "services.worker_process_cleanup._kill_registered_process",
            return_value=True,
        ) as kill_mock:
            cleaned = worker_process_cleanup.cleanup_all_registered_worker_processes()

        self.assertEqual(cleaned, 2)
        self.assertEqual(
            {call.args[0].pid for call in kill_mock.call_args_list},
            {906, 907},
        )


if __name__ == "__main__":
    unittest.main()
