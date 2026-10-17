"""The conversion boundary must verify inputs and publish output atomically."""

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
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
        options = {key: kwargs[key] for key in ("algorithm", "omit_runtime_sockets") if key in kwargs}
        return iso_helper.convert(
            self.iso, kwargs.get("digest", self.digest), self.output,
            kwargs.get("member", "casper/filesystem.squashfs"),
            **options,
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
            for algorithm, length in (("sha256", 64), ("sha512", 128)):
                for digest in ("", "f" * (length - 1), "g" * length, "f" * (length + 1)):
                    with self.subTest(algorithm=algorithm, digest=digest), self.assertRaises(ValueError):
                        self.convert(digest=digest, algorithm=algorithm)
            for algorithm in ("md5", "sha1", "SHA512", "", None):
                with self.subTest(algorithm=algorithm), self.assertRaisesRegex(ValueError, "algorithm"):
                    self.convert(algorithm=algorithm)
        run.assert_not_called()

    def test_sha512_source_mismatch_never_extracts_or_creates_output(self):
        with patch.object(iso_helper.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "SHA-512 mismatch"):
                self.convert(digest="0" * 128, algorithm="sha512")
        run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [self.iso])

    def test_sha512_verifies_snapshot_while_output_receipt_remains_sha256(self):
        original = self.iso.read_bytes()
        expected = hashlib.sha512(original).hexdigest().upper()
        snapshots = []
        def run(argv, **kwargs):
            if argv[0] == "xorriso":
                self.iso.write_bytes(b"later unverified source bytes")
                snapshot = Path(argv[argv.index("-indev") + 1])
                snapshots.append(snapshot)
                self.assertEqual(snapshot.read_bytes(), original)
                Path(argv[-1]).write_bytes(b"fixture verified squashfs")
            else:
                kwargs["stdout"].write(b"fixture converted tar")
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(iso_helper.subprocess, "run", side_effect=run):
            digest = self.convert(digest=expected, algorithm="sha512")
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(len(digest), 64)
        self.assertFalse(snapshots[0].exists())
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output})

    def test_cli_requires_exactly_one_source_checksum_and_routes_algorithm(self):
        arguments = ["--iso", str(self.iso), "--output", str(self.output)]
        with patch.object(iso_helper, "convert") as convert:
            for algorithm, digest in (("sha256", "a" * 64), ("sha512", "b" * 128)):
                self.assertEqual(iso_helper.main([*arguments, "--" + algorithm, digest]), 0)
                self.assertEqual(convert.call_args.args[1], digest)
                self.assertEqual(convert.call_args.kwargs, {"algorithm": algorithm})
            convert.reset_mock()
            for checksums in ([], ["--sha256", "a" * 64, "--sha512", "b" * 128]):
                with self.subTest(checksums=checksums), self.assertRaises(SystemExit) as error:
                    iso_helper.main(arguments + checksums)
                self.assertEqual(error.exception.code, 2)
            convert.assert_not_called()

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
        self.assertIn("--no-skip", commands[-1][0])
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output})

    def socket_conversion_backend(self, diagnostics=None, *, metadata=None, returncode=0, race=None):
        if diagnostics is None:
            diagnostics = "WARNING: ./var/run/runtime.sock: cannot pack socket\nSkipping ./var/run/runtime.sock\n"
        if metadata is None:
            metadata = "Name: runtime.sock\nInode type: socket\nHard link count: 1\n"
        def run(argv, **kwargs):
            if argv[0] == "xorriso":
                Path(argv[-1]).write_bytes(b"fixture squashfs")
            elif argv[0] == "rdsquashfs":
                self.assertEqual(argv[1:3], ["--stat", "/var/run/runtime.sock"])
                return subprocess.CompletedProcess(argv, 0, stdout=metadata, stderr="")
            else:
                self.assertNotIn("--no-skip", argv)
                with tarfile.open(fileobj=kwargs["stdout"], mode="w", format=tarfile.PAX_FORMAT) as archive:
                    root = tarfile.TarInfo(".")
                    root.type, root.mode, root.uid, root.gid = tarfile.DIRTYPE, 0o755, 123, 456
                    archive.addfile(root)
                    program = tarfile.TarInfo("./usr/bin/program")
                    program.mode, program.uid, program.gid, program.size = 0o751, 789, 234, 7
                    program.pax_headers = {"SCHILY.xattr.user.fixture": "preserved"}
                    archive.addfile(program, io.BytesIO(b"program"))
                    link = tarfile.TarInfo("./usr/bin/program-alias")
                    link.type, link.linkname = tarfile.LNKTYPE, "./usr/bin/program"
                    link.uid, link.gid = 789, 234
                    archive.addfile(link)
                    fifo = tarfile.TarInfo("./var/run/pipe")
                    fifo.type, fifo.mode = tarfile.FIFOTYPE, 0o600
                    archive.addfile(fifo)
                kwargs["stderr"].write(diagnostics.encode("utf-8"))
                if race:
                    race()
                return subprocess.CompletedProcess(argv, returncode)
            return subprocess.CompletedProcess(argv, 0)
        return run

    def test_socket_mode_publishes_exact_omissions_and_preserves_representable_entries(self):
        with patch.object(iso_helper.subprocess, "run", side_effect=self.socket_conversion_backend()):
            digest = self.convert(omit_runtime_sockets=True)
        receipt_path = self.output.with_name(self.output.name + ".omissions.json")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["omitted"], [{"path": "./var/run/runtime.sock", "type": "socket"}])
        self.assertEqual(receipt["archive_sha256"], digest)
        self.assertEqual(receipt["source_checksum"], self.digest)
        self.assertEqual(receipt["archive_entries"], 4)
        with tarfile.open(self.output) as archive:
            self.assertEqual(archive.getnames(), [".", "./usr/bin/program", "./usr/bin/program-alias", "./var/run/pipe"])
            self.assertEqual((archive.getmember(".").uid, archive.getmember(".").gid), (123, 456))
            program = archive.getmember("./usr/bin/program")
            self.assertEqual((program.uid, program.gid, program.mode), (789, 234, 0o751))
            self.assertEqual(program.pax_headers["SCHILY.xattr.user.fixture"], "preserved")
            self.assertEqual(archive.extractfile(program).read(), b"program")
            self.assertTrue(archive.getmember("./usr/bin/program-alias").islnk())
            self.assertTrue(archive.getmember("./var/run/pipe").isfifo())
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output, receipt_path})

    def test_socket_mode_rejects_every_unapproved_diagnostic_without_publishing(self):
        diagnostics = (
            "WARNING: ./usr/bin/program: unknown type\nSkipping ./usr/bin/program\n",
            "Found a file named '..', skipping.\n",
            "Skipping ./usr/bin/program\n",
            "WARNING: ./var/run/runtime.sock: cannot pack socket\nSkipping ./usr/bin/program\n",
            "WARNING: ./var/run/runtime.sock: cannot pack socket\nSkipping ./var/run/runtime.sock\nRead error\n",
            "WARNING: gnu/data2: cannot pack socket\nSkipping ./" + "a" * 100 + "\n",
        )
        for report in diagnostics:
            with self.subTest(report=report), patch.object(
                iso_helper.subprocess, "run", side_effect=self.socket_conversion_backend(report)
            ), self.assertRaises(ValueError):
                self.convert(omit_runtime_sockets=True)
            self.assertEqual(list(self.root.iterdir()), [self.iso])

    def test_socket_mode_independently_rejects_non_socket_or_unsafe_inode_metadata(self):
        for metadata in (
            "Inode type: file\nHard link count: 1\n",
            "Inode type: socket\nHard link count: 2\n",
            "Inode type: extended socket\nHard link count: 1\nXattr index: 0x0\n",
            "Inode type: extended socket\nHard link count: 1\n",
        ):
            with self.subTest(metadata=metadata), patch.object(
                iso_helper.subprocess, "run", side_effect=self.socket_conversion_backend(metadata=metadata)
            ), self.assertRaisesRegex(ValueError, "inode"):
                self.convert(omit_runtime_sockets=True)
            self.assertEqual(list(self.root.iterdir()), [self.iso])

    def test_socket_warning_cannot_hide_nonzero_converter_exit(self):
        with patch.object(iso_helper.subprocess, "run", side_effect=self.socket_conversion_backend(returncode=1)):
            with self.assertRaises(subprocess.CalledProcessError):
                self.convert(omit_runtime_sockets=True)
        self.assertEqual(list(self.root.iterdir()), [self.iso])

    def test_socket_mode_refuses_receipt_collision_before_any_extraction(self):
        receipt = self.output.with_name(self.output.name + ".omissions.json")
        receipt.write_text("existing receipt")
        with patch.object(iso_helper.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "receipt"):
                self.convert(omit_runtime_sockets=True)
        run.assert_not_called()
        self.assertEqual(receipt.read_text(), "existing receipt")
        self.assertFalse(self.output.exists())

    def test_socket_mode_rolls_back_own_receipt_if_output_publication_loses_race(self):
        backend = self.socket_conversion_backend(race=lambda: self.output.write_bytes(b"another process won"))
        with patch.object(iso_helper.subprocess, "run", side_effect=backend), self.assertRaises(FileExistsError):
            self.convert(omit_runtime_sockets=True)
        self.assertEqual(self.output.read_bytes(), b"another process won")
        self.assertEqual(set(self.root.iterdir()), {self.iso, self.output})

    def test_cli_socket_mode_requires_explicit_flag(self):
        with patch.object(iso_helper, "convert") as convert:
            result = iso_helper.main(["--iso", str(self.iso), "--output", str(self.output),
                                     "--sha256", self.digest, "--omit-runtime-sockets"])
        self.assertEqual(result, 0)
        self.assertEqual(convert.call_args.kwargs, {"algorithm": "sha256", "omit_runtime_sockets": True})

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
