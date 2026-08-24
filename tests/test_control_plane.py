# -*- coding: utf-8 -*-
import unittest

from app_core.control_plane import (
    JobScheduler,
    JobState,
    aggregate_runner_states,
    can_transition,
    parse_job_state,
    pick_leading_runner_step,
    resolve_target_job_id,
    unwrap_assignment_record,
    wrap_assignment_record,
)


class JobStateMachineTests(unittest.TestCase):
    def test_pause_is_formal_state(self):
        self.assertTrue(can_transition(JobState.RUNNING, JobState.PAUSED))
        self.assertTrue(can_transition(JobState.PAUSED, JobState.RUNNING))
        self.assertTrue(can_transition(JobState.PAUSED, JobState.STOPPING))
        self.assertFalse(can_transition(JobState.READY, JobState.PAUSED))

    def test_aggregate_prefers_active_over_terminal(self):
        self.assertEqual(
            aggregate_runner_states([JobState.COMPLETED, JobState.RUNNING]),
            JobState.RUNNING,
        )
        self.assertEqual(
            aggregate_runner_states([JobState.PAUSED, JobState.PAUSED]),
            JobState.PAUSED,
        )
        self.assertEqual(
            aggregate_runner_states([JobState.COMPLETED, JobState.FAILED]),
            JobState.FAILED,
        )
        self.assertEqual(
            aggregate_runner_states([JobState.STOPPED, JobState.COMPLETED]),
            JobState.STOPPED,
        )
        self.assertEqual(
            aggregate_runner_states([JobState.STARTING, JobState.RUNNING]),
            JobState.RUNNING,
        )
        self.assertEqual(
            aggregate_runner_states([JobState.RUNNING, JobState.STARTING, JobState.COMPLETED]),
            JobState.RUNNING,
        )

    def test_leading_step_prefers_running_runner(self):
        self.assertEqual(
            pick_leading_runner_step(
                [
                    (JobState.STARTING, "正在启动工作流"),
                    (JobState.RUNNING, "点击登录"),
                    (JobState.PAUSED, "工作流已暂停"),
                ]
            ),
            "点击登录",
        )
        self.assertEqual(
            pick_leading_runner_step(
                [
                    (JobState.STARTING, "正在启动工作流"),
                    (JobState.PAUSED, "工作流已暂停"),
                ]
            ),
            "正在启动工作流",
        )

    def test_parse_aliases(self):
        self.assertEqual(parse_job_state("暂停中"), JobState.PAUSED)
        self.assertEqual(parse_job_state("已暂停"), JobState.PAUSED)
        self.assertEqual(parse_job_state("就绪"), JobState.READY)
        self.assertEqual(parse_job_state(JobState.RUNNING), JobState.RUNNING)


class JobSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = JobScheduler()
        self.window = {
            "title": "桌面",
            "hwnd": 65548,
            "bind_id": "bind-desktop",
        }
        self.scheduler.sync_targets([self.window])

    def test_job_id_is_bind_id_not_hwnd(self):
        job = self.scheduler.ensure_job(self.window)
        self.assertEqual(job.job_id, "bind-desktop")
        self.assertEqual(job.hwnd, 65548)
        self.assertEqual(resolve_target_job_id(self.window), "bind-desktop")

    def test_hwnd_change_keeps_assignments(self):
        view = self.scheduler.assignments_view()
        view["bind-desktop"] = [{"file_path": "a.json", "name": "A", "data": {"cards": []}}]
        self.assertEqual(self.scheduler.snapshot("bind-desktop").state, JobState.READY)

        self.window["hwnd"] = 70001
        self.scheduler.sync_targets([self.window])
        snapshot = self.scheduler.snapshot("bind-desktop")
        self.assertEqual(snapshot.hwnd, 70001)
        self.assertEqual(len(snapshot.assignments), 1)
        self.assertEqual(snapshot.assignments[0]["name"], "A")
        self.assertEqual(self.scheduler.resolve_job_id("70001"), "bind-desktop")
        self.assertEqual(self.scheduler.resolve_job_id("65548"), "bind-desktop")

        other = {"title": "游戏", "hwnd": 65548, "bind_id": "bind-game"}
        self.scheduler.sync_targets([self.window, other])
        self.assertEqual(self.scheduler.resolve_job_id("65548"), "bind-game")
        self.assertEqual(self.scheduler.resolve_job_id("70001"), "bind-desktop")

    def test_start_stop_pause_commands(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        denied = self.scheduler.request_start("bind-desktop")
        self.assertTrue(denied.ok)
        self.assertEqual(denied.state, JobState.IDLE)

        queued_again = self.scheduler.request_start("bind-desktop")
        self.assertTrue(queued_again.ok)
        self.assertEqual(queued_again.state, JobState.IDLE)

        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        again = self.scheduler.request_start("bind-desktop")
        self.assertFalse(again.ok)
        self.assertEqual(again.reason, "already_active")

        self.scheduler.apply_runner_state("bind-desktop", JobState.RUNNING)
        paused = self.scheduler.request_pause("bind-desktop")
        self.assertTrue(paused.ok)
        self.assertEqual(paused.state, JobState.PAUSED)

        resumed = self.scheduler.request_resume("bind-desktop")
        self.assertTrue(resumed.ok)
        self.assertEqual(resumed.state, JobState.RUNNING)

        stopped = self.scheduler.request_stop("bind-desktop")
        self.assertTrue(stopped.ok)
        self.assertEqual(stopped.state, JobState.STOPPING)

    def test_unassigned_cannot_start(self):
        result = self.scheduler.request_start("bind-desktop")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "unassigned")

    def test_matches_filter_uses_current_hwnd_lease(self):
        self.assertTrue(self.scheduler.matches_filter("bind-desktop", ["65548"]))
        self.assertTrue(self.scheduler.matches_filter("bind-desktop", ["bind-desktop"]))
        self.assertFalse(self.scheduler.matches_filter("bind-desktop", ["other"]))
        self.assertEqual(self.scheduler.canonicalize_ids(["65548", "bind-desktop"]), ["bind-desktop"])
        self.assertEqual(self.scheduler.canonicalize_ids(["65548"]), [])

    def test_status_text_does_not_force_stopping_over_stopped(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        self.scheduler.request_start("bind-desktop")
        self.scheduler.request_stop("bind-desktop")
        self.assertEqual(self.scheduler.snapshot("bind-desktop").state, JobState.STOPPED)

        snapshot = self.scheduler.apply_status_text("bind-desktop", "正在停止")
        self.assertEqual(snapshot.state, JobState.STOPPED)

    def test_apply_runner_states_keeps_job_running(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        self.scheduler.request_start("bind-desktop")
        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        self.scheduler.apply_runner_state("bind-desktop", JobState.RUNNING)
        snapshot = self.scheduler.apply_runner_states(
            "bind-desktop",
            [JobState.COMPLETED, JobState.RUNNING],
        )
        self.assertEqual(snapshot.state, JobState.RUNNING)

    def test_apply_runner_states_does_not_revive_stopping(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        self.scheduler.request_start("bind-desktop")
        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        self.scheduler.apply_runner_state("bind-desktop", JobState.RUNNING)
        self.scheduler.request_stop("bind-desktop")
        self.assertEqual(self.scheduler.snapshot("bind-desktop").state, JobState.STOPPING)
        snapshot = self.scheduler.apply_runner_states(
            "bind-desktop",
            [JobState.RUNNING, JobState.STARTING],
        )
        self.assertEqual(snapshot.state, JobState.STOPPING)

        self.scheduler.apply_runner_state("bind-desktop", JobState.STOPPED)
        snapshot = self.scheduler.apply_runner_states(
            "bind-desktop",
            [JobState.STARTING],
        )
        self.assertEqual(snapshot.state, JobState.STOPPED)

    def test_revert_unstarted_returns_to_ready(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        self.scheduler.request_start("bind-desktop")
        self.assertEqual(self.scheduler.snapshot("bind-desktop").state, JobState.IDLE)
        snapshot = self.scheduler.revert_unstarted("bind-desktop")
        self.assertEqual(snapshot.state, JobState.READY)

        self.scheduler.request_start("bind-desktop")
        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        snapshot = self.scheduler.revert_unstarted("bind-desktop")
        self.assertEqual(snapshot.state, JobState.READY)

        self.scheduler.request_start("bind-desktop")
        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        self.scheduler.apply_runner_state("bind-desktop", JobState.RUNNING)
        snapshot = self.scheduler.revert_unstarted("bind-desktop")
        self.assertEqual(snapshot.state, JobState.RUNNING)

    def test_finalize_orphaned_stop_clears_running_but_keeps_idle(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        self.scheduler.request_start("bind-desktop")
        self.assertEqual(self.scheduler.snapshot("bind-desktop").state, JobState.IDLE)
        snapshot = self.scheduler.finalize_orphaned_stop("bind-desktop")
        self.assertEqual(snapshot.state, JobState.IDLE)

        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        self.scheduler.apply_runner_state("bind-desktop", JobState.RUNNING)
        snapshot = self.scheduler.finalize_orphaned_stop("bind-desktop")
        self.assertEqual(snapshot.state, JobState.STOPPED)

    def test_finalize_orphaned_stop_leaves_stopped(self):
        self.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        self.scheduler.request_start("bind-desktop")
        self.scheduler.apply_runner_state("bind-desktop", JobState.STARTING)
        self.scheduler.apply_runner_state("bind-desktop", JobState.RUNNING)
        self.scheduler.request_stop("bind-desktop")
        self.assertEqual(self.scheduler.snapshot("bind-desktop").state, JobState.STOPPING)
        snapshot = self.scheduler.finalize_orphaned_stop("bind-desktop")
        self.assertEqual(snapshot.state, JobState.STOPPED)

    def test_assignment_record_requires_wrapped_format(self):
        record = wrap_assignment_record(
            self.window,
            [{"file_path": "a.json", "name": "A"}],
        )
        self.assertNotIn("hwnd", record)
        self.assertEqual(record["workflows"][0]["name"], "A")
        self.assertEqual(unwrap_assignment_record([{"file_path": "b.json", "name": "B"}])["workflows"], [])
        self.assertEqual(unwrap_assignment_record({"file_path": "c.json", "name": "C"})["workflows"], [])
        wrapped = unwrap_assignment_record(record)
        self.assertEqual(wrapped["workflows"][0]["file_path"], "a.json")

    def test_match_saved_key_requires_bind_id(self):
        self.assertEqual(self.scheduler.match_saved_key("bind-desktop"), "bind-desktop")
        self.assertEqual(self.scheduler.match_saved_key("missing-bind"), "")
        self.assertEqual(self.scheduler.match_saved_key("65548"), "")

    def test_assignment_view_dict_compat(self):
        view = self.scheduler.assignments_view()
        self.assertNotIn("bind-desktop", view)
        self.assertIsNone(view.get("bind-desktop"))
        view["bind-desktop"] = [{"file_path": "a.json", "name": "A"}]
        self.assertIn("bind-desktop", view)
        view["bind-desktop"].append({"file_path": "b.json", "name": "B"})
        self.assertEqual(len(self.scheduler.get_job("bind-desktop").assignments), 2)


if __name__ == "__main__":
    unittest.main()
