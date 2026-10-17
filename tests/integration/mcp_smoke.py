#!/usr/bin/env python3
"""Opt-in MCP acceptance against seven existing running providers; local fixtures only."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def verify(args, report):
    workspace = args.workspace.resolve()
    directory = Path(tempfile.mkdtemp(prefix="flagship-mcp-proof-", dir=workspace))
    name = directory.relative_to(workspace).as_posix() + "/literal ; $(name).txt"
    fixture = b"Flagship MCP harmless local fixture\n"
    (workspace / name).write_bytes(fixture)
    parameters = StdioServerParameters(command=str(args.python), args=["-m", "flagship",
        "--state-dir", str(args.state_dir), "--workspace", str(workspace), "mcp"], env=dict(os.environ))

    async with Client(parameters, read_timeout_seconds=180) as client:
        tools = (await client.list_tools()).tools
        report["tools"] = [{"name": item.name, "input_schema": item.input_schema,
                            "output_schema": item.output_schema} for item in tools]
        assert len(tools) == 8 and all(item.output_schema for item in tools)

        async def call(name, arguments):
            result = await client.call_tool(name, arguments)
            if result.is_error or result.structured_content is None:
                raise RuntimeError(f"{name}: {result.content}")
            value = result.structured_content
            report["calls"].append({"name": name, "arguments": arguments, "result": value})
            print(name + " " + json.dumps(arguments) + ": passed", flush=True)
            return value

        status = await call("flagship_status", {})
        assert len(status["providers"]) == 7
        assert all(row["managed"] and row["status"] == "running" for row in status["providers"])
        found = await call("flagship_find_tools", {"query": "hashcat", "limit": 1})
        assert len(found["tools"]) == 1 and found["total"] >= 1
        for profile, tool in (("kali", "exiftool"), ("parrot", "nmap"), ("remnux", "yara"),
                              ("backbox", "foremost"), ("sift", "mmls"), ("caine", "dc3dd"), ("tsurugi", "fls")):
            resolved = await call("flagship_resolve_tool", {"tool": tool, "profile": profile})
            assert resolved["selected"]["profile"] == profile
            info = await call("flagship_tool_info", {"tool": tool, "profile": profile})
            assert info["exit_code"] == 0
            gpu = await call("flagship_gpu_check", {"profile": profile})
            assert gpu["report"]["cuda"]["passed"]
        # Preserve an actual application limitation instead of turning it into a success claim.
        caine = await call("flagship_tool_info", {"tool": "hashcat", "profile": "caine", "detail": "devices"})
        report["caine_hashcat_device_exit_code"] = caine["exit_code"]
        listing = await call("flagship_list_files", {"path": directory.name})
        assert listing["entries"][0]["name"] == Path(name).name
        digest = await call("flagship_inspect_file", {"path": name})
        assert digest["sha256"] == hashlib.sha256(fixture).hexdigest()
        text = await call("flagship_read_text", {"path": name})
        assert text["text"] == fixture.decode() and not text["truncated"]
        bad = await client.call_tool("flagship_read_text", {"path": "../outside"})
        assert bad.is_error
        report["traversal_rejected"] = True
        resource = await client.read_resource("flagship://capabilities")
        report["capabilities"] = json.loads(resource.contents[0].text)
        report["fixture"] = {"path": name, "sha256": digest["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; retain prior receipts and choose a new name")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "passed": False, "calls": [],
              "mcp_sdk_version": version("mcp"), "server_python": str(args.python),
              "scope": "Real stdio MCP and seven real providers; fixed local version/device diagnostics and generated workspace fixture"}
    try:
        asyncio.run(verify(args, report))
        report["passed"] = True
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(json.dumps({"passed": report["passed"], "receipt": str(args.output)}), flush=True)


if __name__ == "__main__":
    main()
