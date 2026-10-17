"""Behavioral tests for planning, ownership, subprocesses and durable state."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flagship import cli


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flagship-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ctx = cli.Context(self.root / "state", self.root / "workspace")
        self.base = ["--state-dir", str(self.ctx.state_dir), "--workspace", str(self.ctx.workspace)]

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(self.base + list(args))
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def seed_owned(self, profile="kali", instance="290f1491-5122-446c-aaef-baf18110e128"):
        record = {
            "schema_version": 1, "profile": profile, "container": f"flagship-{profile}",
            "installation_id": instance, "image": "docker.io/example/image@sha256:" + "a" * 64,
            "image_id": "sha256:" + "b" * 64,
            "workspace": str(self.ctx.workspace), "home": str(self.ctx.home(profile)), "status": "created",
        }
        cli.atomic_json(self.ctx.state_dir / "install.json", {"schema_version": 1, "installation_id": instance})
        cli.atomic_json(self.ctx.record_path(profile), record)
        return {"Id": "fixture-container-id", "Image": "sha256:" + "b" * 64,
                "Mounts": [{"Type": "bind", "Source": str(self.ctx.workspace), "Destination": "/workspace", "RW": True}],
                "Config": {"Labels": {
            f"{cli.LABEL}.managed": "true",
            f"{cli.LABEL}.installation": instance,
            f"{cli.LABEL}.profile": profile,
        }}, "State": {"Status": "running"}}

    def test_help_does_not_need_runtime_or_write_state(self):
        with patch.object(cli, "require_runtime") as runtime:
            code, output, _ = self.invoke("--help")
        self.assertEqual(code, 0)
        self.assertIn("flagship", output)
        runtime.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_profiles_is_machine_readable_without_runtime(self):
        with patch.object(cli, "require_runtime") as runtime:
            code, output, _ = self.invoke("profiles", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output)["profiles"]), 7)
        runtime.assert_not_called()
        self.assertFalse(self.ctx.state_dir.exists())

    def test_unknown_and_unsafe_profiles_fail_before_any_mutation(self):
        with patch.object(cli, "require_runtime") as runtime, patch.object(cli, "stream") as stream:
            for profile in ("unknown", "../kali", "kali;echo-literal", "Kali", "kali/other"):
                with self.subTest(profile=profile):
                    code, _, error = self.invoke("create", profile)
                    self.assertEqual(code, 2)
                    self.assertIn("Unknown profile", error)
        runtime.assert_not_called()
        stream.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_plans_and_dry_runs_never_invoke_runtime_or_create_files(self):
        commands = [
            ("plan", "kali"), ("plan", "sift"),
            ("--dry-run", "create", "parrot"), ("create", "kali", "--dry-run"),
            ("--dry-run", "provision", "kali"),
            ("--dry-run", "run", "kali", "--", "printf", "%s", "literal"),
            ("--dry-run", "remove", "kali"),
            ("--dry-run", "import-rootfs", "caine", "not-created.tar", "--sha256", "a" * 64),
        ]
        with patch.object(cli.subprocess, "run") as capture, patch.object(cli.subprocess, "Popen") as stream:
            for command in commands:
                with self.subTest(command=command):
                    code, output, error = self.invoke(*command)
                    self.assertEqual(code, 0, error)
                    self.assertIsInstance(json.loads(output)["steps"], list)
                    self.assertEqual(list(self.root.iterdir()), [])
        capture.assert_not_called()
        stream.assert_not_called()

    def test_literal_run_arguments_survive_plan_and_process_launch(self):
        arguments = ["printf", "%s\n", "a b", "$(printf literal)", "; echo literal", "*", "--dry-run"]
        code, output, error = self.invoke("--dry-run", "run", "kali", "--", *arguments)
        self.assertEqual(code, 0, error)
        planned = json.loads(output)["steps"][0]["argv"]
        delimiter = planned.index("--")
        self.assertEqual(planned[delimiter + 1:], arguments)
        child = Mock()
        child.wait.return_value = 37
        with patch.object(cli, "require_runtime"), patch.object(cli, "managed_container"), \
                patch.object(cli.subprocess, "Popen", return_value=child) as process:
            code, _, error = self.invoke("run", "kali", "--", *arguments)
        self.assertEqual(code, 37, error)
        self.assertEqual(process.call_args.args[0], planned)
        self.assertFalse(process.call_args.kwargs.get("shell", False))
        self.assertEqual(process.call_args.kwargs["env"]["DBX_CONTAINER_MANAGER"], "podman")

    def test_empty_run_command_and_unconfirmed_remove_have_usage_exit_code(self):
        with patch.object(cli, "require_runtime") as runtime:
            for command in (("run", "kali", "--"), ("remove", "kali")):
                with self.subTest(command=command):
                    self.assertEqual(self.invoke(*command)[0], 2)
        runtime.assert_not_called()

    def test_runtime_missing_binary_returns_operational_error(self):
        with patch.object(cli, "require_runtime", side_effect=cli.CommandError("Missing Podman")):
            code, _, error = self.invoke("create", "kali")
        self.assertEqual(code, 1)
        self.assertIn("Missing Podman", error)
        self.assertFalse(self.ctx.state_dir.exists())

    def test_foreign_container_cannot_be_run_or_removed(self):
        container = self.seed_owned()
        container["Config"]["Labels"][f"{cli.LABEL}.installation"] = "someone-else"
        original = self.ctx.record_path("kali").read_bytes()
        with patch.object(cli, "require_runtime"), \
                patch.object(cli, "state_lock", side_effect=lambda ctx: contextlib.nullcontext()), \
                patch.object(cli, "inspect_container", return_value=container), \
                patch.object(cli, "stream") as stream:
            for command in (("run", "kali", "--", "true"), ("remove", "kali", "--yes")):
                with self.subTest(command=command):
                    code, _, error = self.invoke(*command)
                    self.assertEqual(code, 1)
                    self.assertIn("foreign", error)
        stream.assert_not_called()
        self.assertEqual(self.ctx.record_path("kali").read_bytes(), original)

    def test_matching_labels_without_local_manifest_do_not_establish_ownership(self):
        container = self.seed_owned()
        self.ctx.record_path("kali").unlink()
        with self.assertRaisesRegex(cli.CommandError, "foreign"):
            cli.ensure_owned(self.ctx, "kali", container)

    def test_repeated_create_reuses_owned_container_without_pull_or_rewrite(self):
        container = self.seed_owned()
        original = self.ctx.record_path("kali").read_bytes()
        with patch.object(cli, "inspect_container", return_value=container), \
                patch.object(cli, "checked_stream") as stream, patch.object(cli, "atomic_json") as write, \
                contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                self.assertEqual(cli.create(self.ctx, "kali", cli.load_catalog()["kali"]), 0)
        stream.assert_not_called()
        write.assert_not_called()
        self.assertEqual(self.ctx.record_path("kali").read_bytes(), original)

    def test_create_rejects_workspace_change_for_existing_container(self):
        container = self.seed_owned()
        other = cli.Context(self.ctx.state_dir, self.root / "other-workspace")
        with patch.object(cli, "inspect_container", return_value=container), patch.object(cli, "checked_stream") as stream:
            with self.assertRaisesRegex(cli.CommandError, "different workspace"):
                cli.create(other, "kali", cli.load_catalog()["kali"])
        stream.assert_not_called()

    def test_rootfs_checksum_fails_before_import_and_manifest_write(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        archive = self.root / "rootfs.tar"
        archive.write_bytes(b"known archive fixture")
        args = argparse.Namespace(profile="caine", path=str(archive), sha256="0" * 64)
        with patch.object(cli, "inspect_container", return_value=None), \
                patch.object(cli, "checked_stream") as stream, patch.object(cli, "atomic_json") as write:
            with self.assertRaisesRegex(cli.CommandError, "SHA-256 mismatch"):
                cli.import_rootfs(self.ctx, args, cli.load_catalog()["caine"])
        stream.assert_not_called()
        write.assert_not_called()
        self.assertEqual(list(self.ctx.state_dir.iterdir()), [])

    def test_import_streams_verified_snapshot_after_source_mutates(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        archive = self.root / "rootfs.tar"
        payload = b"known archive fixture"
        archive.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        args = argparse.Namespace(profile="caine", path=str(archive), sha256=digest)
        captured = []

        def stream(argv, *, stdin=None):
            archive.write_bytes(b"unverified changed source bytes")
            captured.append((argv, stdin.read()))

        image = "sha256:" + "b" * 64
        with patch.object(cli, "inspect_container", return_value=None), \
                patch.object(cli, "checked_stream", side_effect=stream), \
                patch.object(cli, "image_identity", return_value=image), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.import_rootfs(self.ctx, args, cli.load_catalog()["caine"]), 0)
        self.assertEqual(captured[0][1], payload)
        self.assertEqual(archive.read_bytes(), b"unverified changed source bytes")
        self.assertIn("-", captured[0][0])
        manifest = json.loads(self.ctx.record_path("caine").read_text())
        self.assertEqual(manifest["archive_sha256"], digest)
        self.assertEqual(manifest["imported_image"], image)

    def test_configuration_drift_prevents_reuse_and_command_execution(self):
        for drift in ("image", "workspace", "read-only", "duplicate", "wrong-type"):
            for command in (("create", "kali"), ("run", "kali", "--", "true"), ("provision", "kali"), ("check", "kali")):
                with self.subTest(drift=drift, command=command):
                    container = self.seed_owned()
                    if drift == "image":
                        container["Image"] = "sha256:" + "c" * 64
                    elif drift == "workspace":
                        container["Mounts"][0]["Source"] = str(self.root / "other")
                    elif drift == "read-only":
                        container["Mounts"][0]["RW"] = False
                    elif drift == "duplicate":
                        container["Mounts"].append(dict(container["Mounts"][0]))
                    else:
                        container["Mounts"][0]["Type"] = "volume"
                    with patch.object(cli, "require_runtime"), \
                            patch.object(cli, "state_lock", side_effect=lambda ctx: contextlib.nullcontext()), \
                            patch.object(cli, "inspect_container", return_value=container), patch.object(cli, "stream") as stream:
                        code, _, error = self.invoke(*command)
                    self.assertEqual(code, 1, error)
                    self.assertIn("differs", error)
                    stream.assert_not_called()

    def test_drifted_owned_container_can_still_be_removed(self):
        container = self.seed_owned()
        container["Image"] = "sha256:" + "c" * 64
        container["Mounts"] = []
        with patch.object(cli, "require_runtime"), \
                patch.object(cli, "state_lock", side_effect=lambda ctx: contextlib.nullcontext()), \
                patch.object(cli, "inspect_container", side_effect=[container, None]), \
                patch.object(cli, "checked_stream") as stream:
            code, _, error = self.invoke("remove", "kali", "--yes")
        self.assertEqual(code, 0, error)
        stream.assert_called_once_with(["distrobox", "rm", "--force", "flagship-kali"])
        self.assertEqual(json.loads(self.ctx.record_path("kali").read_text())["status"], "removed")

    def test_capture_never_uses_a_shell_and_preserves_exit_code(self):
        argv = ["podman", "inspect", "literal; argument"]
        result = subprocess.CompletedProcess(argv, 23, "", "fixture failure")
        with patch.object(cli.subprocess, "run", return_value=result) as run:
            with self.assertRaises(cli.CommandError) as failure:
                cli.capture(argv)
        self.assertEqual(failure.exception.code, 23)
        self.assertEqual(run.call_args.args[0], argv)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_signal_exit_code_is_shell_compatible(self):
        child = Mock()
        child.wait.return_value = -15
        with patch.object(cli.subprocess, "Popen", return_value=child):
            self.assertEqual(cli.stream(["fixture"]), 143)

    def test_atomic_write_failure_keeps_previous_state_and_cleans_temporary(self):
        target = self.root / "manifest.json"
        target.write_text('{"version": 1}\n')
        previous = target.read_bytes()
        with patch.object(cli.os, "replace", side_effect=OSError("fixture replace failure")):
            with self.assertRaises(OSError):
                cli.atomic_json(target, {"version": 2})
        self.assertEqual(target.read_bytes(), previous)
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_atomic_write_publishes_complete_json(self):
        target = self.root / "manifest.json"
        cli.atomic_json(target, {"version": 1, "values": list(range(50))})
        self.assertEqual(json.loads(target.read_text())["values"], list(range(50)))
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_engine_error_is_not_misreported_as_absent_container(self):
        results = [
            subprocess.CompletedProcess([], 125, "", "engine unavailable"),
            subprocess.CompletedProcess([], 125, "", "engine unavailable"),
        ]
        with patch.object(cli, "capture", side_effect=results):
            with self.assertRaisesRegex(cli.CommandError, "Cannot inspect"):
                cli.inspect_container("flagship-kali")

    def test_rootful_engine_rejected_before_container_creation(self):
        result = subprocess.CompletedProcess([], 0, '{"host":{"security":{"rootless":false}}}', "")
        with patch.object(cli.sys, "platform", "linux"), patch.object(cli.os, "geteuid", return_value=1000, create=True), \
                patch.object(cli.shutil, "which", return_value="/usr/bin/tool"), patch.object(cli, "capture", return_value=result):
            with self.assertRaisesRegex(cli.CommandError, "rootless"):
                cli.require_runtime()

    def test_corrupt_state_is_a_readable_error(self):
        target = self.root / "state.json"
        for content in ("not json", "[]", '"string"', "null"):
            with self.subTest(content=content):
                target.write_text(content)
                with self.assertRaisesRegex(cli.CommandError, "Cannot read state"):
                    cli.read_json(target)

    def test_invalid_installation_identity_is_rejected(self):
        for identity in ("not-a-uuid", None, 5, "../../other"):
            with self.subTest(identity=identity):
                cli.atomic_json(self.ctx.state_dir / "install.json", {"schema_version": 1, "installation_id": identity})
                with self.assertRaisesRegex(cli.CommandError, "Invalid installation"):
                    cli.installation(self.ctx)


class CatalogValidationTests(unittest.TestCase):
    def test_malformed_catalog_values_fail_as_command_errors(self):
        base = {"kind": "registry", "name": "Fixture", "image": "docker.io/example/image:tag", "packages": []}
        invalid = [
            {"schema_version": 2, "profiles": {}},
            {"schema_version": 1, "profiles": {"../unsafe": base}},
            {"schema_version": 1, "profiles": {"kali": []}},
            {"schema_version": 1, "profiles": {"kali": {**base, "packages": [5]}}},
            {"schema_version": 1, "profiles": {"kali": {**base, "packages": ["--option"]}}},
            {"schema_version": 1, "profiles": {"kali": {**base, "packages": ["package;literal"]}}},
            {"schema_version": 1, "profiles": {"kali": {**base, "packages": "package"}}},
            {"schema_version": 1, "profiles": {"kali": {**base, "smoke_commands": [[5]]}}},
            {"schema_version": 1, "profiles": {"kali": {**base, "image": "image with spaces"}}},
        ]
        for catalog in invalid:
            with self.subTest(catalog=catalog):
                resource = Mock()
                resource.joinpath.return_value.read_text.return_value = json.dumps(catalog)
                with patch.object(cli, "files", return_value=resource):
                    with self.assertRaises(cli.CommandError):
                        cli.load_catalog()


class ImageIdentityTests(unittest.TestCase):
    def resolve(self, reference, info, registry=True):
        result = subprocess.CompletedProcess([], 0, json.dumps([info]), "")
        with patch.object(cli, "capture", return_value=result):
            return cli.image_identity(reference, registry=registry)

    def test_pinned_manifest_reference_is_preserved(self):
        reference = "docker.io/example/image@sha256:" + "a" * 64
        platform_digest = "docker.io/example/image@sha256:" + "b" * 64
        self.assertEqual(self.resolve(reference, {"RepoDigests": [platform_digest]}), reference)

    def test_tag_is_resolved_to_digest_from_requested_repository(self):
        expected = "docker.io/example/image@sha256:" + "a" * 64
        unrelated = "docker.io/another/image@sha256:" + "b" * 64
        self.assertEqual(self.resolve("docker.io/example/image:tag", {"RepoDigests": [unrelated, expected]}), expected)

    def test_missing_or_malformed_digest_is_rejected(self):
        for digests in ([], ["docker.io/example/image:latest"], ["image@sha256:short"], [None]):
            with self.subTest(digests=digests), self.assertRaisesRegex(cli.CommandError, "immutable RepoDigest"):
                self.resolve("docker.io/example/image:tag", {"RepoDigests": digests})

    def test_ambiguous_unrelated_digests_are_rejected(self):
        digests = ["docker.io/first/image@sha256:" + "a" * 64, "docker.io/second/image@sha256:" + "b" * 64]
        with self.assertRaisesRegex(cli.CommandError, "Ambiguous"):
            self.resolve("docker.io/example/image:tag", {"RepoDigests": digests})

    def test_import_requires_valid_content_id(self):
        expected = "sha256:" + "c" * 64
        self.assertEqual(self.resolve("localhost/fixture", {"Id": expected}, registry=False), expected)
        for image_id in (None, "short", "sha256:" + "z" * 64, "c" * 63, "c" * 65, "z" * 64):
            with self.subTest(image_id=image_id), self.assertRaisesRegex(cli.CommandError, "immutable image ID"):
                self.resolve("localhost/fixture", {"Id": image_id}, registry=False)

    def test_podman_raw_content_id_is_normalized_for_both_field_spellings(self):
        raw_id = "d" * 64
        for field in ("Id", "ID"):
            for value in (raw_id, "sha256:" + raw_id):
                with self.subTest(field=field, value=value):
                    self.assertEqual(
                        self.resolve("localhost/fixture", {field: value}, registry=False),
                        "sha256:" + raw_id,
                    )


@unittest.skipUnless(sys.platform == "linux", "POSIX file locking requires Linux")
class StateLockTests(unittest.TestCase):
    def test_lock_blocks_a_second_process_until_released(self):
        with tempfile.TemporaryDirectory(prefix="flagship-lock-tests-") as directory:
            root = Path(directory)
            ctx = cli.Context(root / "state", root / "workspace")
            marker = root / "acquired"
            ready = root / "ready"
            script = "\n".join([
                "import sys", "from pathlib import Path",
                f"sys.path.insert(0, {str(Path(cli.__file__).resolve().parents[1])!r})",
                "from flagship.cli import Context, state_lock",
                "ctx = Context(Path(sys.argv[1]), Path(sys.argv[2]))",
                "Path(sys.argv[4]).write_text('ready')",
                "with state_lock(ctx):", "    Path(sys.argv[3]).write_text('acquired')",
            ])
            child = None
            try:
                with cli.state_lock(ctx):
                    child = subprocess.Popen([sys.executable, "-c", script, str(ctx.state_dir), str(ctx.workspace), str(marker), str(ready)])
                    import time
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), "child never reached lock acquisition")
                    with self.assertRaises(subprocess.TimeoutExpired):
                        child.wait(timeout=0.15)
                    self.assertFalse(marker.exists())
                self.assertEqual(child.wait(timeout=5), 0)
                self.assertEqual(marker.read_text(), "acquired")
            finally:
                if child is not None and child.poll() is None:
                    child.kill()
                    child.wait()

    def test_insecure_state_directory_permissions_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="flagship-mode-tests-") as directory:
            root = Path(directory)
            state = root / "state"
            state.mkdir(mode=0o755)
            state.chmod(0o755)
            with self.assertRaisesRegex(cli.CommandError, "0700"):
                with cli.state_lock(cli.Context(state, root / "workspace")):
                    self.fail("insecure state lock was accepted")


if __name__ == "__main__":
    unittest.main()
