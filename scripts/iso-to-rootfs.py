#!/usr/bin/env python3
"""Convert a verified live ISO's squashfs to a rootfs tar without root or mounts.

Requires xorriso and sqfs2tar (Ubuntu packages xorriso, squashfs-tools-ng).
The checksum must be obtained independently from the distribution publisher.
No downloaded program or filesystem is executed by this helper.
"""

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def convert(iso, expected, output, squashfs_path):
    iso = Path(iso).expanduser().resolve(strict=True)
    output = Path(output).expanduser().absolute()
    if not iso.is_file():
        raise ValueError("ISO must be a regular file")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("--sha256 must be 64 hexadecimal characters")
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing to overwrite an existing output")
    parent = output.parent.resolve(strict=True)
    output = parent / output.name
    member = PurePosixPath(squashfs_path)
    if ".." in member.parts or str(member) in (".", "/"):
        raise ValueError("Invalid squashfs path inside ISO")
    for executable in ("xorriso", "sqfs2tar"):
        if not shutil.which(executable):
            raise ValueError(f"Missing {executable}; install xorriso and squashfs-tools-ng")
    with tempfile.TemporaryDirectory(prefix="flagship-iso-", dir=parent) as temporary:
        temporary = Path(temporary)
        # Verify the exact bytes subsequently parsed, even if the source changes.
        print("Copying and verifying source ISO checksum...", file=sys.stderr)
        snapshot = temporary / "verified.iso"
        checksum = hashlib.sha256()
        with iso.open("rb") as source, snapshot.open("xb") as destination:
            while chunk := source.read(1024 * 1024):
                checksum.update(chunk)
                destination.write(chunk)
        if checksum.hexdigest() != expected.lower():
            raise ValueError("ISO SHA-256 mismatch; nothing was extracted")
        squashfs = temporary / "filesystem.squashfs"
        archive = temporary / "rootfs.tar"
        subprocess.run([
            "xorriso", "-osirrox", "on", "-indev", str(snapshot),
            "-extract", "/" + str(member).lstrip("/"), str(squashfs),
        ], check=True)
        if not squashfs.is_file() or squashfs.is_symlink():
            raise ValueError("Selected ISO member is not a regular squashfs image")
        with archive.open("xb") as stream:
            subprocess.run([
                "sqfs2tar", "--root-becomes", ".", "--no-skip", str(squashfs),
            ], stdout=stream, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        if not archive.stat().st_size:
            raise ValueError("Conversion produced an empty archive")
        digest = sha256(archive)
        # Atomic publication without replacing a file created during conversion.
        os.link(archive, output)
    print(f"{digest}  {output}")
    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--squashfs-path", default="casper/filesystem.squashfs")
    args = parser.parse_args(argv)
    try:
        convert(args.iso, args.sha256, args.output, args.squashfs_path)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"flagship: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
