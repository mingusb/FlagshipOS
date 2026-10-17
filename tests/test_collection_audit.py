import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flagship import cli


script = Path(__file__).parent / "integration" / "full_collection_audit.py"
spec = importlib.util.spec_from_file_location("full_collection_audit", script)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class CollectionAuditTests(unittest.TestCase):
    def test_manifest_preserves_duplicate_architectures_and_residual_configuration(self):
        rows = audit.inventory("libc6:amd64\tlibc6\tamd64\t2.39\tii \n"
                               "libc6:i386\tlibc6\ti386\t2.39\thi \n"
                               "retired\tretired\tall\t1.0\trc \n")
        expected = audit.manifest("libc6 2.39\nlibc6 2.39\nretired 1.0\n")
        result = audit.compare_packages(expected, rows, installed_only=False)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["compared_records"], 3)
        self.assertEqual(result["actual_installed_records"], 2)
        missing = audit.compare_packages(expected, rows[:1], installed_only=False)
        self.assertIn({"package": "libc6", "version": "2.39", "count": 1}, missing["missing_or_changed"])
        self.assertEqual(missing["status"], "fail")

    def test_changed_versions_are_gaps_while_additional_packages_are_reported(self):
        rows = audit.inventory("one\tone\tamd64\t2.0\tii \nextra\textra\tall\t1\tii \n")
        result = audit.compare_packages(audit.manifest("one 1.0\n"), rows)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["missing_or_changed"], [{"package": "one", "version": "1.0", "count": 1}])
        self.assertEqual(len(result["additional_or_changed"]), 2)

    def test_cast_receipt_requires_exact_full_mode_and_release(self):
        text = ("installations:\n    teamdfir/sift-saltstack:\n"
                "        distro_name: teamdfir/sift-saltstack\n"
                "        version: v2026.04.21\n        mode: desktop\n")
        self.assertEqual(audit.cast_state(text, audit.CAST_EXPECTED["sift"])["status"], "pass")
        for replacement in (text.replace("desktop", "server"), text.replace("v2026.04.21", "v2025.01.01")):
            self.assertEqual(audit.cast_state(replacement, audit.CAST_EXPECTED["sift"])["status"], "fail")
        with self.assertRaises(ValueError):
            audit.cast_state(text + "        mode: desktop\n", audit.CAST_EXPECTED["sift"])

    def test_iso_receipt_must_bind_source_manifest_and_imported_archive(self):
        expected = audit.ISO_RELEASES["caine"]
        receipt = {"archive_sha256": "a" * 64, "publisher_manifest_sha256": "b" * 64,
                   "source_checksum_algorithm": expected["algorithm"], "source_checksum": expected["checksum"]}
        record = {"archive_sha256": "a" * 64}
        self.assertEqual(audit.iso_binding("caine", receipt, record, "b" * 64)["status"], "pass")
        for field in receipt:
            altered = dict(receipt, **{field: "incorrect"})
            with self.subTest(field=field):
                self.assertNotEqual(audit.iso_binding("caine", altered, record, "b" * 64)["status"], "pass")

    def test_prepared_profile_is_unavailable_without_starting_or_probing(self):
        with tempfile.TemporaryDirectory() as temporary:
            ctx = cli.Context(Path(temporary), Path(temporary))
            record = {"status": "prepared", "imported_image": "sha256:" + "a" * 64}
            with patch.object(cli, "read_json", return_value=record), patch.object(cli, "inspect_container", return_value=None), \
                    patch.object(audit, "observe") as observe:
                result = audit.audit_profile(ctx, "sift", {}, {})
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["preparation_record"], record)
            observe.assert_not_called()

    def test_empty_iso_manifest_needs_independent_source_database_evidence(self):
        expected = audit.ISO_RELEASES["tsurugi"]
        receipt = {"archive_sha256": "a" * 64, "package_baseline_sha256": "b" * 64,
                   "source_checksum_algorithm": expected["algorithm"], "source_checksum": expected["checksum"],
                   "package_baseline_origin": "verified-source-squashfs-dpkg-status",
                   "source_package_database_sha256": "c" * 64, "archive_package_database_sha256": "c" * 64,
                   "source_package_database_member": "/var/lib/dpkg/status",
                   "source_squashfs_iso_member": "/casper/filesystem.squashfs",
                   "source_squashfs_sha256": "d" * 64, "publisher_iso_manifest_bytes": 0}
        record = {"archive_sha256": "a" * 64}
        result = audit.iso_binding("tsurugi", receipt, record, "b" * 64)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["package_baseline_origin"], "verified-source-squashfs-dpkg-status")
        for field in receipt:
            with self.subTest(field=field):
                altered = dict(receipt, **{field: "incorrect"})
                self.assertNotEqual(audit.iso_binding("tsurugi", altered, record, "b" * 64)["status"], "pass")

    def test_manifest_rejects_empty_and_malformed_rows(self):
        for text in ("", "package", "package version extra", "../invalid 1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                audit.manifest(text)

    def test_audit_rejects_remote_or_custom_backend_before_runtime_or_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report.json"
            arguments = ["--state-dir", str(root), "--workspace", str(root), "--output", str(output)]
            for custom in (False, True):
                with self.subTest(custom=custom):
                    environment = {"CONTAINER_HOST": "" if custom else "ssh://example.invalid", "CONTAINER_CONNECTION": ""}
                    if custom:
                        (root / ".distroboxrc").write_text("container_manager=podman\n")
                    with patch.dict(os.environ, environment), patch.object(Path, "home", return_value=root), \
                            patch.object(audit.sys, "platform", "linux"), \
                            patch.object(audit.os, "geteuid", return_value=1000, create=True), \
                            patch.object(cli, "validate_paths"), patch.object(cli, "require_runtime") as runtime, \
                            contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        audit.main(arguments)
                    self.assertEqual(error.exception.code, 2)
                    runtime.assert_not_called()
                    self.assertFalse(output.exists())

    def test_owned_container_with_different_requested_workspace_is_never_probed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ctx = cli.Context(root / "state", root / "requested")
            image = "sha256:" + "a" * 64
            record = {"image_id": image, "workspace": str(root / "different")}
            container = {"Image": image, "State": {"Running": True},
                         "Mounts": [{"Type": "bind", "Destination": "/workspace", "RW": True,
                                     "Source": str(root / "different")}]}
            with patch.object(cli, "read_json", return_value=record), \
                    patch.object(cli, "inspect_container", return_value=container), \
                    patch.object(cli, "ensure_owned", return_value=record), patch.object(audit, "observe") as observe, \
                    self.assertRaisesRegex(cli.CommandError, "requested shared workspace"):
                audit.audit_profile(ctx, "sift", {}, {})
            observe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
