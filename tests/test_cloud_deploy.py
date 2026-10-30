import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("deploy_gcp", Path(__file__).parents[1] / "tools/deploy_gcp.py")
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def test_default_invocation_cannot_create_resources(self):
        with patch("sys.argv", ["deploy_gcp.py", "test-project"]), patch.object(deploy, "run") as run:
            with contextlib.redirect_stdout(io.StringIO()):
                deploy.main()
            run.assert_not_called()

    def test_existing_secret_bindings_are_preserved(self):
        with patch.object(deploy, "run", return_value="projects/test/secrets/test/versions/1") as run:
            with patch("getpass.getpass") as password, contextlib.redirect_stdout(io.StringIO()):
                deploy.seed_secrets("test-project")
            password.assert_not_called()
            self.assertTrue(all("list" in call.args[0] for call in run.call_args_list))

    def test_new_secrets_use_stdin_and_never_cli_arguments(self):
        def command(args, **kwargs):
            return ""  # No existing secret versions.
        with patch.object(deploy, "run", side_effect=command) as run:
            with patch("getpass.getpass", side_effect=["test-only-app-password", "test-only-app-password", "test-only-vw-password"]):
                with patch("builtins.input", side_effect=["test-only@example.invalid", "WVWZZZ3CZLE000001"]):
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        deploy.seed_secrets("test-project")
            writes = [call for call in run.call_args_list if "input_text" in call.kwargs]
            self.assertEqual(len(writes), 2)
            values = [json.loads(call.kwargs["input_text"]) for call in writes]
            self.assertGreaterEqual(len(values[0]["session_secret"]), 32)
            for call in writes:
                self.assertNotIn("test-only-app-password", " ".join(call.args[0]))
                self.assertNotIn("test-only-vw-password", " ".join(call.args[0]))
            self.assertNotIn("test-only-app-password", output.getvalue())
            self.assertNotIn("test-only-vw-password", output.getvalue())
