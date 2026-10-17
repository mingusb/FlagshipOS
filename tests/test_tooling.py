"""Command routing contracts; containers are mocked, no security tools are run."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from flagship import cli, tooling


class ToolingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flagship-tool-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ctx = cli.Context(self.root / "state", self.root / "workspace")
        self.catalog = {"kali": {}, "parrot": {}}
        self.containers = {}
        self.records = {}
        self.inventory = {"schema_version": 1, "refreshed_at": "2026-10-17T00:00:00+00:00", "profiles": {}}
        for profile, digit in (("parrot", "2"), ("kali", "1")):
            self.containers[profile] = {"Id": digit * 64, "Config": {"Env": ["PATH=/usr/bin:/opt/example/bin"]},
                "Mounts": [{"Type": "bind", "Destination": "/workspace", "Source": str(self.ctx.workspace)}]}
            self.records[profile] = {"image_id": "sha256:" + digit * 64,
                                     "installation_id": "44be14e0-58c3-46ec-b20a-35db1e75a520", "status": "created"}
            self.inventory["profiles"][profile] = {"container_id": digit * 64,
                "image_id": self.records[profile]["image_id"],
                "installation_id": self.records[profile]["installation_id"],
                "tools": {"example-tool": f"/opt/{profile}/bin/example-tool"}}

    def provider(self, ctx, profile):
        return self.containers[profile], self.records[profile]

    def save_inventory(self):
        cli.atomic_json(self.ctx.state_dir / "inventory.json", self.inventory)

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["--state-dir", str(self.ctx.state_dir), "--workspace", str(self.ctx.workspace), *arguments]
        with patch.object(cli, "load_catalog", return_value=self.catalog), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(argv)
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_selection_uses_catalog_order_then_preference_then_override(self):
        # Cache insertion order deliberately differs from stable catalog order.
        result = tooling.resolve_tool(self.inventory, "example-tool", self.catalog)
        self.assertEqual(result["selected"]["profile"], "kali")
        self.assertEqual([item["profile"] for item in result["candidates"]], ["kali", "parrot"])
        self.assertEqual(result["selection"], "catalog-priority")
        result = tooling.resolve_tool(self.inventory, "example-tool", self.catalog,
                                      preferred={"example-tool": "parrot"})
        self.assertEqual(result["selected"]["profile"], "parrot")
        self.assertEqual(result["selection"], "preference")
        result = tooling.resolve_tool(self.inventory, "example-tool", self.catalog, profile="kali",
                                      preferred={"example-tool": "parrot"})
        self.assertEqual(result["selected"]["profile"], "kali")
        self.assertEqual(result["selection"], "override")

    def test_missing_preferred_provider_does_not_silently_change_tool(self):
        del self.inventory["profiles"]["parrot"]["tools"]["example-tool"]
        for options in ({"preferred": {"example-tool": "parrot"}}, {"profile": "parrot"}):
            with self.subTest(options=options), self.assertRaises(cli.CommandError) as error:
                tooling.resolve_tool(self.inventory, "example-tool", self.catalog, **options)
            self.assertEqual(error.exception.code, 127)

    def test_invalid_tool_names_and_profiles_fail_before_runtime(self):
        with patch.object(cli, "require_runtime") as runtime, patch.object(cli, "stream") as stream:
            for name in ("../example", "/usr/bin/example", "a b", "a;literal", "$(literal)", "-option", "a\x00b"):
                with self.subTest(name=name):
                    self.assertEqual(self.invoke("exec", name)[0], 2)
            self.assertEqual(self.invoke("exec", "--profile", "unknown", "example-tool")[0], 2)
        runtime.assert_not_called()
        stream.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_all_unified_dry_runs_avoid_runtime_discovery_and_files(self):
        commands = (("tools", "--refresh"), ("which", "example-tool"), ("exec", "example-tool", "--", "literal"),
                    ("shell", "--", "printf", "literal"), ("prefer", "example-tool", "parrot"),
                    ("prefer", "example-tool", "--clear"))
        with patch.object(cli, "require_runtime") as runtime, patch.object(cli.subprocess, "Popen") as process, \
                patch.object(cli.subprocess, "run") as capture:
            for command in commands:
                with self.subTest(command=command):
                    code, output, error = self.invoke("--dry-run", *command)
                    self.assertEqual(code, 0, error)
                    self.assertEqual(json.loads(output)["command"], command[0])
                    self.assertEqual(list(self.root.iterdir()), [])
        runtime.assert_not_called()
        process.assert_not_called()
        capture.assert_not_called()

    def test_discovery_keeps_alias_argv0_but_excludes_original_and_resolved_host_paths(self):
        container = copy.deepcopy(self.containers["kali"])
        container["Mounts"] += [{"Type": "bind", "Destination": "/usr/local/bin"},
                                {"Type": "bind", "Destination": "/opt/host"},
                                {"Type": "bind", "Destination": "/home/user"}]
        triples = [("alias", "/usr/bin/alias", "/usr/bin/multicall"),
                   ("alias", "/opt/second/alias", "/opt/second/alias"),
                   ("host-original", "/usr/local/bin/host-original", "/usr/bin/real"),
                   ("host-target", "/usr/bin/host-target", "/opt/host/real"),
                   ("host-home", "/usr/bin/host-home", "/home/user/tool"),
                   ("traversal", "/usr/bin/../bin/traversal", "/usr/bin/traversal"),
                   ("invalid name", "/usr/bin/odd", "/usr/bin/odd"),
                   ("safe-neighbor", "/opt/host-tools/safe", "/opt/host-tools/safe")]
        output = "Distrobox startup notice\n" + tooling.MARKER + "".join("\x00".join(item) + "\x00" for item in triples)
        self.assertEqual(tooling.parse_inventory(output, container),
                         {"alias": "/usr/bin/alias", "safe-neighbor": "/opt/host-tools/safe"})

    def test_discovery_rejects_missing_or_truncated_marker_protocol(self):
        for output in ("startup failed", tooling.MARKER + "name\x00/path\x00", tooling.MARKER + "name\x00/path\x00/target"):
            with self.subTest(output=output), self.assertRaises(cli.CommandError):
                tooling.parse_inventory(output, self.containers["kali"])

    def test_discovery_argv_has_clean_path_and_no_host_path_directories(self):
        container = copy.deepcopy(self.containers["kali"])
        container["Config"]["Env"] = ["PATH=/home/user/bin:/workspace:/usr/local/bin:/opt/image/bin:/usr/bin"]
        container["Mounts"].append({"Type": "bind", "Destination": "/usr/local/bin"})
        container["Mounts"].append({"Type": "bind", "Destination": "/home/user"})
        argv = tooling.discover_argv("kali", container)
        self.assertIn("--clean-path", argv)
        directories = argv[argv.index("flagship-inventory") + 1:]
        self.assertIn("/opt/image/bin", directories)
        for path in ("/home/user/bin", "/workspace", "/usr/local/bin"):
            self.assertNotIn(path, directories)

    def test_changed_container_image_or_installation_rejects_cache_before_execution(self):
        self.save_inventory()
        for field in ("container_id", "image_id", "installation_id"):
            altered = copy.deepcopy(self.inventory)
            altered["profiles"]["kali"][field] = "different"
            cli.atomic_json(self.ctx.state_dir / "inventory.json", altered)
            with self.subTest(field=field), patch.object(cli, "require_runtime"), \
                    patch.object(cli, "managed_container", side_effect=self.provider), patch.object(cli, "stream") as stream:
                code, _, error = self.invoke("exec", "example-tool")
                self.assertEqual(code, 1)
                self.assertIn("different container", error)
                stream.assert_not_called()

    def test_new_bind_mount_over_cached_executable_blocks_execution(self):
        self.save_inventory()
        self.containers["kali"]["Mounts"].append({"Type": "bind", "Destination": "/opt/kali"})
        with patch.object(cli, "require_runtime"), patch.object(cli, "managed_container", side_effect=self.provider), \
                patch.object(cli, "stream") as stream:
            code, _, error = self.invoke("exec", "example-tool")
        self.assertEqual(code, 1)
        self.assertIn("host mount", error)
        stream.assert_not_called()

    def test_exec_preserves_literal_arguments_exit_code_and_only_checks_selected_provider(self):
        self.save_inventory()
        literals = ["two words", "$(touch marker)", "x; literal", "*", "--profile", "parrot", "--dry-run"]
        child = Mock()
        child.wait.return_value = 37
        with patch.object(cli, "require_runtime"), patch.object(cli, "managed_container", side_effect=self.provider) as managed, \
                patch.object(cli.subprocess, "Popen", return_value=child) as process:
            code, _, error = self.invoke("exec", "--profile", "kali", "example-tool", "--", *literals)
        self.assertEqual(code, 37, error)
        argv = process.call_args.args[0]
        self.assertEqual(argv[argv.index("/opt/kali/bin/example-tool") + 1:], literals)
        self.assertIn("--clean-path", argv)
        self.assertFalse(process.call_args.kwargs.get("shell", False))
        self.assertNotIn("stdout", process.call_args.kwargs)
        self.assertNotIn("stderr", process.call_args.kwargs)
        self.assertEqual([call.args[1] for call in managed.call_args_list], ["kali"])
        self.assertFalse((self.root / "marker").exists())

    def test_current_workspace_subdirectory_maps_literally_and_outside_falls_back(self):
        subdir = self.ctx.workspace / "case with spaces" / "$(literal)"
        subdir.mkdir(parents=True)
        argv = tooling.exec_argv(self.ctx, "kali", "/usr/bin/example", ["file name"], cwd=subdir)
        self.assertEqual(argv[argv.index("--") + 1:],
                         ["/usr/bin/env", "--chdir=/workspace/case with spaces/$(literal)", "/usr/bin/example", "file name"])
        outside = tooling.exec_argv(self.ctx, "kali", "/usr/bin/example", [], cwd=self.root)
        self.assertIn("--chdir=/workspace", outside)

    def test_preferences_round_trip_clear_and_unavailable_provider_preserves_existing_state(self):
        self.save_inventory()
        with patch.object(cli, "require_runtime"), patch.object(cli, "managed_container", side_effect=self.provider), \
                patch.object(cli, "state_lock", side_effect=lambda ctx: contextlib.nullcontext()):
            code, _, error = self.invoke("prefer", "example-tool", "parrot")
            self.assertEqual(code, 0, error)
            self.assertEqual(tooling.preferences(self.ctx, self.catalog), {"example-tool": "parrot"})
            original = (self.ctx.state_dir / "preferences.json").read_bytes()
            code, _, _ = self.invoke("prefer", "missing-tool", "kali")
            self.assertEqual(code, 127)
            self.assertEqual((self.ctx.state_dir / "preferences.json").read_bytes(), original)
            code, _, error = self.invoke("prefer", "example-tool", "--clear")
            self.assertEqual(code, 0, error)
            self.assertEqual(tooling.preferences(self.ctx, self.catalog), {})

    def test_refresh_container_replacement_does_not_overwrite_last_good_inventory(self):
        self.save_inventory()
        original = (self.ctx.state_dir / "inventory.json").read_bytes()
        cli.atomic_json(self.ctx.record_path("kali"), self.records["kali"])
        replaced = copy.deepcopy(self.containers["kali"])
        replaced["Id"] = "9" * 64
        output = tooling.MARKER + "example\x00/usr/bin/example\x00/usr/bin/example\x00"
        with patch.object(cli, "state_lock", side_effect=lambda ctx: contextlib.nullcontext()), \
                patch.object(cli, "managed_container", side_effect=[self.provider(self.ctx, "kali"), (replaced, self.records["kali"])]), \
                patch.object(cli, "capture", return_value=subprocess.CompletedProcess([], 0, output, "")), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(cli.CommandError, "changed during discovery"):
                tooling.refresh_inventory(self.ctx, self.catalog)
        self.assertEqual((self.ctx.state_dir / "inventory.json").read_bytes(), original)

    def test_refresh_skips_prepared_images_without_created_containers(self):
        cli.atomic_json(self.ctx.record_path("kali"), self.records["kali"])
        cli.atomic_json(self.ctx.record_path("parrot"), {**self.records["parrot"], "status": "prepared"})
        output = tooling.MARKER + "example\x00/usr/bin/example\x00/usr/bin/example\x00"
        def only_created(ctx, profile):
            self.assertEqual(profile, "kali", "Prepared-only images have no running environment to discover")
            return self.provider(ctx, profile)
        with patch.object(cli, "state_lock", side_effect=lambda ctx: contextlib.nullcontext()), \
                patch.object(cli, "managed_container", side_effect=only_created), \
                patch.object(cli, "capture", return_value=subprocess.CompletedProcess([], 0, output, "")) as capture, \
                contextlib.redirect_stderr(io.StringIO()):
            inventory = tooling.refresh_inventory(self.ctx, self.catalog)
        self.assertEqual(list(inventory["profiles"]), ["kali"])
        capture.assert_called_once()

    def test_malformed_cached_paths_are_rejected_without_backend(self):
        for path in ("/run/host/example", "/workspace/example", "/usr/../home/example", "/usr/bin/example\x00evil"):
            self.inventory["profiles"]["kali"]["tools"]["example-tool"] = path
            self.save_inventory()
            with self.subTest(path=path), patch.object(cli, "managed_container") as managed:
                with self.assertRaises(cli.CommandError):
                    tooling.load_inventory(self.ctx, self.catalog)
                managed.assert_not_called()

    def test_image_home_tools_are_indexed_while_global_host_home_and_aliases_are_excluded(self):
        container = copy.deepcopy(self.containers["kali"])
        container["Mounts"].append({"Type": "bind", "Destination": "/home/hostuser"})
        triples = [("image-user-tool", "/home/imageuser/.local/bin/tool", "/home/imageuser/.local/bin/tool"),
                   ("image-root-tool", "/root/.local/bin/tool", "/root/.local/bin/tool"),
                   ("host-user-tool", "/home/hostuser/bin/tool", "/home/hostuser/bin/tool"),
                   ("host-alias", "/usr/bin/host-alias", "/home/hostuser/bin/tool")]
        output = tooling.MARKER + "".join("\x00".join(item) + "\x00" for item in triples)
        self.assertEqual(tooling.parse_inventory(output, container), {
            "image-root-tool": "/root/.local/bin/tool", "image-user-tool": "/home/imageuser/.local/bin/tool"})

    @unittest.skipUnless(sys.platform == "linux", "Private profile homes use Linux paths")
    def test_verified_private_home_tools_are_indexed_but_nested_host_binds_are_excluded(self):
        home = str(self.ctx.home("kali"))
        container = copy.deepcopy(self.containers["kali"])
        container["Mounts"] += [{"Type": "bind", "Destination": home, "Source": home, "RW": True},
                                {"Type": "bind", "Destination": home + "/external", "Source": "/unrelated-host-dir"},
                                {"Type": "bind", "Destination": "/home/hostuser"}]
        record = {**self.records["kali"], "home": home}
        self.assertEqual(tooling.managed_home(self.ctx, "kali", container, record), home)
        triples = [("private-tool", home + "/.local/bin/tool", home + "/.local/bin/tool"),
                   ("nested-host-tool", home + "/external/tool", home + "/external/tool"),
                   ("nested-host-alias", home + "/bin/alias", home + "/external/tool"),
                   ("other-host-alias", home + "/bin/other-alias", "/home/hostuser/tool")]
        output = tooling.MARKER + "".join("\x00".join(item) + "\x00" for item in triples)
        self.assertEqual(tooling.parse_inventory(output, container, home),
                         {"private-tool": home + "/.local/bin/tool"})
        self.assertEqual(tooling.parse_inventory(output, container), {})

    @unittest.skipUnless(sys.platform == "linux", "Private profile homes use Linux paths")
    def test_home_mount_source_and_cached_home_drift_block_dispatch(self):
        home = str(self.ctx.home("kali"))
        self.records["kali"]["home"] = home
        mount = {"Type": "bind", "Destination": home, "Source": home, "RW": True}
        self.containers["kali"]["Mounts"].append(mount)
        self.inventory["profiles"]["kali"]["home"] = home
        self.save_inventory()
        with patch.object(cli, "require_runtime"), patch.object(cli, "managed_container", side_effect=self.provider), \
                patch.object(cli, "stream") as stream:
            mount["Source"] = str(self.root / "unrelated")
            code, _, error = self.invoke("exec", "example-tool")
            self.assertEqual(code, 1)
            self.assertIn("private home mount differs", error)
            mount["Source"] = home
            self.inventory["profiles"]["kali"]["home"] = str(self.root / "old-home")
            self.save_inventory()
            code, _, error = self.invoke("exec", "example-tool")
            self.assertEqual(code, 1)
            self.assertIn("home has changed", error)
            stream.assert_not_called()

    def test_host_path_removes_prior_session_shims_but_preserves_host_priority(self):
        old = self.ctx.state_dir / "shells" / "session-old"
        host = self.root / "hostbin"
        similar = self.ctx.state_dir / "shells-neighbor"
        with patch.dict(os.environ, {"PATH": os.pathsep.join([str(host), str(old), "", str(similar)])}):
            self.assertEqual(tooling.host_path(self.ctx), os.pathsep.join([str(host), str(similar)]))

    @unittest.skipUnless(sys.platform == "linux", "Private symlink shim sessions are a Linux runtime feature")
    def test_shell_shims_are_private_append_after_host_commands_and_clean_up(self):
        self.ctx.workspace.mkdir()
        original_path = os.environ.get("PATH", "")
        old = self.ctx.state_dir / "shells" / "session-old"
        seen = []
        def inspect_session(argv, *, env, cwd):
            self.assertEqual(argv, ["printf", "%s", "literal"])
            self.assertEqual(cwd, self.ctx.workspace)
            self.assertEqual(env["FLAGSHIP_ACTIVE"], "1")
            self.assertNotIn(str(old), env["PATH"].split(os.pathsep))
            shimdir = Path(env["PATH"].split(os.pathsep)[-1])
            seen.append(shimdir)
            self.assertEqual(stat.S_IMODE(shimdir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((shimdir / ".dispatch").stat().st_mode), 0o700)
            self.assertEqual(os.readlink(shimdir / "example-tool"), ".dispatch")
            dispatch = (shimdir / ".dispatch").read_text()
            self.assertIn("-m flagship", dispatch)
            self.assertIn(str(Path(sys.executable).absolute()), dispatch)
            self.assertIn('"$tool" -- "$@"', dispatch)
            self.assertEqual(env["PATH"].split(os.pathsep)[:-1], original_path.split(os.pathsep))
            return 23
        with patch.dict(os.environ, {"PATH": original_path + os.pathsep + str(old)}), \
                patch.object(cli, "stream", side_effect=inspect_session):
            self.assertEqual(tooling.shell(self.ctx, self.inventory, ["--", "printf", "%s", "literal"]), 23)
        self.assertTrue(seen)
        self.assertFalse(seen[0].exists())

    @unittest.skipUnless(sys.platform == "linux", "Private symlink shim sessions are a Linux runtime feature")
    def test_shell_cleans_private_session_when_child_launch_fails(self):
        self.ctx.workspace.mkdir()
        with patch.object(cli, "stream", side_effect=OSError("fixture launch failure")):
            with self.assertRaises(OSError):
                tooling.shell(self.ctx, self.inventory, ["printf", "literal"])
        self.assertEqual(list((self.ctx.state_dir / "shells").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
