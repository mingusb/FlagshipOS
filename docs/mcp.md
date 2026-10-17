# Flagship MCP server

Flagship's local [Model Context Protocol](https://modelcontextprotocol.io/docs/learn/server-concepts) server gives an assistant structured access to provider status, executable discovery, bounded diagnostics and the shared workspace. It uses the [official Python SDK](https://github.com/modelcontextprotocol/python-sdk), pinned to the tested 2.3.0 release, over standard input/output.

[AGENTS.md](../AGENTS.md) explains how repository-aware assistants should use Flagship. MCP clients receive operational instructions during connection and through `flagship://capabilities`; those instructions do not depend on the client reading repository files.

## Install and connect

Inside the Ubuntu WSL installation that owns the environments:

```bash
cd ~/FlagshipOS
bash scripts/bootstrap.sh --skip-system-packages --with-mcp
flagship tools --refresh
flagship mcp
```

The final command waits for an MCP client. Point the client's stdio configuration at the absolute path to `~/.local/bin/flagship`, with `mcp` as its argument. The client launches and stops the server; no separate background service is needed. The workspace must already exist. Put `--workspace /absolute/path` and `--state-dir /absolute/path` before `mcp` when using nondefault locations.

For a Windows MCP client that accepts `mcpServers` configuration, replace the distribution name and Linux username in this example:

```json
{
  "mcpServers": {
    "flagship": {
      "command": "wsl.exe",
      "args": [
        "--distribution", "FlagshipOS-Full",
        "--user", "YOUR_LINUX_USER",
        "--exec", "/home/YOUR_LINUX_USER/.local/bin/flagship",
        "mcp"
      ]
    }
  }
}
```

Use the ordinary Linux account that created the collections. A different account has different rootless containers and state. Clients with a different configuration format use the same command and argument array. Refresh/reconnect the client after adding the entry.

## Available operations

| MCP tool | Result |
| --- | --- |
| `flagship_status` | All seven providers, current ownership/configuration status and shared workspace |
| `flagship_find_tools` | Paginated substring search with provider filters, alternatives and inventory timestamp |
| `flagship_resolve_tool` | Selected provider, explicit provider override, saved preference and host-command priority |
| `flagship_gpu_check` | Bounded CUDA memory test and separate OpenCL enumeration for a running provider |
| `flagship_tool_info` | Fixed version queries for eight representative tools; Hashcat device discovery with `detail: "devices"` |
| `flagship_list_files` | Paginated entries in one workspace directory |
| `flagship_inspect_file` | SHA-256, size and first 64 bytes as hex for a file up to 256 MiB |
| `flagship_read_text` | Up to 64 KiB of UTF-8 text, with an explicit truncation flag |

The `flagship://capabilities` resource describes the server, catalog and workspace. Tool results contain structured JSON. Diagnostic results preserve exit status, stderr, selected provider and observation time. Errors distinguish unavailable inventory, a stopped provider, invalid input and an inaccessible file.

Try asking the connected assistant: “Which providers have Hashcat?”, “Check CUDA in SIFT”, or “Hash `evidence/sample.bin` and show the text in `notes.txt`.” Paths are relative to the shared workspace. `flagship_find_tools` searches a cached inventory while validating current container identities; refresh from the terminal after changing installed tools.

## Access and verification scope

This interface provides inspection and fixed diagnostics. It does not expose general shell execution, arbitrary command arguments, installation, container lifecycle changes or preference writes. GPU diagnostics require an already-running managed container and never request GPU setup. Provider selection is an explicit argument and does not change the user's default.

Workspace reads walk directory descriptors and reject traversal, symlinks, multiple hard links, special files and cross-filesystem paths. Names containing spaces or literal shell syntax are treated as filenames. Responses are bounded; backend processes have deadlines, bounded output and cancellation cleanup. The server uses the host account's permissions and is not an isolation boundary against another process running as that same account. A connected client can read eligible files in the configured workspace; use a dedicated workspace for material intended for that client.

All operations carry read-only annotations. File contents and upstream command output are labeled untrusted data. The server listens only on stdio, with no network listener or credentials of its own. CUDA success means the documented small memory test passed; [application-specific GPU limitations](gpu.md) still apply.

## Tests

```bash
python3 -m pip install '.[mcp]'
python3 -m unittest discover -s tests -v
```

The MCP tests exercise a real subprocess handshake, tool and resource discovery, structured responses, schema rejection, descriptor-based file access, output limits, timeouts and cancellation. Tests with a temporary empty workspace do not establish live container functionality; the separately published live acceptance receipts identify that scope.

On 2026-10-17, the [live seven-provider MCP check](evidence/2026-10-17/mcp-seven-providers.json) passed 27 protocol calls against the installed public package: discovery, resolution, fixed version queries, CUDA checks, and generated workspace-file inspection. CAINE's failing Hashcat device query remains exit 255 in the structured result. The [Windows configuration check](evidence/2026-10-17/windows-mcp.json) separately passed initialization and discovery through `wsl.exe`. See [the complete validation scope](validation.md#mcp-and-windows-entry-points).
