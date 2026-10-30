import contextlib
import importlib.util
import io
import json
import logging
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("diagnose_vw", Path(__file__).parents[1] / "tools/diagnose_vw.py")
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)


class VWDiagnosisTests(unittest.TestCase):
    def test_secret_is_read_via_captured_stdout_and_never_passed_as_argument(self):
        secret = {"username": "private-user@example.invalid", "password": "private-password", "vin": "private-vin"}
        with patch.object(diagnose.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(secret))) as run:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = diagnose.read_credentials("test-project")
        self.assertEqual(result, {key: secret[key] for key in ("username", "password")})
        self.assertEqual(output.getvalue(), "")
        args = run.call_args.args[0]
        self.assertTrue(run.call_args.kwargs["capture_output"])
        for value in secret.values():
            self.assertNotIn(value, " ".join(args))

    def test_failed_login_cannot_expose_provider_payload_or_logs(self):
        private = "private-password private-token private-user@example.invalid private-vin"
        websession = SimpleNamespace(hooks={}, close=Mock())
        session = SimpleNamespace(hooks={}, websession=websession, close=Mock())

        def login():
            response = SimpleNamespace(
                url="https://emea.bff.cariad.digital/user-login/v1/authorize?token=" + private,
                status_code=403, headers={"Set-Cookie": private, "Location": "https://identity.vwgroup.io/?token=" + private},
            )
            session.hooks["response"][0](response)
            logging.error(private)
            print(private)
            print(private, file=diagnose.sys.stderr)
            raise RuntimeError(private)

        session.login = Mock(side_effect=login)
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            report = diagnose.probe({"username": private, "password": private}, session_factory=lambda config: session)
            diagnose.print_report(report)
        for value in private.split():
            self.assertNotIn(value, output.getvalue() + errors.getvalue() + json.dumps(report))
        self.assertIn("VW-aanmeldadres: HTTP 403", output.getvalue())
        session.login.assert_called_once_with()
        session.close.assert_called_once_with()
        websession.close.assert_called_once_with()

    def test_successful_probe_does_not_fetch_or_control_the_vehicle(self):
        session = Mock(hooks={}, websession=Mock(hooks={}))
        report = diagnose.probe({}, session_factory=lambda config: session)
        self.assertIsNone(report["failure"])
        session.login.assert_called_once_with()
        self.assertEqual([call[0] for call in session.mock_calls], ["login", "websession.close", "close"])

    def test_safe_failure_uses_library_location_without_exception_text(self):
        try:
            exec(compile('raise ValueError("private-token")', "/private/account/we_connect_session.py", "exec"), {})
        except ValueError as error:
            failure = diagnose.safe_failure(error)
        self.assertEqual(failure, {"type": "Overige fout", "origin": "we_connect_session.py:1"})

    def test_real_connector_reports_failure_before_credentials_are_sent(self):
        from requests import Response
        from requests.adapters import BaseAdapter

        sent = []

        class DeniedAdapter(BaseAdapter):
            def send(self, request, **kwargs):
                sent.append(request)
                response = Response()
                response.status_code = 403
                response.url = request.url
                response.request = request
                response._content = b"private-provider-body"
                return response

            def close(self):
                pass

        def session_factory(config):
            session = diagnose.make_session(config)
            session.mount("https://", DeniedAdapter())
            session.websession.mount("https://", DeniedAdapter())
            return session

        config = {"username": "private-user@example.invalid", "password": "private-password"}
        report = diagnose.probe(config, session_factory=session_factory)
        self.assertEqual(report["steps"], [{"step": "VW-aanmeldadres", "status": 403, "redirect": False}])
        self.assertEqual(report["failure"]["type"], "AuthenticationError")
        self.assertTrue(report["failure"]["origin"].startswith("we_connect_session.py:"))
        self.assertEqual(len(sent), 1)
        for value in (*config.values(), "private-provider-body"):
            self.assertNotIn(value, json.dumps(report))
            self.assertNotIn(value, sent[0].url)
            self.assertNotIn(value, str(sent[0].body))

    def test_credentials_setup_failure_never_prints_secret_response(self):
        error = subprocess.CalledProcessError(1, ["gcloud"], output="private-token", stderr="private-password")
        with patch.object(diagnose.subprocess, "run", side_effect=error):
            with self.assertRaises(subprocess.CalledProcessError):
                diagnose.read_credentials("test-project")

