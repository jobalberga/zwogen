"""Run explicitly with FIRESTORE_EMULATOR_HOST; never uses real credentials."""

import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from passat_charge.cloud import CloudScheduler, CloudWorker
from passat_charge.cloud_store import FirestoreStore
from passat_charge.scheduler import PlanError
from tests.cloud_helpers import CloudFixture


@unittest.skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "requires local Firestore emulator")
class FirestoreIntegrationTests(CloudFixture, unittest.TestCase):
    def make_store(self):
        store = FirestoreStore("passat-cloud-test")
        store.reference = store.client.collection("test_runs").document(uuid.uuid4().hex)
        self.addCleanup(store.reference.delete)
        self.addCleanup(store.client.close)
        return store

    def test_two_concurrent_arms_create_only_one_plan(self):
        barrier = threading.Barrier(2)
        def arm():
            barrier.wait(5)
            try:
                return self.scheduler.arm()["id"]
            except PlanError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: arm(), range(2)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(self.store.read()["plan"]["id"], next(item for item in results if item))

    def test_real_transaction_retries_do_not_lose_updates(self):
        self.store.mutate(lambda state: state.update(counter=0))
        def increment(_):
            def change(state):
                state["counter"] += 1
            self.store.mutate(change)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(increment, range(8)))
        self.assertEqual(self.store.read()["counter"], 8)

    def test_new_client_restores_plan_and_cancel_blocks_old_task(self):
        plan = self.paused_plan()
        task_id = self.store.read()["outbox"]["id"]
        other = FirestoreStore("passat-cloud-test")
        self.addCleanup(other.client.close)
        other.reference = self.store.reference
        scheduler = CloudScheduler(other, self.queue, self.clock)
        self.assertEqual(scheduler.store.read()["plan"]["id"], plan["id"])
        scheduler.cancel(plan["id"])
        self.clock.now = plan["due"]
        CloudWorker(other, scheduler, self.vehicle, self.clock).run(task_id)
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])

    def test_outbox_recovers_after_queue_outage(self):
        self.queue.fail = True
        with self.assertRaises(PlanError):
            self.scheduler.arm()
        self.queue.fail = False
        self.scheduler.reconcile()
        self.step()
        self.assertEqual(self.store.read()["plan"]["state"], "confirm_stop")

    def test_login_reservations_are_atomic(self):
        bucket = uuid.uuid4().hex
        self.addCleanup(lambda: self.store.clear_login(bucket))
        with ThreadPoolExecutor(max_workers=4) as pool:
            allowed = list(pool.map(lambda _: self.store.allow_login(bucket, self.clock()), range(8)))
        self.assertEqual(sum(allowed), 5)

    def test_real_web_login_and_plan_use_cloud_state(self):
        from passat_charge.web import create_app
        app = create_app(self.scheduler, "test-only-password", "test-only-session-secret", secure_cookies=False)
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            token = session["csrf"]
        self.assertEqual(client.post("/", data={"csrf": token, "password": "test-only-password"}).status_code, 302)
        with client.session_transaction() as session:
            token = session["csrf"]
        response = client.post("/api/plan", json={"start_time": "22:30"}, headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.store.read()["plan"]["id"], response.json["plan"]["id"])
        self.assertEqual(client.get("/api/status").json["plan"]["due"], response.json["plan"]["due"])
