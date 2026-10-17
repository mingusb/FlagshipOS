#!/usr/bin/env python3
"""Remap explicitly named out-of-range rootfs owners to unused rootless IDs.

Verifies a private input snapshot and every output member's content/metadata.
Never extracts or executes archive files. Writes OUTPUT.owners.json and refuses
existing outputs. This changes ownership, so retain both archives and receipts.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile


def mappings(values):
    result = {}
    for value in values:
        if not re.fullmatch(r"[0-9]+:[0-9]+", value):
            raise ValueError("Owner mapping must be OLD:NEW decimal IDs")
        old, new = map(int, value.split(":"))
        if not 65535 < old < 4294967295 or not 0 < new < 65534:
            raise ValueError("Map only out-of-range owners to unprivileged IDs 1..65533")
        if old in result or new in result.values():
            raise ValueError("Owner mappings must be one-to-one")
        result[old] = new
    return result


def metadata(member):
    # Standard PAX fields duplicate the effective TarInfo attributes. All other
    # PAX metadata, including xattrs, is included verbatim in the comparison.
    fields = ("name", "mode", "uid", "gid", "size", "mtime", "linkname", "uname", "gname", "devmajor", "devminor")
    value = {field: getattr(member, field) for field in fields}
    value["type"] = member.type.hex()
    value["pax"] = {key: val for key, val in member.pax_headers.items()
                    if key not in (*fields, "path", "linkpath")}
    return value


def describe(digest, member, content_hash):
    data = metadata(member)
    data["content_sha256"] = content_hash
    digest.update(json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")


class DigestReader:
    def __init__(self, source):
        self.source, self.digest = source, hashlib.sha256()

    def read(self, size=-1):
        data = self.source.read(size)
        self.digest.update(data)
        return data


def rewrite(source, destination, uid_map, gid_map):
    seen_uid, seen_gid, changes = set(), set(), []
    expected = hashlib.sha256()
    count = 0
    with tarfile.open(source, "r:") as original, tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as output:
        for member in original:
            if member.sparse is not None or member.type not in (
                    tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.LNKTYPE,
                    tarfile.SYMTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
                raise ValueError("Unsupported archive member: " + member.name)
            if any("acl" in key.lower() for key in member.pax_headers):
                raise ValueError("ACL-bearing archives require separate owner-reference review")
            seen_uid.add(member.uid)
            seen_gid.add(member.gid)
            revised = copy.deepcopy(member)
            revised.uid = uid_map.get(member.uid, member.uid)
            revised.gid = gid_map.get(member.gid, member.gid)
            for numeric, named in (("uid", "uname"), ("gid", "gname")):
                if getattr(revised, numeric) != getattr(member, numeric):
                    setattr(revised, named, "")
                    if numeric in revised.pax_headers:
                        revised.pax_headers[numeric] = str(getattr(revised, numeric))
                    if named in revised.pax_headers:
                        revised.pax_headers[named] = ""
            if (member.uid, member.gid) != (revised.uid, revised.gid):
                changes.append({"path": member.name, "old_uid": member.uid, "old_gid": member.gid,
                                "new_uid": revised.uid, "new_gid": revised.gid})
            if revised.uid > 65535 or revised.gid > 65535 or min(revised.uid, revised.gid) < 0:
                raise ValueError("Unmapped owner remains: " + member.name)
            reader = DigestReader(original.extractfile(member)) if member.isfile() else None
            output.addfile(revised, reader)
            describe(expected, revised, reader.digest.hexdigest() if reader else None)
            if reader:
                reader.source.close()
            count += 1
            original.members.clear()
            output.members.clear()
            if count % 100000 == 0:
                print(f"Rewrote {count} entries", file=sys.stderr, flush=True)
    for mapping, seen in ((uid_map, seen_uid), (gid_map, seen_gid)):
        if not set(mapping) <= seen:
            raise ValueError("An explicitly mapped source ID was absent")
        if set(mapping.values()) & seen:
            raise ValueError("A target ID already owns archive entries; refusing to merge identities")
    actual = hashlib.sha256()
    verified_count = 0
    with tarfile.open(destination, "r:") as archive:
        for member in archive:
            content_hash = None
            if member.isfile():
                with archive.extractfile(member) as stream:
                    content_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            describe(actual, member, content_hash)
            verified_count += 1
            archive.members.clear()
    if count != verified_count or expected.digest() != actual.digest():
        raise ValueError("Output content or metadata differs beyond the requested owner mappings")
    return {"archive_entries": count, "ownership_changes": changes,
            "semantic_sha256": actual.hexdigest(), "content_and_metadata_verified": True,
            "verification": "Ordered effective tar metadata and SHA256 of every regular file, allowing only the explicit numeric owner changes and clearing their textual owner names"}


def remap(source, expected, output, uid_map, gid_map):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("A 64-character input SHA-256 is required")
    if not uid_map and not gid_map:
        raise ValueError("At least one explicit owner mapping is required")
    # Validate programmatic callers through the same rules as command-line use.
    uid_map = mappings([f"{old}:{new}" for old, new in uid_map.items()])
    gid_map = mappings([f"{old}:{new}" for old, new in gid_map.items()])
    source = Path(source).expanduser().resolve(strict=True)
    output = Path(output).expanduser().absolute()
    output = output.parent.resolve(strict=True) / output.name
    receipt = output.with_name(output.name + ".owners.json")
    if not source.is_file():
        raise ValueError("Input must be a regular tar file")
    if any(path.exists() or path.is_symlink() for path in (output, receipt)):
        raise ValueError("Refusing to overwrite output or ownership receipt")
    with tempfile.TemporaryDirectory(prefix="flagship-owners-", dir=output.parent) as temporary:
        root = Path(temporary)
        snapshot, converted = root / "verified.tar", root / "remapped.tar"
        with source.open("rb") as stream, snapshot.open("xb") as target:
            reader = DigestReader(stream)
            shutil.copyfileobj(reader, target, 1024 * 1024)
        if reader.digest.hexdigest() != expected.lower():
            raise ValueError("Input SHA-256 mismatch; nothing was remapped")
        result = rewrite(snapshot, converted, uid_map, gid_map)
        with converted.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
        result.update(schema_version=1, source_archive=str(source), source_archive_sha256=expected.lower(),
                      archive=str(output), archive_sha256=digest, archive_bytes=converted.stat().st_size,
                      uid_map=uid_map, gid_map=gid_map)
        private = root / "owners.json"
        with private.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(private, receipt)
        try:
            os.link(converted, output)
        except OSError:
            if receipt.exists() and receipt.samefile(private):
                receipt.unlink()
            raise
    print(f"{digest}  {output}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--uid-map", action="append", default=[], metavar="OLD:NEW")
    parser.add_argument("--gid-map", action="append", default=[], metavar="OLD:NEW")
    args = parser.parse_args(argv)
    try:
        remap(args.input, args.sha256, args.output, mappings(args.uid_map), mappings(args.gid_map))
    except (OSError, ValueError, tarfile.TarError) as error:
        print(f"flagship: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
