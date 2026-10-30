import json
import threading
import unittest
from unittest.mock import Mock, patch

from passat_charge.cloud import Busy, CloudScheduler, CloudWorker, LEASE_SECONDS
from passat_charge.cloud_runtime import create_worker_app, verify_caller
from passat_charge.cloud_store import TaskQueue
from passat_charge.scheduler import PlanError
from passat_charge.web import create_app
from tests.cloud_helpers import CloudFixture


class CloudTests(CloudFixture, unittest.TestCase):
    def test_cold_worker_starts_only_at_selected_time_and_confirms(self):
        plan = self.paused_plan()
        self.assertEqual(self.store.read()["plan"]["state"], "scheduled")
        self.assertLessEqual(self.store.read()["outbox"]["due"], plan["due"])
        self.clock.now = plan["due"] - 1
        self.step()
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])
        self.clock.now = plan["due"]
        self.step()
        self.assertEqual(self.vehicle.calls[-1], ("start", plan["due"]))
        self.clock.advance(180)
        self.vehicle.measure(charging=True)
        self.step()
        self.assertEqual(self.store.read()["plan"]["state"], "started")
        self.assertIsNone(self.store.read()["outbox"])

    def test_delayed_duplicate_and_cancelled_tasks_cannot_start(self):
        plan = self.paused_plan()
        task_id = self.store.read()["outbox"]["id"]
        self.scheduler.cancel(plan["id"])
        self.clock.now = plan["due"] + 1
        self.step(task_id)
        self.step(task_id)
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])
        self.assertEqual(self.store.read()["plan"]["state"], "cancelled")

    def test_completed_task_redelivery_does_not_repeat_command(self):
        self.scheduler.arm()
        task_id = self.store.read()["outbox"]["id"]
        self.step(task_id)
        self.step(task_id)
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])

    def test_duplicate_worker_and_cancel_are_rejected_during_execution(self):
        plan = self.scheduler.arm()
        task_id = self.store.read()["outbox"]["id"]
        entered, release = threading.Event(), threading.Event()
        original = self.vehicle.refresh
        errors = []
        def refresh():
            entered.set()
            release.wait(5)
            return original()
        self.vehicle.refresh = refresh
        def run():
            try:
                self.step(task_id)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(Busy):
                self.step(task_id)
            with self.assertRaises(PlanError):
                self.scheduler.cancel(plan["id"])
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])

    def test_queue_outage_keeps_outbox_and_recovery_publishes_it(self):
        self.queue.fail = True
        with self.assertRaises(PlanError):
            self.scheduler.arm()
        saved = self.store.read()
        self.assertIsNone(saved["outbox"]["published_at"])
        self.assertEqual(saved["plan"]["state"], "pending_stop")
        self.queue.fail = False
        CloudScheduler(self.store, self.queue, self.clock).reconcile()
        self.assertIsNotNone(self.store.read()["outbox"]["published_at"])
        self.step()
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])

    def test_recovery_replaces_lost_task_and_old_delivery_is_harmless(self):
        self.scheduler.arm()
        old = self.store.read()["outbox"]["id"]
        self.clock.advance(601)
        self.scheduler.reconcile()
        new = self.store.read()["outbox"]["id"]
        self.assertNotEqual(old, new)
        self.step(old)
        self.assertEqual(self.vehicle.calls, [])
        self.step(new)
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])

    def test_crash_after_command_intent_recovers_after_lease(self):
        self.scheduler.arm()
        original = self.vehicle.command
        def crash(action):
            original(action)
            raise RuntimeError("test-only process crash")
        self.vehicle.command = crash
        task_id = self.store.read()["outbox"]["id"]
        with self.assertRaises(RuntimeError):
            self.step(task_id)
        self.assertEqual(self.store.read()["plan"]["attempts"], 1)
        self.clock.advance(LEASE_SECONDS + 1)
        self.vehicle.command = original
        self.step(task_id)
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop", "stop"])

    def test_expired_lease_cannot_issue_vehicle_command(self):
        self.scheduler.arm()
        original = self.vehicle.refresh
        def slow():
            self.clock.advance(LEASE_SECONDS + 1)
            return original()
        self.vehicle.refresh = slow
        from passat_charge.cloud import LeaseLost
        with self.assertRaises(LeaseLost):
            self.step()
        self.assertEqual(self.vehicle.calls, [])

    def test_expired_plan_is_not_started(self):
        plan = self.paused_plan()
        self.clock.now = plan["deadline"] + 1
        self.step()
        self.assertEqual(self.store.read()["plan"]["state"], "expired")
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])

    def test_recovery_expires_plan_even_when_vehicle_worker_cannot_start(self):
        plan = self.scheduler.arm()
        self.clock.now = plan["deadline"] + 1
        self.scheduler.reconcile()
        self.assertEqual(self.store.read()["plan"]["state"], "expired")
        self.assertIsNone(self.store.read()["outbox"])
        self.assertEqual(self.vehicle.calls, [])

    def test_failed_idle_refresh_does_not_retry_forever(self):
        self.clock.advance(181)
        self.scheduler.status()
        self.assertIsNotNone(self.store.read()["outbox"])
        self.clock.advance(901)
        self.scheduler.reconcile()
        self.assertIsNone(self.store.read()["outbox"])

    def test_cloud_login_limits_persist_across_web_instances(self):
        for _ in range(5):
            self.assertTrue(self.scheduler.allow_login("test"))
        other = CloudScheduler(self.store, self.queue, self.clock)
        self.assertFalse(other.allow_login("test"))
        self.clock.advance(901)
        self.assertTrue(other.allow_login("test"))

    def test_health_and_unauthenticated_status_never_enqueue(self):
        self.assertIsNone(self.store.read()["outbox"])
        self.clock.advance(1000)
        app = create_app(self.scheduler, "test-only-password", "test-only-secret-key", secure_cookies=False)
        client = app.test_client()
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/api/status").status_code, 401)
        self.assertIsNone(self.store.read()["outbox"])

    def test_storage_outage_returns_safe_error_without_provider_details(self):
        app = create_app(self.scheduler, "test-only-password", "test-only-secret-key", secure_cookies=False)
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            token = session["csrf"]
        client.post("/", data={"csrf": token, "password": "test-only-password"})
        with patch.object(self.store, "read", side_effect=RuntimeError("test-private-provider-response")):
            with self.assertLogs(level="ERROR") as logs:
                response = client.get("/api/status")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("test-private-provider-response", response.text)
        self.assertNotIn("test-private-provider-response", " ".join(logs.output))


    def test_task_queue_encodes_only_opaque_id_and_oidc(self):
        from google.cloud.tasks_v2.types import Task
        queue = object.__new__(TaskQueue)
        queue.client = Mock()
        queue.parent = "projects/test/locations/europe-west1/queues/test"
        queue.worker_url = "https://worker.run.app"
        queue.caller = "caller@test.iam.gserviceaccount.com"
        queue.audience = "https://worker.test.internal"
        queue.publish({"id": "a" * 32, "due": 100.1})
        payload = queue.client.create_task.call_args.kwargs["task"]
        encoded = Task(payload)
        self.assertEqual(json.loads(encoded.http_request.body), {"task_id": "a" * 32})
        self.assertEqual(encoded.schedule_time.timestamp(), 101)
        self.assertEqual(encoded.http_request.oidc_token.audience, queue.audience)


