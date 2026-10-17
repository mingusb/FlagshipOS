"""Preparation publishes a recipe receipt only after a successful immutable build."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from flagship import cli, preparation


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flagship-prepare-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ctx = cli.Context(self.root / "state", self.root / "workspace")
        self.recipe = b"FROM scratch\nLABEL fixture=benign\n"
        self.image_id = "sha256:" + "a" * 64

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["--state-dir", str(self.ctx.state_dir), "--workspace", str(self.ctx.workspace), *arguments]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(argv)
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_dry_run_reads_bundled_recipe_without_runtime_state_or_build(self):
        with patch.object(preparation, "load_recipe", return_value=self.recipe), \
                patch.object(cli, "require_runtime") as runtime, patch.object(cli.subprocess, "run") as capture, \
                patch.object(cli.subprocess, "Popen") as process:
            code, output, error = self.invoke("--dry-run", "prepare", "kali")
        self.assertEqual(code, 0, error)
        self.assertIn(hashlib.sha256(self.recipe).hexdigest(), output)
        self.assertIn("podman", output)
        self.assertIsInstance(json.loads(output), dict)
        runtime.assert_not_called()
        capture.assert_not_called()
        process.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_recipe_and_arbitrary_recipe_option_fail_without_build(self):
        with patch.object(cli, "require_runtime") as runtime, patch.object(cli, "checked_stream") as build:
            code, _, error = self.invoke("prepare", "caine")
            self.assertNotEqual(code, 0)
            self.assertIn("recipe", error.lower())
            self.assertEqual(self.invoke("prepare", "kali", "--recipe", "arbitrary.Containerfile")[0], 2)
        runtime.assert_not_called()
        build.assert_not_called()
        self.assertFalse(self.ctx.record_path("caine").exists())

    def test_existing_container_refuses_rebuild_before_private_context_creation(self):
        with patch.object(cli, "inspect_container", return_value={"Id": "existing"}), \
                patch.object(cli, "checked_stream") as build, patch.object(preparation.tempfile, "TemporaryDirectory") as temporary:
            with self.assertRaisesRegex(cli.CommandError, "existing|Remove|remove"):
                preparation.prepare(self.ctx, "kali", self.recipe)
        build.assert_not_called()
        temporary.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_selected_network_helper_stops_prepare_before_lock_or_build(self):
        info = {"host": {"security": {"rootless": True}, "rootlessNetworkCmd": "pasta"}}
        def which(name):
            return "/usr/bin/" + name if name in ("podman", "distrobox", "slirp4netns") else None
        with patch.object(preparation, "load_recipe", return_value=self.recipe), \
                patch.object(cli.sys, "platform", "linux"), patch.object(cli.os, "geteuid", return_value=1000, create=True), \
                patch.object(cli.shutil, "which", side_effect=which), \
                patch.object(cli, "capture", return_value=subprocess.CompletedProcess([], 0, json.dumps(info), "")) as capture, \
                patch.object(cli, "state_lock") as lock, patch.object(cli, "checked_stream") as build:
            with self.assertRaisesRegex(cli.CommandError, "passt"):
                preparation.main(self.ctx, "kali")
        capture.assert_called_once_with(["podman", "info", "--format", "json"])
        lock.assert_not_called()
        build.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_doctor_reports_missing_pasta_even_when_slirp_is_installed(self):
        info = {"host": {"security": {"rootless": True}, "rootlessNetworkCmd": "pasta"}}
        with patch.object(cli.sys, "platform", "linux"), patch.object(cli.os, "geteuid", return_value=1000, create=True), \
                patch.object(cli.shutil, "which", side_effect=lambda name: None if name == "pasta" else "/usr/bin/" + name), \
                patch.object(cli, "capture", return_value=subprocess.CompletedProcess([], 0, json.dumps(info), "")):
            code, output, _ = self.invoke("doctor", "--json")
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertTrue(result["checks"]["rootless"])
        self.assertFalse(result["checks"]["rootless_network"])
        self.assertIn("pasta", result["details"]["rootless_network"])
        self.assertIn("passt", result["details"]["rootless_network"])

    def test_success_builds_exact_recipe_in_private_empty_context_and_cleans_it(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        contexts = []
        def build(argv, **kwargs):
            self.assertEqual(argv[:2], ["podman", "build"])
            context = Path(argv[-1])
            contexts.append(context)
            self.assertEqual(context.parent, self.ctx.state_dir)
            if sys.platform == "linux":
                self.assertEqual(stat.S_IMODE(context.stat().st_mode), 0o700)
            self.assertEqual(sorted(item.name for item in context.iterdir()), ["Containerfile"])
            self.assertEqual((context / "Containerfile").read_bytes(), self.recipe)
            self.assertFalse(self.ctx.record_path("kali").exists())
            Path(argv[argv.index("--iidfile") + 1]).write_text(self.image_id.removeprefix("sha256:") + "\n")
        with patch.object(cli, "inspect_container", return_value=None), patch.object(cli, "checked_stream", side_effect=build), \
                patch.object(cli, "image_identity", return_value=self.image_id) as identity, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(preparation.prepare(self.ctx, "kali", self.recipe), 0)
        self.assertEqual(len(contexts), 1)
        self.assertFalse(contexts[0].exists())
        record = cli.read_json(self.ctx.record_path("kali"))
        self.assertEqual(cli.locked_image(record), self.image_id)
        self.assertEqual(record["recipe_sha256"], hashlib.sha256(self.recipe).hexdigest())
        self.assertEqual(record["status"], "prepared")
        self.assertEqual(identity.call_args.kwargs, {"registry": False})
        self.assertEqual(identity.call_args.args[0], self.image_id)

    def test_build_failure_has_no_prepared_receipt_and_cleans_context(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        contexts = []
        def fail(argv, **kwargs):
            contexts.append(Path(argv[-1]))
            raise cli.CommandError("fixture build failed", 37)
        with patch.object(cli, "inspect_container", return_value=None), patch.object(cli, "checked_stream", side_effect=fail), \
                patch.object(cli, "image_identity") as identity:
            with self.assertRaises(cli.CommandError) as error:
                preparation.prepare(self.ctx, "kali", self.recipe)
        self.assertEqual(error.exception.code, 37)
        identity.assert_not_called()
        self.assertFalse(self.ctx.record_path("kali").exists())
        self.assertTrue(contexts)
        self.assertFalse(contexts[0].exists())

    def test_image_inspection_failure_keeps_previous_receipt_and_cleans_context(self):
        previous = {"schema_version": 1, "status": "prepared", "imported_image": "sha256:" + "b" * 64,
                    "recipe_sha256": "c" * 64}
        cli.atomic_json(self.ctx.record_path("kali"), previous)
        original = self.ctx.record_path("kali").read_bytes()
        contexts = []
        def build(argv):
            contexts.append(Path(argv[-1]))
            Path(argv[argv.index("--iidfile") + 1]).write_text(self.image_id)
        with patch.object(cli, "inspect_container", return_value=None), \
                patch.object(cli, "checked_stream", side_effect=build), \
                patch.object(cli, "image_identity", side_effect=cli.CommandError("invalid image identity")):
            with self.assertRaisesRegex(cli.CommandError, "invalid image identity"):
                preparation.prepare(self.ctx, "kali", self.recipe)
        self.assertEqual(self.ctx.record_path("kali").read_bytes(), original)
        self.assertTrue(contexts)
        self.assertFalse(contexts[0].exists())

    def test_create_consumes_prepared_immutable_image_without_registry_pull(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        def build(argv):
            Path(argv[argv.index("--iidfile") + 1]).write_text(self.image_id)
        with patch.object(cli, "inspect_container", return_value=None), patch.object(cli, "checked_stream", side_effect=build), \
                patch.object(cli, "image_identity", return_value=self.image_id), contextlib.redirect_stdout(io.StringIO()):
            preparation.prepare(self.ctx, "kali", self.recipe)
        previous = cli.read_json(self.ctx.record_path("kali"))
        container = {"Image": self.image_id,
            "Config": {"Labels": {f"{cli.LABEL}.managed": "true", f"{cli.LABEL}.profile": "kali",
                                    f"{cli.LABEL}.installation": previous["installation_id"]}},
            "Mounts": [{"Type": "bind", "Source": str(self.ctx.workspace), "Destination": "/workspace", "RW": True}]}
        with patch.object(cli, "inspect_container", side_effect=[None, container]), \
                patch.object(cli, "checked_stream") as commands, \
                patch.object(cli, "image_identity", return_value=self.image_id), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.create(self.ctx, "kali", cli.load_catalog()["kali"]), 0)
        self.assertEqual(len(commands.call_args_list), 1)
        argv = commands.call_args.args[0]
        self.assertEqual(argv[:2], ["distrobox", "create"])
        self.assertEqual(argv[argv.index("--image") + 1], self.image_id)
        created = cli.read_json(self.ctx.record_path("kali"))
        self.assertEqual(created["recipe_sha256"], previous["recipe_sha256"])
        self.assertEqual(created["status"], "created")

    def test_missing_and_malformed_build_receipts_never_publish_prepared_image(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        for value in (None, "", "a" * 63, "sha256:" + "b" * 65, "sha256:" + "g" * 64,
                      "localhost/flagship/kali:mutable", "a" * 64 + "\n" + "b" * 64):
            contexts = []
            def build(argv):
                contexts.append(Path(argv[-1]))
                if value is not None:
                    Path(argv[argv.index("--iidfile") + 1]).write_text(value)
            with self.subTest(value=value), patch.object(cli, "inspect_container", return_value=None), \
                    patch.object(cli, "checked_stream", side_effect=build), patch.object(cli, "image_identity") as identity:
                with self.assertRaisesRegex(cli.CommandError, "valid immutable image ID"):
                    preparation.prepare(self.ctx, "kali", self.recipe)
                identity.assert_not_called()
                self.assertFalse(self.ctx.record_path("kali").exists())
                self.assertFalse(contexts[0].exists())

    def test_image_identity_must_match_private_build_receipt(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        contexts = []
        def build(argv):
            contexts.append(Path(argv[-1]))
            Path(argv[argv.index("--iidfile") + 1]).write_text(self.image_id)
        with patch.object(cli, "inspect_container", return_value=None), patch.object(cli, "checked_stream", side_effect=build), \
                patch.object(cli, "image_identity", return_value="sha256:" + "b" * 64):
            with self.assertRaisesRegex(cli.CommandError, "does not match"):
                preparation.prepare(self.ctx, "kali", self.recipe)
        self.assertFalse(self.ctx.record_path("kali").exists())
        self.assertFalse(contexts[0].exists())

    def test_mutable_recipe_tag_cannot_replace_image_from_private_build_receipt(self):
        self.ctx.state_dir.mkdir(mode=0o700)
        moved_tag = {}
        def build(argv):
            Path(argv[argv.index("--iidfile") + 1]).write_text(self.image_id)
            # Another build can move the shared tag after this build completed.
            moved_tag[argv[argv.index("--tag") + 1]] = "sha256:" + "b" * 64
        def inspect(reference, registry):
            self.assertFalse(registry)
            return moved_tag.get(reference, self.image_id)
        with patch.object(cli, "inspect_container", return_value=None), patch.object(cli, "checked_stream", side_effect=build), \
                patch.object(cli, "image_identity", side_effect=inspect) as identity, contextlib.redirect_stdout(io.StringIO()):
            preparation.prepare(self.ctx, "kali", self.recipe)
        identity.assert_called_once_with(self.image_id, registry=False)
        self.assertEqual(cli.locked_image(cli.read_json(self.ctx.record_path("kali"))), self.image_id)


if __name__ == "__main__":
    unittest.main()
