#!/usr/bin/env python3
"""Convert a verified live ISO's squashfs to a rootfs tar without root or mounts.

Requires xorriso and sqfs2tar (Ubuntu packages xorriso, squashfs-tools-ng).
The checksum must be obtained independently from the distribution publisher.
No downloaded program or filesystem is executed by this helper.
The explicit --omit-runtime-sockets mode additionally needs rdsquashfs and
writes OUTPUT.omissions.json. All other omissions and read errors remain fatal.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def socket_omissions(diagnostics, squashfs):
    """Accept only sqfs2tar's paired socket diagnostics, verified against inodes.

    Upstream v1.3.2 write_tree.c and lib/tar/write_header.c emit these exact
    pairs. The latter writes PAX/GNU metadata before rejecting a socket, so
    sockets with xattrs, long names, or hard links cannot safely be omitted.
    Unknown diagnostics fail closed, including after a zero converter exit.
    """
    lines = iter(diagnostics.splitlines())
    omitted = []
    for warning in lines:
        match = re.fullmatch(r"WARNING: (.+): cannot pack socket", warning)
        if not match or next(lines, None) != "Skipping " + match[1]:
            raise ValueError("Conversion reported an unapproved omission or diagnostic: " + warning)
        name = match[1]
        parts = name[2:].split("/") if name.startswith("./") else []
        if (not parts or any(part in ("", ".", "..") for part in parts)
                or not name.isprintable() or len(name.encode("utf-8")) >= 100
                or name in omitted):
            raise ValueError("Cannot safely identify an omitted socket: " + repr(name))
        result = subprocess.run(
            ["rdsquashfs", "--stat", "/" + name[2:], str(squashfs)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            text=True, encoding="utf-8", errors="strict",
        )
        fields = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition(": ")
            if separator:
                if key in fields:
                    raise ValueError("Ambiguous inode metadata for omitted socket: " + name)
                fields[key] = value
        if (result.stderr or fields.get("Inode type") not in ("socket", "extended socket")
                or fields.get("Hard link count") != "1"
                or fields.get("Xattr index", "0xFFFFFFFF") != "0xFFFFFFFF"
                or (fields.get("Inode type") == "extended socket" and "Xattr index" not in fields)):
            raise ValueError("Cannot safely omit socket inode or its metadata: " + name)
        omitted.append(name)
    return omitted


def validate_archive(archive, omitted):
    """Read headers only; never extract or execute the converted filesystem."""
    count = 0
    try:
        with tarfile.open(archive, "r:") as stream:
            for member in stream:
                if member.name in omitted or (member.islnk() and member.linkname in omitted):
                    raise ValueError("Archive unexpectedly represents an omitted socket")
                count += 1
                stream.members.clear()
    except tarfile.TarError as error:
        raise ValueError("Conversion produced an invalid tar archive") from error
    if not count:
        raise ValueError("Conversion produced no archive entries")
    return count


def convert(iso, expected, output, squashfs_path, algorithm="sha256", omit_runtime_sockets=False):
    iso = Path(iso).expanduser().resolve(strict=True)
    output = Path(output).expanduser().absolute()
    if not iso.is_file():
        raise ValueError("ISO must be a regular file")
    if algorithm not in ("sha256", "sha512"):
        raise ValueError("Checksum algorithm must be sha256 or sha512")
    length = 64 if algorithm == "sha256" else 128
    if not isinstance(expected, str) or not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", expected):
        raise ValueError(f"--{algorithm} must be {length} hexadecimal characters")
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing to overwrite an existing output")
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    receipt = output.with_name(output.name + ".omissions.json")
    if omit_runtime_sockets and (receipt.exists() or receipt.is_symlink()):
        raise ValueError("Refusing to overwrite an existing omissions receipt")
    member = PurePosixPath(squashfs_path)
    if ".." in member.parts or str(member) in (".", "/"):
        raise ValueError("Invalid squashfs path inside ISO")
    executables = ("xorriso", "sqfs2tar", "rdsquashfs") if omit_runtime_sockets else ("xorriso", "sqfs2tar")
    for executable in executables:
        if not shutil.which(executable):
            raise ValueError(f"Missing {executable}; install xorriso and squashfs-tools-ng")
    with tempfile.TemporaryDirectory(prefix="flagship-iso-", dir=parent) as temporary:
        temporary = Path(temporary)
        # Verify the exact bytes subsequently parsed, even if the source changes.
        print("Copying and verifying source ISO checksum...", file=sys.stderr)
        snapshot = temporary / "verified.iso"
        checksum = hashlib.new(algorithm)
        with iso.open("rb") as source, snapshot.open("xb") as destination:
            while chunk := source.read(1024 * 1024):
                checksum.update(chunk)
                destination.write(chunk)
        if checksum.hexdigest() != expected.lower():
            raise ValueError(f"ISO {algorithm.upper().replace('SHA', 'SHA-')} mismatch; nothing was extracted")
        squashfs = temporary / "filesystem.squashfs"
        archive = temporary / "rootfs.tar"
        subprocess.run([
            "xorriso", "-osirrox", "on", "-indev", str(snapshot),
            "-extract", "/" + str(member).lstrip("/"), str(squashfs),
        ], check=True)
        if not squashfs.is_file() or squashfs.is_symlink():
            raise ValueError("Selected ISO member is not a regular squashfs image")
        with archive.open("xb") as stream:
            arguments = ["sqfs2tar", "--root-becomes", "."]
            if omit_runtime_sockets:
                # Capture diagnostics on disk; inspect every line before publishing.
                diagnostics = temporary / "sqfs2tar.stderr"
                with diagnostics.open("xb") as errors:
                    result = subprocess.run(arguments + [str(squashfs)], stdout=stream, stderr=errors)
                report = diagnostics.read_text(encoding="utf-8", errors="strict")
                if report:
                    print(report, file=sys.stderr, end="" if report.endswith("\n") else "\n")
                result.check_returncode()
                omitted = socket_omissions(report, squashfs)
            else:
                subprocess.run(arguments + ["--no-skip", str(squashfs)], stdout=stream, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        if not archive.stat().st_size:
            raise ValueError("Conversion produced an empty archive")
        digest = sha256(archive)
        # Atomic publication without replacing a file created during conversion.
        if omit_runtime_sockets:
            entries = validate_archive(archive, set(omitted))
            private_receipt = temporary / "omissions.json"
            with private_receipt.open("x", encoding="utf-8") as stream:
                json.dump({
                    "schema_version": 1, "mode": "omit-runtime-sockets",
                    "source_iso": str(iso), "source_checksum_algorithm": algorithm,
                    "source_checksum": expected.lower(), "squashfs_path": "/" + str(member).lstrip("/"),
                    "archive": str(output), "archive_sha256": digest, "archive_entries": entries,
                    "omitted": [{"path": name, "type": "socket"} for name in omitted],
                }, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Publish the receipt first so an archive is never published without it.
            os.link(private_receipt, receipt)
            try:
                os.link(archive, output)
            except OSError:
                if receipt.exists() and receipt.samefile(private_receipt):
                    receipt.unlink()
                raise
        else:
            os.link(archive, output)
    print(f"{digest}  {output}")
    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True)
    checksums = parser.add_mutually_exclusive_group(required=True)
    checksums.add_argument("--sha256")
    checksums.add_argument("--sha512")
    parser.add_argument("--output", required=True)
    parser.add_argument("--squashfs-path", default="casper/filesystem.squashfs")
    parser.add_argument("--omit-runtime-sockets", action="store_true",
                        help="Explicitly omit verified Unix sockets and write OUTPUT.omissions.json; reject all other omissions")
    args = parser.parse_args(argv)
    try:
        algorithm = "sha512" if args.sha512 is not None else "sha256"
        options = {"algorithm": algorithm}
        if args.omit_runtime_sockets:
            options["omit_runtime_sockets"] = True
        convert(args.iso, getattr(args, algorithm), args.output, args.squashfs_path, **options)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"flagship: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
