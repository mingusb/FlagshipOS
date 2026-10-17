"""Real filesystem, process-supervision and MCP wire-contract checks."""

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from flagship import cli
from flagship.mcp_server import Backend, FILE_LIMIT, Workspace, bounded_process


@unittest.skipUnless(sys.platform == "linux", "Linux descriptor and process semantics")
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flagship-mcp-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "workspace"
        self.directory.mkdir()
        self.workspace = Workspace(self.directory)
        self.addCleanup(self.workspace.close)

    def test_literal_filename_hash_and_text(self):
        name = "a file ; $(literal).txt"
        data = b"harmless local fixture\n"
        (self.directory / name).write_bytes(data)
        result = self.workspace.inspect(name)
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(result["prefix_hex"], data.hex())
        self.assertEqual(self.workspace.text(name)["text"], data.decode())
        self.assertEqual(self.workspace.listing()["entries"][0]["name"], name)

    def test_traversal_absolute_windows_and_null_paths_rejected(self):
        for path in ("../secret", "/etc/passwd", "a/../secret", "a//b", "C:\\secret", "x\x00y"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.workspace.inspect(path)

    def test_file_and_directory_symlinks_rejected(self):
        (self.root / "secret").write_text("private")
        (self.directory / "filelink").symlink_to(self.root / "secret")
        (self.directory / "dirlink").symlink_to(self.root, target_is_directory=True)
        for path in ("filelink", "dirlink/secret"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.workspace.inspect(path)
        self.assertEqual({row["kind"] for row in self.workspace.listing()["entries"]}, {"symlink"})

    def test_hardlink_and_fifo_rejected_without_blocking(self):
        outside = self.root / "secret"
        outside.write_text("private")
        os.link(outside, self.directory / "hardlink")
        os.mkfifo(self.directory / "pipe")
        for path in ("hardlink", "pipe"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.workspace.inspect(path)

    def test_open_descriptor_stays_on_original_after_name_replaced(self):
        (self.directory / "file").write_text("original")
        (self.root / "secret").write_text("private")
        with self.workspace.open("file") as (fd, _):
            (self.directory / "file").rename(self.directory / "original")
            (self.directory / "file").symlink_to(self.root / "secret")
            self.assertEqual(os.read(fd, 100), b"original")

    def test_changed_file_detected(self):
        path = self.directory / "file"
        path.write_text("before")
        with self.workspace.open("file") as (fd, original):
            path.write_text("after and longer")
            with self.assertRaisesRegex(ValueError, "changed"):
                self.workspace.unchanged(fd, original)

    def test_large_file_rejected_before_reading(self):
        with (self.directory / "sparse").open("wb") as stream:
            stream.truncate(FILE_LIMIT + 1)
        with self.assertRaisesRegex(ValueError, "256 MiB"):
            self.workspace.inspect("sparse")

    def test_text_is_bounded_and_utf8_boundary_is_safe(self):
        (self.directory / "text").write_bytes("AéB".encode())
        result = self.workspace.text("text", 2)
        self.assertEqual(result["text"], "A")
        self.assertTrue(result["truncated"])
        (self.directory / "binary").write_bytes(b"x\x00y")
        with self.assertRaises(ValueError):
            self.workspace.text("binary")

    def test_directory_pagination(self):
        for name in ("c", "a", "b"):
            (self.directory / name).touch()
        first = self.workspace.listing(limit=2)
        self.assertEqual([row["name"] for row in first["entries"]], ["a", "b"])
        self.assertEqual(first["next_offset"], 2)
        self.assertEqual(self.workspace.listing(offset=2)["entries"][0]["name"], "c")


@unittest.skipUnless(sys.platform == "linux", "Linux process groups")
class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_exit_status_and_both_streams_preserved(self):
        result = await bounded_process([sys.executable, "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"])
        self.assertEqual(result, {"exit_code": 7, "stdout": "out\n", "stderr": "err\n"})

    async def test_excessive_output_rejected(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            await bounded_process([sys.executable, "-c", "print('x' * 10000)"], limit=100)

    async def test_deadline_terminates_sleeping_process(self):
        with self.assertRaises(TimeoutError):
            await bounded_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)

    async def test_cancellation_reaps_child(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "pid"
            task = asyncio.create_task(bounded_process([sys.executable, "-c",
                "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)", str(path)]))
            async with asyncio.timeout(5):
                while not path.exists():
                    await asyncio.sleep(0.01)
            pid = int(path.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    async def test_invalid_tool_name_never_reaches_backend(self):
        backend = Backend(cli.Context(Path("/tmp/state"), Path("/tmp/workspace")))
        with patch.object(backend, "call") as call:
            with self.assertRaises(cli.CommandError):
                await backend.resolve("nmap; echo bad")
            call.assert_not_called()


HAS_SDK = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_SDK and sys.platform == "linux", "Install the mcp extra on Linux")
class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_handshake_schemas_resources_and_workspace(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        with tempfile.TemporaryDirectory(prefix="flagship-mcp-wire-") as root:
            workspace = Path(root) / "workspace"
            workspace.mkdir()
            fixture = b"MCP local fixture\n"
            (workspace / "sample.txt").write_bytes(fixture)
            parameters = StdioServerParameters(command=sys.executable,
                args=["-m", "flagship", "--state-dir", root + "/state", "--workspace", str(workspace), "mcp"],
                env=dict(os.environ))
            async with Client(parameters, read_timeout_seconds=20) as client:
                tools = (await client.list_tools()).tools
                self.assertEqual({tool.name for tool in tools}, {
                    "flagship_status", "flagship_find_tools", "flagship_resolve_tool", "flagship_gpu_check",
                    "flagship_tool_info", "flagship_list_files", "flagship_inspect_file", "flagship_read_text"})
                self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))
                status = await client.call_tool("flagship_status", {})
                self.assertFalse(status.is_error)
                self.assertEqual(len(status.structured_content["providers"]), 7)
                digest = await client.call_tool("flagship_inspect_file", {"path": "sample.txt"})
                self.assertEqual(digest.structured_content["sha256"], hashlib.sha256(fixture).hexdigest())
                resource = await client.read_resource("flagship://capabilities")
                self.assertIn("stdio", resource.contents[0].text)
                for name, arguments in (
                    ("flagship_read_text", {"path": "../outside"}),
                    ("flagship_read_text", {"path": "sample.txt", "max_bytes": 1000000}),
                    ("flagship_gpu_check", {"profile": "foreign"}),
                    ("flagship_tool_info", {"tool": "bash", "profile": "kali"}),
                    ("flagship_tool_info", {"tool": "nmap", "profile": "kali", "detail": "devices"}),
                ):
                    with self.subTest(name=name, arguments=arguments):
                        result = await client.call_tool(name, arguments)
                        self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()
