import unittest
from dataclasses import replace
from datetime import datetime, timezone

from passat_charge.scheduler import MAX_ATTEMPTS, PlanError, Scheduler, ZONE, next_midnight
from tests.helpers import Clock, Fixture


class SchedulerTests(Fixture, unittest.TestCase):
    def test_stop_then_start_only_at_midnight_and_confirm_measurement(self):
        plan = self.scheduler.arm()
        expected = datetime(2026, 10, 30, tzinfo=ZONE).timestamp()
        self.assertEqual(plan["due"], expected)
        self.scheduler.tick()
        self.assertEqual([c[0] for c in self.vehicle.calls], ["stop"])
        self.assertEqual(self.scheduler.latest()["state"], "confirm_stop")
        self.clock.advance(180)
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "scheduled")
        self.clock.now = plan["due"] - 1
        self.scheduler.tick()
        self.assertNotIn("start", [c[0] for c in self.vehicle.calls])
        self.clock.now = plan["due"]
        self.scheduler.tick()
        self.assertEqual(self.vehicle.calls[-1], ("start", plan["due"]))
        self.assertEqual(self.scheduler.latest()["state"], "confirm_start")
        self.clock.advance(180)
        self.vehicle.measure(charging=True)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "started")
        self.clock.advance(86400)
        self.scheduler.tick()
        self.assertEqual([a for a, _ in self.vehicle.calls], ["stop", "start"])

    def test_cancelling_never_resumes_or_starts(self):
        plan = self.paused_plan()
        self.scheduler.cancel(plan["id"])
        self.clock.now = plan["due"] + 300
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "cancelled")
        self.assertEqual([a for a, _ in self.vehicle.calls], ["stop"])

    def test_restart_preserves_plan(self):
        plan = self.paused_plan()
        self.scheduler = Scheduler(self.database, self.vehicle, self.clock)
        self.assertEqual(self.scheduler.latest()["id"], plan["id"])
        self.clock.now = plan["due"]
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        self.assertEqual(self.vehicle.calls[-1][0], "start")

    def test_restart_keeps_pending_stop(self):
        plan = self.scheduler.arm()
        self.scheduler = Scheduler(self.database, self.vehicle, self.clock)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["id"], plan["id"])
        self.assertEqual(self.vehicle.calls[-1][0], "stop")

    def test_missed_window_never_starts_next_day(self):
        plan = self.paused_plan()
        self.clock.now = plan["deadline"] + 1
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "expired")
        self.assertNotIn("start", [c[0] for c in self.vehicle.calls])

    def test_unconfirmed_stop_fails_and_cancels_automatic_start(self):
        plan = self.scheduler.arm()
        self.scheduler.tick()
        self.clock.advance(601)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "failed")
        self.clock.now = plan["due"]
        self.scheduler.tick()
        self.assertEqual([a for a, _ in self.vehicle.calls], ["stop"])

    def test_stale_data_cannot_confirm_start(self):
        plan = self.paused_plan()
        self.clock.now = plan["due"]
        self.scheduler.tick()
        # Old cached charging=True does not confirm a new start command.
        self.vehicle.snapshot = replace(self.vehicle.snapshot, charging=True)
        self.clock.advance(180)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "confirm_start")
        self.clock.advance(421)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "failed")

    def test_command_failures_have_bounded_retries(self):
        plan = self.paused_plan()
        self.clock.now = plan["due"]
        self.vehicle.command_error = True
        for _ in range(MAX_ATTEMPTS):
            self.scheduler.tick()
            self.clock.advance(180)
        self.assertEqual(self.scheduler.latest()["state"], "failed")
        self.assertEqual([a for a, _ in self.vehicle.calls].count("start"), MAX_ATTEMPTS)
        self.scheduler.tick()
        self.assertEqual([a for a, _ in self.vehicle.calls].count("start"), MAX_ATTEMPTS)

    def test_offline_start_is_retried_after_reconnection(self):
        plan = self.paused_plan()
        self.clock.now = plan["due"]
        self.vehicle.refresh_error = True
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "pending_start")
        self.assertNotIn("start", [c[0] for c in self.vehicle.calls])
        self.clock.advance(180)
        self.vehicle.refresh_error = False
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        self.assertEqual(self.vehicle.calls[-1][0], "start")

    def test_evening_plan_waits_for_midnight(self):
        self.clock = Clock("2026-10-29T20:30:00")
        self.scheduler.clock = self.clock
        self.vehicle.clock = self.clock
        self.vehicle.measure()
        self.scheduler.tick()
        plan = self.scheduler.arm()
        self.assertEqual(plan["due"], datetime(2026, 10, 30, tzinfo=ZONE).timestamp())
        self.scheduler.tick()
        self.assertEqual([a for a, _ in self.vehicle.calls], ["stop"])

    def test_new_plan_after_midnight_uses_the_following_midnight(self):
        self.clock = Clock("2026-10-30T00:30:00")
        self.scheduler.clock = self.clock
        self.vehicle.clock = self.clock
        self.vehicle.measure()
        self.scheduler.tick()
        plan = self.scheduler.arm()
        self.assertEqual(plan["due"], datetime(2026, 10, 31, tzinfo=ZONE).timestamp())
        self.scheduler.tick()
        self.assertEqual([a for a, _ in self.vehicle.calls], ["stop"])

    def test_duplicate_active_plan_rejected_including_new_process(self):
        self.scheduler.arm()
        other = Scheduler(self.database, self.vehicle, self.clock)
        other.tick()
        with self.assertRaises(PlanError):
            other.arm()

    def test_cancel_during_command_rejected_without_race(self):
        plan = self.scheduler.arm()
        with self.scheduler.lock:
            with self.assertRaises(PlanError):
                self.scheduler.cancel(plan["id"])
        self.assertEqual(self.scheduler.latest()["state"], "pending_stop")

    def test_rejects_wrong_id_and_stale_or_unplugged_status(self):
        for changes in ({"plugged": False}, {"plugged": None}, {"measured_at": self.clock() - 901},
                        {"measured_at": None}, {"measured_at": self.clock() + 61}):
            original = self.scheduler.snapshot
            self.scheduler.snapshot = replace(original, **changes)
            with self.assertRaises(PlanError):
                self.scheduler.arm()
            self.scheduler.snapshot = original
        self.scheduler.arm()
        with self.assertRaises(PlanError):
            self.scheduler.cancel("not-this-plan")

    def test_missing_credentials_never_send_commands(self):
        self.vehicle.configured = False
        with self.assertRaises(PlanError):
            self.scheduler.arm()
        self.scheduler.tick()
        self.assertEqual(self.vehicle.calls, [])

    def test_resumed_charging_before_midnight_requests_another_stop(self):
        self.paused_plan()
        self.clock.advance(180)
        self.vehicle.measure(charging=True)
        self.scheduler.tick()
        self.assertEqual([a for a, _ in self.vehicle.calls], ["stop", "stop"])
        self.assertEqual(self.scheduler.latest()["state"], "confirm_stop")

    def test_recovery_does_not_exceed_command_attempt_limit(self):
        self.scheduler.arm()
        plan = self.scheduler.latest()
        self.scheduler._update(plan, attempts=3)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.latest()["state"], "failed")
        self.assertEqual(self.vehicle.calls, [])


