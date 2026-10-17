"""Distrobox's own shell parsing requires conservative Linux path syntax."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flagship import cli


@unittest.skipUnless(sys.platform == "linux", "Linux path policy applies to the actual container host")
class LinuxPathPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flagship-path-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def invoke(self, state, workspace, *command):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["--state-dir", str(state), "--workspace", str(workspace), *command]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_unsafe_state_or_workspace_rejected_before_backend_and_filesystem(self):
        leaves = (
            "a b", "a\tb", "a\nb", "a:mount", "a $(touch marker)",
            "a;literal", "a'quoted", 'a"quoted', "a`literal`", "a\\b",
            "a[pattern]", "a*", "a&literal", "a|literal", "a>literal", "a<literal",
        )
        commands = (("create", "kali"), ("--dry-run", "create", "kali"), ("plan", "kali"))
        with patch.object(cli.subprocess, "run") as capture, patch.object(cli.subprocess, "Popen") as process:
            for leaf in leaves:
                for field in ("state", "workspace"):
                    state = self.root / (leaf if field == "state" else "state")
                    workspace = self.root / (leaf if field == "workspace" else "workspace")
                    for command in commands:
                        with self.subTest(leaf=leaf, field=field, command=command):
                            code, _, error = self.invoke(state, workspace, *command)
                            self.assertEqual(code, 1, error)
                            self.assertIn("path", error.lower())
                            self.assertEqual(list(self.root.iterdir()), [])
        capture.assert_not_called()
        process.assert_not_called()

    def test_space_rejection_explains_supported_paths(self):
        code, _, error = self.invoke(self.root / "state", self.root / "workspace with spaces", "plan", "kali")
        self.assertEqual(code, 1)
        self.assertIn("space", error.lower())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_supported_absolute_paths_still_plan_without_mutation(self):
        state = self.root / "private_state-01"
        workspace = self.root / "workspace.v1"
        with patch.object(cli.subprocess, "run") as capture, patch.object(cli.subprocess, "Popen") as process:
            code, output, error = self.invoke(state, workspace, "--dry-run", "create", "kali")
        self.assertEqual(code, 0, error)
        steps = json.loads(output)["steps"]
        create = next(step["argv"] for step in steps if step["argv"][:2] == ["distrobox", "create"])
        self.assertIn(f"{workspace}:/workspace:rw", create)
        capture.assert_not_called()
        process.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsafe_inherited_paths_are_rejected_with_explicit_safe_paths(self):
        keys = ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "SHELL")
        with patch.object(cli.subprocess, "run") as capture, patch.object(cli.subprocess, "Popen") as process:
            for key in keys:
                with self.subTest(key=key), patch.dict(os.environ, {key: str(self.root / "unsafe path")}):
                    code, _, error = self.invoke(self.root / "state", self.root / "workspace", "create", "kali")
                    self.assertEqual(code, 1, error)
                    self.assertIn("path", error.lower())
                    self.assertEqual(list(self.root.iterdir()), [])
        capture.assert_not_called()
        process.assert_not_called()

    def test_safe_symlink_spelling_does_not_hide_unsafe_resolved_path(self):
        target = self.root / "target with spaces"
        target.mkdir()
        link = self.root / "safe-link"
        link.symlink_to(target, target_is_directory=True)
        with patch.object(cli.subprocess, "run") as capture, patch.object(cli.subprocess, "Popen") as process:
            code, _, error = self.invoke(self.root / "state", link, "plan", "kali")
        self.assertEqual(code, 1, error)
        self.assertIn("path", error.lower())
        self.assertFalse((self.root / "state").exists())
        capture.assert_not_called()
        process.assert_not_called()

    def test_backend_drops_environment_overrides_and_uses_local_account(self):
        import pwd
        overrides = {
            "DBX_CONTAINER_MANAGER": "docker", "DBX_CONTAINER_NAME": "unowned",
            "DBX_CONTAINER_HOME_PREFIX": "/other", "DBX_SUDO_PROGRAM": "sudo",
            "USER": "invented-user", "LOGNAME": "invented-user",
        }
        with patch.dict(os.environ, overrides):
            environment = cli.backend_env()
        self.assertEqual({key for key in environment if key.startswith("DBX_")}, {"DBX_CONTAINER_MANAGER", "DBX_SUDO_PROGRAM"})
        self.assertEqual(environment["DBX_CONTAINER_MANAGER"], "podman")
        self.assertEqual(environment["DBX_SUDO_PROGRAM"], "/bin/false")
        self.assertEqual(environment["USER"], pwd.getpwuid(os.getuid()).pw_name)
        self.assertEqual(environment["LOGNAME"], environment["USER"])

    def test_remote_engine_configuration_is_rejected(self):
        for key in ("CONTAINER_HOST", "CONTAINER_CONNECTION"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "fixture-remote"}):
                with self.assertRaisesRegex(cli.CommandError, "Remote Podman"):
                    cli.validate_backend_configuration()

    def test_custom_distrobox_config_is_reported_before_use(self):
        config = self.root / ".distroboxrc"
        with patch.object(Path, "home", return_value=self.root), \
                patch.object(Path, "exists", autospec=True, side_effect=lambda path: path == config), \
                patch.dict(os.environ, {"CONTAINER_HOST": "", "CONTAINER_CONNECTION": ""}):
            with self.assertRaisesRegex(cli.CommandError, "Custom Distrobox") as failure:
                cli.validate_backend_configuration()
        self.assertIn(str(config), str(failure.exception))

    def test_floating_or_shell_shaped_state_image_cannot_reach_plan(self):
        for image in ("docker.io/example/image:latest", "image;literal", "$(printf literal)", 5):
            with self.subTest(image=image):
                state = self.root / "state"
                cli.atomic_json(state / "profiles" / "kali.json", {"image": image})
                with patch.object(cli.subprocess, "run") as capture, patch.object(cli.subprocess, "Popen") as process:
                    code, _, error = self.invoke(state, self.root / "workspace", "plan", "kali")
                self.assertEqual(code, 1, error)
                self.assertIn("immutable image", error)
                capture.assert_not_called()
                process.assert_not_called()
                self.assertFalse((self.root / "workspace").exists())


if __name__ == "__main__":
    unittest.main()