class WorkerAccessTests(unittest.TestCase):
    def setUp(self):
        self.scheduler, self.execute = Mock(), Mock()
        def verify(token):
            if token != "test-only-token":
                raise ValueError()
        self.app = create_worker_app(self.scheduler, verify=verify, execute=self.execute)
        self.client = self.app.test_client()
        self.header = {"Authorization": "Bearer test-only-token"}

    def test_worker_requires_valid_identity_for_both_routes(self):
        for path in ("/tasks/step", "/tasks/reconcile"):
            self.assertEqual(self.client.post(path, json={"task_id": "a" * 32}).status_code, 401)
            self.assertEqual(self.client.post(path, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.execute.assert_not_called()
        self.scheduler.reconcile.assert_not_called()

    def test_valid_task_and_invalid_payload(self):
        self.assertEqual(self.client.post("/tasks/step", json={"task_id": "a" * 32}, headers=self.header).status_code, 200)
        self.execute.assert_called_once_with("a" * 32, None)
        self.assertEqual(self.client.post("/tasks/step", json={"task_id": "../secret"}, headers=self.header).status_code, 400)

    def test_failure_requests_provider_retry(self):
        self.execute.side_effect = TimeoutError()
        self.assertEqual(self.client.post("/tasks/step", json={"task_id": "a" * 32}, headers=self.header).status_code, 503)

    def test_vehicle_process_deadline_interrupts_stalled_work(self):
        import time
        from passat_charge.cloud_job import main
        completed = []
        def stalled(task_id):
            time.sleep(0.5)
            completed.append(task_id)
        with self.assertLogs(level="ERROR"):
            with self.assertRaises(SystemExit) as error:
                main("test-only-task", handler=stalled, timeout=0.03)
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(completed, [])

    def test_worker_uses_own_run_host_and_ignores_forwarded_host(self):
        app = create_worker_app(self.scheduler, verify=lambda _: None, execute=self.execute, resolve_url=True)
        client = app.test_client()
        response = client.post("/tasks/step", base_url="https://passat-worker-123.europe-west1.run.app",
                               json={"task_id": "a" * 32},
                               headers={**self.header, "X-Forwarded-Host": "attacker.example"})
        self.assertEqual(response.status_code, 200)
        self.execute.assert_called_once_with("a" * 32, "https://passat-worker-123.europe-west1.run.app")
        response = client.post("/tasks/step", base_url="https://attacker.example", json={"task_id": "a" * 32}, headers=self.header)
        self.assertEqual(response.status_code, 400)

    def test_identity_must_match_audience_and_expected_service_account(self):
        with patch.dict("os.environ", {"TASK_AUDIENCE": "test-audience", "TASK_SERVICE_ACCOUNT": "expected@test"}):
            with patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "wrong@test", "email_verified": True}):
                with self.assertRaises(ValueError):
                    verify_caller("test-token")
            with patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "expected@test", "email_verified": True}) as verify:
                verify_caller("test-token")
                self.assertEqual(verify.call_args.kwargs["audience"], "test-audience")
