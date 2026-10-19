"""Tests for the opt-in systemd lifecycle of all seven providers."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flagship import cli, lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="flagship-lifecycle-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ctx = cli.Context(self.root / "state", self.root / "workspace")
        self.catalog = cli.load_catalog()
        self.config = self.root / "config"
        self.env = {"XDG_CONFIG_HOME": str(self.config), "PATH": "/usr/bin:/bin"}

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(["--state-dir", str(self.ctx.state_dir), "--workspace", str(self.ctx.workspace), *args])
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def args(self, command, **values):
        fields = {"command": command, "dry_run": False}
        fields.update(values)
        return SimpleNamespace(**fields)

    def test_unit_set_requires_every_profile_and_restarts_long_lived_services(self):
        with patch.dict(os.environ, self.env), patch.object(lifecycle.shutil, "which", return_value="/home/test/.local/bin/flagship"):
            files = lifecycle.unit_files(self.ctx, self.catalog)
        self.assertEqual(set(files), {"flagship.target", *(f"flagship-{p}.service" for p in self.catalog)})
        target = files[lifecycle.TARGET]
        for profile in self.catalog:
            self.assertIn(f"flagship-{profile}.service", target)
            service = files[f"flagship-{profile}.service"]
            self.assertIn(f'"run" "{profile}" "--" "sleep" "infinity"', service)
            self.assertIn("ExecStop=", service)
            self.assertIn('"--_service-stop"', service)
            self.assertIn("Restart=always", service)
            self.assertIn("PartOf=flagship.target", service)

    def test_unit_uses_the_installed_console_entry_point(self):
        with patch.dict(os.environ, self.env), patch.object(lifecycle.shutil, "which", return_value="/home/test/.local/bin/flagship"):
            service = lifecycle.unit_files(self.ctx, self.catalog)["flagship-kali.service"]
        self.assertIn('ExecStart="/home/test/.local/bin/flagship"', service)
        self.assertNotIn('"-m" "flagship"', service)

    def test_service_path_does_not_capture_windows_or_session_paths(self):
        path = "/usr/bin:/bin:/mnt/c/Windows/System32:/home/test/session-bin"
        located = {"flagship": "/home/test/.local/bin/flagship", "podman": "/usr/bin/podman",
                   "distrobox": "/usr/bin/distrobox"}
        with patch.dict(os.environ, {**self.env, "PATH": path}), \
                patch.object(lifecycle.shutil, "which", side_effect=located.get):
            service = lifecycle.unit_files(self.ctx, self.catalog)["flagship-kali.service"]
        self.assertIn('Environment=PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"', service)
        self.assertNotIn("/mnt/c/Windows/System32", service)
        self.assertNotIn("/home/test/session-bin", service)

    def test_dry_run_lists_lifecycle_units_without_writing_or_running_them(self):
        with patch.dict(os.environ, self.env), patch.object(lifecycle, "_systemctl") as systemctl:
            code, output, error = self.invoke("--dry-run", "boot")
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(result["requires_all_profiles"], list(self.catalog))
        self.assertEqual(len(result["unit_files"]), 8)
        self.assertFalse(self.config.exists())
        systemctl.assert_not_called()

    def test_boot_refuses_partial_provider_set_before_writing_or_starting(self):
        def managed(_ctx, profile):
            if profile == "tsurugi":
                raise cli.CommandError("No container for tsurugi")

        with patch.dict(os.environ, self.env), patch.object(cli, "require_runtime"), \
                patch.object(cli, "validate_backend_configuration"), patch.object(lifecycle, "_require_user_manager"), \
                patch.object(cli, "managed_container", side_effect=managed), patch.object(lifecycle, "_systemctl") as systemctl:
            code, _, error = self.invoke("boot")
        self.assertEqual(code, 1)
        self.assertIn("all seven providers", error)
        self.assertIn("tsurugi", error)
        self.assertFalse(self.config.exists())
        systemctl.assert_not_called()

    def test_boot_writes_units_then_starts_one_required_target(self):
        calls = []
        with patch.dict(os.environ, self.env), patch.object(cli, "require_runtime"), \
                patch.object(cli, "validate_backend_configuration"), patch.object(cli, "managed_container"), \
                patch.object(lifecycle, "_systemctl", side_effect=lambda args, **kwargs: calls.append(args) or Mock(returncode=0)):
            code, output, error = self.invoke("boot")
        self.assertEqual(code, 0, error)
        self.assertIn("all seven providers", output)
        self.assertEqual(calls[0], ["show-environment"])
        self.assertEqual(calls[1], ["daemon-reload"])
        self.assertEqual(calls[2], ["start", lifecycle.TARGET])
        self.assertEqual(len(list((self.config / "systemd" / "user").glob("*.service"))), 7)

    def test_boot_reports_service_failures_even_when_target_start_succeeds(self):
        def systemctl(args, **kwargs):
            if args == ["is-active", "flagship-caine.service"]:
                return SimpleNamespace(returncode=3, stdout="inactive\n")
            return SimpleNamespace(returncode=0, stdout="active\n")

        with patch.dict(os.environ, self.env), patch.object(cli, "require_runtime"), \
                patch.object(cli, "validate_backend_configuration"), patch.object(cli, "managed_container"), \
                patch.object(lifecycle, "_systemctl", side_effect=systemctl):
            code, output, error = self.invoke("boot")
        self.assertEqual(code, 1)
        self.assertNotIn("all seven providers", output)
        self.assertIn("inactive services: caine", error)

    def test_restart_stops_the_target_before_starting_it_again(self):
        calls = []
        with patch.dict(os.environ, self.env), patch.object(cli, "require_runtime"), \
                patch.object(cli, "validate_backend_configuration"), patch.object(cli, "managed_container"), \
                patch.object(lifecycle, "_systemctl", side_effect=lambda args, **kwargs: calls.append(args) or Mock(returncode=0)), \
                patch.object(lifecycle, "_stop_all_owned"):
            code, _, error = self.invoke("restart")
        self.assertEqual(code, 0, error)
        self.assertLess(calls.index(["stop", lifecycle.TARGET]), calls.index(["start", lifecycle.TARGET]))

    def test_autostart_enable_with_linger_establishes_boot_persistence(self):
        events = []
        with patch.dict(os.environ, self.env), patch.object(cli, "require_runtime"), \
                patch.object(cli, "validate_backend_configuration"), patch.object(cli, "managed_container"), \
                patch.object(lifecycle, "_enable_linger", side_effect=lambda: events.append("linger")), \
                patch.object(lifecycle, "_systemctl", side_effect=lambda args, **kwargs: events.append(args) or Mock(returncode=0)):
            code, output, error = self.invoke("autostart", "enable", "--linger")
        self.assertEqual(code, 0, error)
        self.assertIn("when WSL starts", output)
        self.assertEqual(events[0], "linger")
        self.assertIn(["enable", lifecycle.TARGET], events)
        self.assertIn(["start", lifecycle.TARGET], events)

    def test_autostart_disable_does_not_stop_current_provider_set(self):
        calls = []
        with patch.dict(os.environ, self.env), patch.object(lifecycle, "_systemctl", side_effect=lambda args, **kwargs: calls.append(args) or Mock(returncode=0)):
            code, output, error = self.invoke("autostart", "disable")
        self.assertEqual(code, 0, error)
        self.assertIn("currently running providers are unchanged", output)
        self.assertEqual(calls[-1], ["disable", lifecycle.TARGET])
        self.assertNotIn(["stop", lifecycle.TARGET], calls)

    def test_shutdown_stops_the_target_without_requiring_all_seven_to_validate(self):
        calls = []
        with patch.dict(os.environ, self.env), patch.object(lifecycle, "_systemctl", side_effect=lambda args, **kwargs: calls.append(args) or Mock(returncode=0)), \
                patch.object(lifecycle, "_validate_all") as validate, patch.object(lifecycle, "_stop_all_owned") as stop:
            code = lifecycle.main(self.ctx, self.args("shutdown"), self.catalog)
        self.assertEqual(code, 0)
        validate.assert_not_called()
        stop.assert_called_once_with(self.ctx, self.catalog)
        self.assertEqual(calls[-1], ["stop", lifecycle.TARGET])

    def test_status_marks_target_incomplete_if_any_provider_service_is_inactive(self):
        def systemctl(args, **kwargs):
            if args == ["is-active", "flagship-tsurugi.service"]:
                return SimpleNamespace(returncode=3, stdout="inactive\n")
            return SimpleNamespace(returncode=0, stdout="active\n")

        with patch.dict(os.environ, self.env), patch.object(lifecycle, "_systemctl", side_effect=systemctl):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                lifecycle.main(self.ctx, self.args("autostart", action="status", linger=False), self.catalog)
        self.assertIn("Provider set: incomplete or stopped", stdout.getvalue())
        self.assertIn("tsurugi: stopped", stdout.getvalue())

    def test_unmanaged_unit_is_never_overwritten(self):
        directory = self.config / "systemd" / "user"
        directory.mkdir(parents=True)
        (directory / lifecycle.TARGET).write_text("[Unit]\nDescription=someone else's unit\n")
        with patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(cli.CommandError, "unmanaged systemd unit"):
                lifecycle._write_unit_files(self.ctx, self.catalog)

    def test_unmanaged_late_unit_prevents_any_partial_unit_install(self):
        directory = self.config / "systemd" / "user"
        directory.mkdir(parents=True)
        (directory / "flagship-caine.service").write_text("[Unit]\nDescription=someone else's unit\n")
        with patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(cli.CommandError, "unmanaged systemd unit"):
                lifecycle._write_unit_files(self.ctx, self.catalog)
        self.assertEqual({item.name for item in directory.iterdir()}, {"flagship-caine.service"})

    def test_linger_enable_skips_sudo_when_already_enabled(self):
        with patch.object(cli, "capture", return_value=SimpleNamespace(returncode=0, stdout="Linger=yes\n")), \
                patch.object(cli, "checked_stream") as sudo:
            lifecycle._enable_linger()
        sudo.assert_not_called()

    def test_stop_hook_only_stops_a_verified_owned_container(self):
        instance = "290f1491-5122-446c-aaef-baf18110e128"
        record = {"schema_version": 1, "profile": "kali", "container": "flagship-kali",
                  "installation_id": instance, "workspace": str(self.ctx.workspace), "status": "created"}
        cli.atomic_json(self.ctx.state_dir / "install.json", {"schema_version": 1, "installation_id": instance})
        cli.atomic_json(self.ctx.record_path("kali"), record)
        container = {"Config": {"Labels": {
            f"{cli.LABEL}.managed": "true",
            f"{cli.LABEL}.installation": instance,
            f"{cli.LABEL}.profile": "kali",
        }}}
        with patch.object(cli, "inspect_container", return_value=container), patch.object(cli, "checked_stream") as stop:
            lifecycle._stop_owned(self.ctx, "kali")
        stop.assert_called_once_with(["podman", "stop", "--time", "15", "flagship-kali"])
        container["Config"]["Labels"][f"{cli.LABEL}.installation"] = "foreign"
        with patch.object(cli, "inspect_container", return_value=container), patch.object(cli, "checked_stream") as stop:
            with self.assertRaisesRegex(cli.CommandError, "foreign"):
                lifecycle._stop_owned(self.ctx, "kali")
        stop.assert_not_called()

    def test_bulk_shutdown_stops_running_owned_containers_and_checks_the_result(self):
        instance = "290f1491-5122-446c-aaef-baf18110e128"
        record = {"schema_version": 1, "profile": "kali", "container": "flagship-kali",
                  "installation_id": instance, "workspace": str(self.ctx.workspace), "status": "created"}
        cli.atomic_json(self.ctx.state_dir / "install.json", {"schema_version": 1, "installation_id": instance})
        cli.atomic_json(self.ctx.record_path("kali"), record)
        labels = {f"{cli.LABEL}.managed": "true", f"{cli.LABEL}.installation": instance,
                  f"{cli.LABEL}.profile": "kali"}
        running = {"Config": {"Labels": labels}, "State": {"Status": "running"}}
        exited = {"Config": {"Labels": labels}, "State": {"Status": "exited"}}
        kali_inspections = iter([running, exited])

        def inspect(name):
            return next(kali_inspections) if name == "flagship-kali" else None

        with patch.object(cli, "inspect_container", side_effect=inspect), patch.object(cli, "checked_stream") as stop:
            lifecycle._stop_all_owned(self.ctx, self.catalog)
        stop.assert_called_once_with(["podman", "stop", "--time", "15", "flagship-kali"])

    def test_internal_stop_option_stops_owned_profile_without_public_help_entry(self):
        instance = "290f1491-5122-446c-aaef-baf18110e128"
        record = {"schema_version": 1, "profile": "kali", "container": "flagship-kali",
                  "installation_id": instance, "workspace": str(self.ctx.workspace), "status": "created"}
        cli.atomic_json(self.ctx.state_dir / "install.json", {"schema_version": 1, "installation_id": instance})
        cli.atomic_json(self.ctx.record_path("kali"), record)
        container = {"Config": {"Labels": {
            f"{cli.LABEL}.managed": "true",
            f"{cli.LABEL}.installation": instance,
            f"{cli.LABEL}.profile": "kali",
        }}}
        with patch.object(cli, "inspect_container", return_value=container), patch.object(cli, "checked_stream") as stop:
            code, _, error = self.invoke("--_service-stop", "kali")
        self.assertEqual(code, 0, error)
        stop.assert_called_once_with(["podman", "stop", "--time", "15", "flagship-kali"])

    def test_cli_help_exposes_lifecycle_without_exposing_internal_stop_hook(self):
        code, output, _ = self.invoke("--help")
        self.assertEqual(code, 0)
        self.assertIn("boot", output)
        self.assertIn("shutdown", output)
        self.assertIn("restart", output)
        self.assertIn("autostart", output)
        self.assertNotIn("_service-stop", output)

