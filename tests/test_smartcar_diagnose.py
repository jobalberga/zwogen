import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

SPEC = importlib.util.spec_from_file_location("diagnose_smartcar", Path(__file__).parents[1] / "tools/diagnose_smartcar.py")
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)

VEHICLE = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
PRIVATE = "private-password private-token private@example.invalid private-vin"


def connection(permissions, mode="live"):
    return {"attributes": {"permissions": permissions, "vehicle": {"mode": mode}},
            "relationships": {"vehicle": {"data": {"id": VEHICLE}}, "user": {"data": {"id": USER}}}}


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())


class FakeOpener:
    def __init__(self, permissions=diagnose.PERMISSIONS):
        self.calls = []
        self.rows = [connection(list(permissions))]
        self.signals = {}
        self.token_error = None

    def open(self, request, timeout):
        self.calls.append(request)
        if request.full_url == diagnose.TOKEN_URL:
            if self.token_error:
                raise self.token_error
            return Response({"access_token": "private-token", "token_type": "Bearer"})
        if "/connections?" in request.full_url:
            return Response({"data": self.rows, "meta": {"totalCount": len(self.rows)}})
        code = request.full_url.rsplit("/", 1)[-1]
        values = {"tractionbattery-stateofcharge": 43, "charge-detailedchargingstatus": "NOT_CHARGING",
                  "charge-ischargingcableconnected": False}
        return Response(self.signals.get(code, {"data": {"attributes": {"code": code, "status": {"value": "SUCCESS"},
                                                                      "body": {"value": values[code]}},
                                                       "meta": {"oemUpdatedAt": "2026-10-30T10:00:00Z"}}}))


class SmartcarDiagnosisTests(unittest.TestCase):
    def test_m2m_read_only_probe_uses_scoped_user_and_no_vehicle_commands(self):
        opener = FakeOpener()
        report = diagnose.probe("client_test", "private-secret", opener=opener)
        self.assertTrue(report["authenticated"])
        self.assertEqual(report["live_vehicles"], 1)
        self.assertTrue(all(report["permissions"].values()))
        token_request = opener.calls[0]
        self.assertEqual(json.loads(token_request.data), {"client_id": "client_test", "client_secret": "private-secret",
                                                         "grant_type": "client_credentials"})
        self.assertEqual(parse_qs(urlsplit(opener.calls[1].full_url).query), {"filter[vehicle.mode]": ["live"]})
        self.assertEqual(len(opener.calls), 5)
        self.assertTrue(all(request.get_method() == "GET" for request in opener.calls[1:]))
        for request in opener.calls[2:]:
            self.assertEqual(request.get_header("Sc-user-id"), USER)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            diagnose.print_report(report)
        self.assertIn("43%", output.getvalue())
        self.assertIn("Losgekoppeld", output.getvalue())
        for secret in ("client_test", "private-secret", "private-token", VEHICLE, USER):
            self.assertNotIn(secret, output.getvalue() + json.dumps(report))

    def test_absent_permissions_skip_signal_calls_without_claiming_a_paywall(self):
        opener = FakeOpener(permissions=[])
        report = diagnose.probe("client_test", "private-secret", opener=opener)
        self.assertEqual(len(opener.calls), 2)
        self.assertFalse(any(report["permissions"].values()))
        self.assertTrue(all("toestemming ontbreekt" in result["status"] for result in report["signals"].values()))

    def test_simulated_or_multiple_vehicles_are_not_selected(self):
        for rows in ([connection([], "test")], [connection([]), connection([])]):
            with self.subTest(count=len(rows)):
                opener = FakeOpener()
                opener.rows = rows
                report = diagnose.probe("client_test", "private-secret", opener=opener)
                self.assertIn("precies één", report["error"])
                self.assertEqual(len(opener.calls), 2)

    def test_http_error_cannot_expose_provider_body_or_secrets(self):
        opener = FakeOpener()
        opener.token_error = HTTPError(diagnose.TOKEN_URL, 401, PRIVATE, {}, io.BytesIO(PRIVATE.encode()))
        report = diagnose.probe("client_test", "private-secret", opener=opener)
        self.assertEqual(report["error"], "HTTP 401")
        self.assertNotIn(PRIVATE, json.dumps(report))
        self.assertEqual(len(opener.calls), 1)

    def test_signal_errors_and_unexpected_values_never_reach_output(self):
        opener = FakeOpener()
        for code in diagnose.SIGNALS:
            opener.signals[code] = {"data": {"attributes": {"code": code, "status": {"value": "ERROR", "error": {
                "type": "PERMISSION", "detail": PRIVATE}}, "body": {"value": PRIVATE}}}}
        report = diagnose.probe("client_test", "private-secret", opener=opener)
        self.assertTrue(all(result["status"] == "PERMISSION" for result in report["signals"].values()))
        self.assertNotIn(PRIVATE, json.dumps(report))
        for code in diagnose.SIGNALS:
            result = diagnose.summarize_signal({"data": {"attributes": {"code": code, "status": {"value": "SUCCESS"},
                                                                        "body": {"value": PRIVATE}},
                                                        "meta": {"oemUpdatedAt": PRIVATE}}}, code)
            self.assertEqual(result["value"], "Onbekend")
            self.assertIsNone(result["measured_at"])

    def test_redirects_and_vehicle_posts_are_rejected(self):
        self.assertIsNone(diagnose.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid"))
        with self.assertRaisesRegex(diagnose.CheckError, "POST"):
            diagnose.request_json(FakeOpener(), diagnose.API_URL + "/vehicles/" + VEHICLE + "/charge/start", data={})

