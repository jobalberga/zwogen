import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("deploy_gcp", Path(__file__).parents[1] / "tools/deploy_gcp.py")
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def test_default_invocation_cannot_create_resources(self):
        with patch("sys.argv", ["deploy_gcp.py", "test-project"]), patch.object(deploy, "run") as run:
            run.return_value = '{"terraform_version": "1.10.5"}'
            with patch.object(deploy.shutil, "which", side_effect=lambda name: "/usr/bin/" + name):
                with contextlib.redirect_stdout(io.StringIO()):
                    deploy.main()
            run.assert_called_once_with(["/usr/bin/terraform", "version", "-json"], capture=True)

    def test_placeholder_is_rejected_before_any_cloud_mutation(self):
        with patch("sys.argv", ["deploy_gcp.py", "test-project", "--apply"]):
            with patch.object(deploy.shutil, "which", side_effect=lambda name: "/usr/bin/" + name):
                with patch.object(deploy, "run", return_value="Follow the instructions to install terraform") as run:
                    with self.assertRaisesRegex(ValueError, "setup_cloud_shell.sh"):
                        deploy.main()
                run.assert_called_once_with(["/usr/bin/terraform", "version", "-json"], capture=True)

    def test_unsupported_terraform_output_is_rejected(self):
        for output in ('{}', '[]', 'null', '{"terraform_version": null}',
                       '{"terraform_version": "1.5.7"}', '{"terraform_version": "1.6.0-rc1"}'):
            with self.subTest(output=output):
                with patch.object(deploy.shutil, "which", return_value="terraform"):
                    with patch.object(deploy, "run", return_value=output):
                        with self.assertRaisesRegex(ValueError, "minimaal 1.6"):
                            deploy.check_tools()

    def test_terraform_failure_gives_installation_instructions(self):
        with patch.object(deploy.shutil, "which", return_value="terraform"):
            with patch.object(deploy, "run", side_effect=subprocess.CalledProcessError(1, ["terraform"])):
                with self.assertRaisesRegex(ValueError, "setup_cloud_shell.sh"):
                    deploy.check_tools()

    def test_missing_terraform_does_not_run_cloud_commands(self):
        with patch.object(deploy.shutil, "which", side_effect=lambda name: name if name == "gcloud" else None):
            with patch.object(deploy, "run") as run:
                with self.assertRaisesRegex(ValueError, "Terraform ontbreekt"):
                    deploy.check_tools()
            run.assert_not_called()

    def test_supported_terraform_is_accepted(self):
        for version in ("1.6.0", "1.10.5", "1.14.0"):
            with self.subTest(version=version):
                with patch.object(deploy.shutil, "which", return_value="terraform"):
                    with patch.object(deploy, "run", return_value=json.dumps({"terraform_version": version})):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(deploy.check_tools(), "terraform")

    def test_missing_plan_prevents_apply_and_secret_input(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(deploy, "INFRA", Path(directory)):
                with patch("sys.argv", ["deploy_gcp.py", "test-project", "--apply"]):
                    with patch.object(deploy, "check_tools", return_value="terraform"):
                        with patch.object(deploy, "run", return_value="true") as run:
                            with patch.object(deploy, "seed_secrets") as seed:
                                with self.assertRaisesRegex(ValueError, "geen installatieplan"):
                                    deploy.main()
                            seed.assert_not_called()
                        commands = [call.args[0] for call in run.call_args_list]
                        self.assertTrue(any("plan" in args for args in commands))
                        self.assertFalse(any("apply" in args for args in commands))

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
