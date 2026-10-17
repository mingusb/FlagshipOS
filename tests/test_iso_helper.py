"""The conversion boundary must verify inputs and publish output atomically."""

import contextlib
import hashlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "iso-to-rootfs.py"
SPEC = importlib.util.spec_from_file_location("flagship_iso_helper", SCRIPT)
iso_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(iso_helper)


class IsoHelperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flagship-iso-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.iso = self.root / "source ISO ; literal.iso"
        self.iso.write_bytes(b"fixture source bytes")
        self.digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        self.output = self.root / "rootfs.tar"
        self.addCleanup(patch.stopall)
        patch.object(iso_helper.shutil, "which", side_effect=lambda command: "/usr/bin/" + command).start()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.stdout))
        self.enterContext(contextlib.redirect_stderr(self.stderr))

    def convert(self, **kwargs):
        return iso_helper.convert(
            self.iso, kwargs.get("digest", self.digest), self.output,
            kwargs.get("member", "casper/filesystem.squashfs"),
        )

    def test_checksum_mismatch_never_extracts_or_creates_output(self):
        with patch.object(iso_helper.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "mismatch"):
                self.convert(digest="0" * 64)
        run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [self.iso])

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b"previous output")
        with patch.object(iso_helper.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "overwrite"):
                self.convert()
        run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"previous output")

    def test_traversal_member_rejected_before_extraction(self):
        with patch.object(iso_helper.subprocess, "run") as run:
            for member in ("../escape", "/casper/../../escape", "/", "."):
                with self.subTest(member=member), self.assertRaises(ValueError):
                    self.convert(member=member)
        run.assert_not_called()

    def test_invalid_checksums_are_rejected(self):
        with patch.object(iso_helper.subprocess, "run") as run:
            for digest in ("", "f" * 63, "g" * 64, "f" * 65):
                with self.subTest(digest=digest), self.assertRaises(ValueError):
                    self.convert(digest=digest)
        run.assert_not_called()

    def test_success_preserves_argument_boundaries_and_publishes_digest(self):
        commands = []
        snapshots = []
        original = self.iso.read_bytes()

        def run(argv, **kwargs):
            commands.append((argv, kwargs))
            if argv[0] == "xorriso":
                snapshot = Path(argv[argv.index("-indev") + 1])
                snapshots.append((snapshot, snapshot.read_bytes()))
                Path(argv[-1]).write_bytes(b"fixture squashfs")
            else:
                kwargs["stdout"].write(b"fixture converted tar")
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(iso_helper.subprocess, "run", side_effect=run):
            digest = self.convert(digest=self.digest.upper())
        self.assertEqual(self.output.read_bytes(), b"fixture converted tar")
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertNotEqual(snapshots[0][0], self.iso)
        self.assertEqual(snapshots[0][1], original)
        self.assertFalse(snapshots[0][0].exists(), "private input snapshot was not cleaned up")
        for argv, kwargs in commands:
            self.assertIsInstance(argv, list)
            self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output})

    def test_replacing_original_after_verification_cannot_change_extracted_input(self):
        original = self.iso.read_bytes()
        extracted = []

        def run(argv, **kwargs):
            if argv[0] == "xorriso":
                replacement = self.root / "replacement.iso"
                replacement.write_bytes(b"unverified replacement bytes")
                replacement.replace(self.iso)
                snapshot = Path(argv[argv.index("-indev") + 1])
                extracted.append((snapshot, snapshot.read_bytes()))
                Path(argv[-1]).write_bytes(b"fixture verified squashfs")
            else:
                kwargs["stdout"].write(b"converted from verified snapshot")
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(iso_helper.subprocess, "run", side_effect=run):
            self.convert()
        self.assertNotEqual(extracted[0][0], self.iso)
        self.assertEqual(extracted[0][1], original)
        self.assertEqual(hashlib.sha256(extracted[0][1]).hexdigest(), self.digest)
        self.assertEqual(self.iso.read_bytes(), b"unverified replacement bytes")
        self.assertEqual(self.output.read_bytes(), b"converted from verified snapshot")
        self.assertFalse(extracted[0][0].exists())
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output})

    def test_converter_failure_leaves_no_partial_output(self):
        def run(argv, **kwargs):
            if argv[0] == "xorriso":
                Path(argv[-1]).write_bytes(b"fixture squashfs")
                return subprocess.CompletedProcess(argv, 0)
            kwargs["stdout"].write(b"partial bytes")
            raise subprocess.CalledProcessError(17, argv)

        with patch.object(iso_helper.subprocess, "run", side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                self.convert()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.iterdir()), [self.iso])

    def test_racing_output_creation_is_not_overwritten(self):
        def run(argv, **kwargs):
            if argv[0] == "xorriso":
                Path(argv[-1]).write_bytes(b"fixture squashfs")
            else:
                kwargs["stdout"].write(b"new output")
                self.output.write_bytes(b"another process won")
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(iso_helper.subprocess, "run", side_effect=run):
            with self.assertRaises(FileExistsError):
                self.convert()
        self.assertEqual(self.output.read_bytes(), b"another process won")
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output})


if __name__ == "__main__":
    unittest.main()
