import re
import unittest

from passat_charge.web import create_app
from tests.helpers import Fixture


class WebTests(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.scheduler, "test-only-password", "test-only-session-key", secure_cookies=False)
        self.app.testing = True
        self.client = self.app.test_client()

    def csrf(self):
        self.client.get("/")
        with self.client.session_transaction() as session:
            return session["csrf"]

    def login(self):
        response = self.client.post("/", data={"csrf": self.csrf(), "password": "test-only-password"})
        self.assertEqual(response.status_code, 302)

    def test_login_required_for_vehicle_information_and_mutations(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        token = self.csrf()
        self.assertEqual(self.client.post("/api/plan", headers={"X-CSRF-Token": token}).status_code, 401)
        self.assertEqual(self.vehicle.calls, [])

    def test_csrf_required_even_after_login(self):
        self.login()
        self.assertEqual(self.client.post("/api/plan").status_code, 403)
        self.assertEqual(self.client.post("/api/plan", headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post("/", data={"csrf": "€"}).status_code, 403)

    def test_plan_and_cancel_round_trip(self):
        self.login()
        token = self.csrf()
        response = self.client.post("/api/plan", headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 201)
        plan = response.json["plan"]
        self.assertEqual(self.client.get("/api/status").json["plan"]["id"], plan["id"])
        self.assertEqual(self.client.post("/api/plan", headers={"X-CSRF-Token": token}).status_code, 409)
        cancelled = self.client.post("/api/plan/" + plan["id"] + "/cancel", headers={"X-CSRF-Token": token})
        self.assertEqual(cancelled.json["plan"]["state"], "cancelled")

    def test_rate_limit_is_persistent_and_expires(self):
        token = self.csrf()
        for _ in range(5):
            self.assertEqual(self.client.post("/", data={"csrf": token, "password": "wrong"}).status_code, 401)
        other = create_app(self.scheduler, "test-only-password", "test-only-session-key", secure_cookies=False).test_client()
        other.get("/")
        with other.session_transaction() as session:
            other_token = session["csrf"]
        self.assertEqual(other.post("/", data={"csrf": other_token, "password": "test-only-password"}).status_code, 429)
        self.clock.advance(901)
        self.assertEqual(other.post("/", data={"csrf": other_token, "password": "test-only-password"}).status_code, 302)

    def test_selected_time_is_scheduled_and_survives_restart(self):
        from datetime import datetime
        from passat_charge.scheduler import Scheduler, ZONE
        self.login()
        response = self.client.post("/api/plan", json={"start_time": "22:30"},
                                    headers={"X-CSRF-Token": self.csrf()})
        self.assertEqual(response.status_code, 201)
        due = datetime(2026, 10, 29, 22, 30, tzinfo=ZONE).timestamp()
        self.assertEqual(response.json["plan"]["due"], due)
        self.scheduler.tick()
        self.clock.advance(180)
        self.vehicle.measure(charging=False)
        self.scheduler.tick()
        restored = Scheduler(self.database, self.vehicle, self.clock)
        self.clock.now = due - 1
        restored.tick()
        self.assertEqual([action for action, _ in self.vehicle.calls], ["stop"])
        self.clock.now = due
        restored.tick()
        self.assertEqual(self.vehicle.calls[-1], ("start", due))

    def test_invalid_time_does_not_create_a_plan(self):
        self.login()
        for payload in ({"start_time": "25:00"}, {"start_time": None}, ["22:30"]):
            response = self.client.post("/api/plan", json=payload,
                                        headers={"X-CSRF-Token": self.csrf()})
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(self.scheduler.latest())

    def test_status_supplies_dates_for_all_dropdown_choices(self):
        self.login()
        state = self.client.get("/api/status").json
        self.assertEqual(len(state["start_times"]), 48)
        self.assertEqual(state["start_times"][0]["value"], "00:00")
        self.assertEqual(state["start_times"][-1]["value"], "23:30")
        self.assertTrue(all(item["due"] > state["now"] for item in state["start_times"]))

    def test_logout_rotates_session_and_revokes_access(self):
        self.login()
        self.assertEqual(self.client.post("/logout", data={"csrf": self.csrf()}).status_code, 302)
        self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_password_change_revokes_existing_sessions(self):
        self.login()
        cookie = self.client.get_cookie("session")
        other = create_app(self.scheduler, "new-test-only-password", "test-only-session-key", secure_cookies=False).test_client()
        other.set_cookie("session", cookie.value)
        self.assertEqual(other.get("/api/status").status_code, 401)
        self.assertIn(b"App-wachtwoord", other.get("/").data)

    def test_no_car_details_on_login_page_and_assets_resolve(self):
        page = self.client.get("/")
        self.assertIn(b"App-wachtwoord", page.data)
        self.assertNotIn(b'id="battery"', page.data)
        self.login()
        page = self.client.get("/")
        for path in re.findall(rb'(?:src|href)="(/static/[^"]+)"', page.data):
            response = self.client.get(path.decode())
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_headers_and_safe_health_endpoint(self):
        app = create_app(self.scheduler, "test-only-password", "test-key", secure_cookies=True)
        response = app.test_client().get("/healthz")
        self.assertEqual(response.json, {"ok": True, "planner": True})
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
