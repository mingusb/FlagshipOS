import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("owner_remap", Path(__file__).parents[1] / "scripts/remap-rootfs-owners.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class OwnerRemapTests(unittest.TestCase):
    def fixture(self, root, *, target_used=False, acl=False):
        source = root / "source.tar"
        with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as archive:
            item = tarfile.TarInfo("./opt/tool/data with spaces")
            item.uid, item.gid, item.mode, item.size = 1146479719, 1490099278, 0o751, 7
            item.uname, item.gname = "old-user", "old-group"
            item.pax_headers = {"uid": str(item.uid), "gid": str(item.gid), "SCHILY.xattr.user.example": "retained"}
            if acl:
                item.pax_headers["SCHILY.acl.access"] = "user::rw-"
            archive.addfile(item, io.BytesIO(b"payload"))
            for name, kind, link in (("hard", tarfile.LNKTYPE, item.name),
                                     ("symbolic", tarfile.SYMTYPE, "data with spaces"),
                                     ("pipe", tarfile.FIFOTYPE, "")):
                other = tarfile.TarInfo("./opt/tool/" + name)
                other.uid, other.gid = (60000 if target_used else 123), 456
                other.type, other.linkname = kind, link
                archive.addfile(other)
        return source, hashlib.sha256(source.read_bytes()).hexdigest()

    def test_pax_numeric_owners_contents_links_modes_and_xattrs_are_verified(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            source, digest = self.fixture(root)
            before = source.read_bytes()
            output = root / "output.tar"
            result = helper.remap(source, digest, output, {1146479719: 60000}, {1490099278: 60001})
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(result["content_and_metadata_verified"])
            self.assertEqual(result["archive_entries"], 4)
            self.assertEqual(len(result["ownership_changes"]), 1)
            self.assertEqual(json.loads((root / "output.tar.owners.json").read_text())["archive_sha256"],
                             hashlib.sha256(output.read_bytes()).hexdigest())
            with tarfile.open(output) as archive:
                member = archive.next()
                self.assertEqual((member.uid, member.gid, member.mode, member.uname, member.gname), (60000, 60001, 0o751, "", ""))
                self.assertEqual(member.pax_headers["SCHILY.xattr.user.example"], "retained")
                self.assertEqual(archive.extractfile(member).read(), b"payload")
                self.assertEqual(archive.extractfile("./opt/tool/hard").read(), b"payload")
                self.assertTrue(archive.getmember("./opt/tool/symbolic").issym())
                self.assertTrue(archive.getmember("./opt/tool/pipe").isfifo())

    def test_invalid_or_colliding_mapping_never_publishes(self):
        for options in ({"target_used": True}, {"acl": True}, {}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, digest = self.fixture(root, **options)
                output = root / "output.tar"
                groups = {1490099278: 60001} if options else {}
                with self.assertRaises(ValueError):
                    helper.remap(source, digest, output, {1146479719: 60000}, groups)
                self.assertEqual(list(root.iterdir()), [source])

    def test_binary_capability_xattr_survives_added_pax_encoding_marker(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            source = root / "binary-xattr.tar"
            payload = b"\x01\x00\x00\x02\x00\x14\x80\x00" + b"\x00" * 12
            with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as archive:
                item = tarfile.TarInfo("./usr/bin/example")
                item.uid = 1146479719
                item.pax_headers = {"SCHILY.xattr.security.capability": payload.decode("utf-8", "surrogateescape")}
                archive.addfile(item, io.BytesIO())
            # Isolate the representational difference seen with sqfs2tar: its
            # decoded header lacks hdrcharset, while Python adds that marker.
            with tarfile.open(source) as archive:
                before = archive.next()
            after = before.replace()
            before.pax_headers.pop("hdrcharset", None)
            after.pax_headers["hdrcharset"] = "BINARY"
            self.assertEqual(helper.metadata(before), helper.metadata(after))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            output = root / "converted.tar"
            helper.remap(source, digest, output, {1146479719: 60000}, {})
            with tarfile.open(output) as archive:
                value = archive.next().pax_headers["SCHILY.xattr.security.capability"]
                self.assertEqual(value.encode("utf-8", "surrogateescape"), payload)

    def test_checksum_and_existing_output_are_checked_before_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, digest = self.fixture(root)
            output = root / "output.tar"
            with patch.object(helper, "rewrite") as rewrite:
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    helper.remap(source, "0" * 64, output, {1146479719: 60000}, {})
                output.write_bytes(b"preserve")
                with self.assertRaisesRegex(ValueError, "overwrite"):
                    helper.remap(source, digest, output, {1146479719: 60000}, {})
                rewrite.assert_not_called()
            self.assertEqual(output.read_bytes(), b"preserve")

    def test_mapping_rejects_privilege_changes_merges_and_ambiguous_syntax(self):
        for values in (("1000:60000",), ("1146479719:0",), ("1146479719:65534",),
                       ("1146479719:60000", "1490099278:60000"),
                       ("1146479719:60000", "1146479719:60001"), ("1:2:3",)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                helper.mappings(values)


if __name__ == "__main__":
    unittest.main()
