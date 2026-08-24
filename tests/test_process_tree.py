from unittest import mock

from app_core.runtime import process_tree


class _Process:
    def __init__(self, pid=123, returncode=None):
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout):
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_already_stopped_process_is_not_terminated():
    process = _Process(returncode=7)

    result = process_tree.terminate_process_tree(process)

    assert result.already_stopped
    assert result.returncode == 7


def test_windows_force_stop_uses_single_taskkill_policy():
    process = _Process()
    completed = mock.Mock(returncode=0)

    with mock.patch.object(process_tree.os, "name", "nt"), mock.patch.object(
        process_tree.subprocess,
        "run",
        return_value=completed,
    ) as run:
        result = process_tree.terminate_process_tree(process)

    assert result.forced
    run.assert_called_once()
    assert run.call_args.args[0][:3] == ["taskkill", "/PID", "123"]