class TimezoneTests(unittest.TestCase):
    def test_midnight_in_winter_summer_and_dst_transition_days(self):
        cases = (
            ("2026-01-20T12:00", "2026-01-20T23:00+00:00"),
            ("2026-07-20T12:00", "2026-07-20T22:00+00:00"),
            ("2026-03-28T12:00", "2026-03-28T23:00+00:00"),
            ("2026-03-29T12:00", "2026-03-29T22:00+00:00"),
            ("2026-10-24T12:00", "2026-10-24T22:00+00:00"),
            ("2026-10-25T12:00", "2026-10-25T23:00+00:00"),
            ("2026-12-31T23:59:59", "2026-12-31T23:00+00:00"),
            ("2028-02-28T12:00", "2028-02-28T23:00+00:00"),
        )
        for local, expected_utc in cases:
            with self.subTest(local=local):
                now = datetime.fromisoformat(local).replace(tzinfo=ZONE).timestamp()
                due = datetime.fromtimestamp(next_midnight(now), timezone.utc)
                self.assertEqual(due, datetime.fromisoformat(expected_utc))
                self.assertEqual(due.astimezone(ZONE).hour, 0)
                self.assertGreater(due.timestamp(), now)

    def test_midnight_to_midnight_can_span_23_or_25_hours(self):
        for local, hours in (("2026-03-29T00:00", 23), ("2026-10-25T00:00", 25)):
            with self.subTest(local=local):
                now = datetime.fromisoformat(local).replace(tzinfo=ZONE).timestamp()
                self.assertEqual(next_midnight(now) - now, hours * 3600)


if __name__ == "__main__":
    unittest.main()
