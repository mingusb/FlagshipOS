# FlagshipOS

[![CI](https://github.com/mingusb/FlagshipOS/actions/workflows/ci.yml/badge.svg)](https://github.com/mingusb/FlagshipOS/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Seven Debian-family tool collections, one workspace and shell, on Ubuntu WSL2.**

FlagshipOS manages Kali, Parrot, REMnux, SIFT, BackBox, CAINE and Tsurugi through rootless Podman and Distrobox. Each collection keeps its own libraries and package database. Ubuntu's APT sources stay Ubuntu-only. Executable discovery and routing make installed tools available from one terminal.

**Status: experimental, with seven-collection acceptance completed on fresh Ubuntu 26.10 WSL2.** All seven full installations pass the combined managed package audit and bounded CUDA memory check. The actual shared-shell demonstration passes all seven providers, a cross-provider pipeline, shared files, provider switching and failure-code preservation. Discovery indexes 11,307 unique command names. The MCP-enabled package passes 163 automated tests, including a real protocol connection and installed-wheel checks. These bounded results do not establish universal tool compatibility or production readiness. See [validation and receipts](docs/validation.md), the [captured demonstration](docs/evidence/2026-10-17/seven-provider-transcript.txt) and [application-specific GPU results](docs/gpu.md).

## Start on Ubuntu WSL2

Use a fresh **Ubuntu 26.10 WSL2** installation and a normal Linux user. Follow [Ubuntu's WSL instructions](https://documentation.ubuntu.com/wsl/latest/guides/install-ubuntu-wsl2/) and verify the image from the [official release directory](https://releases.ubuntu.com/26.10/). Keep the checkout, container storage and workspace in the Linux filesystem. Python 3.11 or newer is required.

```bash
git clone https://github.com/mingusb/FlagshipOS.git
cd FlagshipOS
bash scripts/bootstrap.sh --yes
export PATH="$HOME/.local/bin:$PATH"
flagship doctor
flagship profiles
```

Review the bootstrap before running it. It installs Ubuntu prerequisites and a private Python environment; it does not create tool environments or edit your shell configuration. Omit `--yes` to retain APT's prompt. Use `--skip-system-packages` if prerequisites are already installed.

## Prepare collections

`prepare` builds a local toolkit image before Distrobox connects it to your workspace. Builds can require substantial downloads, disk space and time. Review the recipe and dry run first:

```bash
flagship --dry-run prepare kali
flagship prepare kali
flagship create kali
flagship check kali
```

Repeat `prepare` and `create` for `parrot`, `remnux`, `sift` and `backbox`. Creation uses the recorded immutable image ID; repeating `create` reuses a matching managed container.

| Profile | Full collection method |
| --- | --- |
| `kali` | Official pinned Kali base plus `kali-linux-everything`, including recommends |
| `parrot` | Official pinned Security base plus `parrot-tools-full`, including recommends |
| `remnux` | Official pinned Noble container expanded with the upstream full installer |
| `sift` | Ubuntu 24.04 plus the upstream SIFT desktop installation through Cast |
| `backbox` | Ubuntu 24.04 plus the signed BackBox 9 repository and `backbox-tools`, including recommends |
| `caine` | Extract and import the verified CAINE 14 release filesystem |
| `tsurugi` | Extract and import the verified Tsurugi LAB 26.03 release filesystem |

Only CAINE and Tsurugi need official ISO extraction in this workflow. Follow the [profile and import guide](docs/profiles.md). Full collection means the selected upstream collection or release filesystem, not every historical package or guaranteed WSL functionality.

Direct `create` on Kali, Parrot or REMnux without `prepare` uses an upstream image with omissions. `provision` installs only that profile's explicitly listed packages; it does not replace all five recipes. Existing containers must be removed before preparing replacements. See [persistence and replacement](docs/operations.md).

## Use one terminal

After creating environments, discover their executable commands:

```bash
flagship tools --refresh
flagship which nmap
flagship exec nmap -- --version
flagship exec --profile parrot nmap -- --version
flagship prefer nmap parrot
flagship shell
```

The shell starts in your shared workspace. Host commands and shell builtins keep priority; an indexed specialist command missing on the host routes to a container. `flagship exec` explicitly selects a container tool even when a host command has the same name. `which` explains the choice and alternatives.

Without an override or saved preference, providers follow catalog order: Kali, Parrot, REMnux, SIFT, BackBox, CAINE, Tsurugi. Clear a choice with `flagship prefer nmap --clear`. Refresh the inventory after installing tools or replacing containers. Discovery confirms executable presence, not complete application functionality.

The default workspace is `~/flagship`, mounted as `/workspace` in every environment. Routed commands preserve a current subdirectory inside the workspace; from elsewhere they start at `/workspace`. File arguments are passed literally. Direct profile execution remains available with `flagship run remnux -- yara --version`.

## Commands

For assistants, the optional [Flagship MCP server](docs/mcp.md) exposes executable and installed-package search, man-page discovery and man/help inspection, bounded execution of indexed collection tools, fixed diagnostics and shared-workspace inspection. Command execution can modify files or access networks as the provider user. Install with `bash scripts/bootstrap.sh --skip-system-packages --with-mcp`, then connect the client's stdio transport to `flagship mcp`.

[AGENTS.md](AGENTS.md) provides operating and development instructions for assistants reading the repository. Connected MCP clients receive server instructions and can read `flagship://capabilities` without opening the checkout.

| Command | Purpose |
| --- | --- |
| `profiles`, `doctor`, `status` | Inspect metadata, prerequisites and state; each accepts `--json` |
| `mcp` | Start the optional local MCP server for an assistant client |
| `plan PROFILE` | Preview container creation |
| `prepare PROFILE` | Build and register a bundled full collection recipe |
| `create PROFILE` | Create or reuse a matching managed container |
| `provision PROFILE` | Install that profile's listed packages in an existing container |
| `run PROFILE -- COMMAND ...` | Run directly in one environment |
| `check PROFILE` | Run representative local version checks |
| `gpu PROFILE [--setup] [--json]` | Connect the WSL NVIDIA driver when requested; check CUDA and report OpenCL GPU discovery |
| `tools --refresh`, `tools --json` | Refresh or inspect the executable inventory |
| `which TOOL`, `which --profile PROFILE TOOL` | Explain selection; supports `--json` |
| `exec [--profile PROFILE] TOOL -- ARG ...` | Run the selected indexed executable |
| `prefer TOOL PROFILE`, `prefer TOOL --clear` | Save or clear a provider preference |
| `shell`, `shell -- COMMAND ...` | Open a shell or run a command with routing available |
| `import-rootfs PROFILE FILE --sha256 HASH` | Verify and register a genuine distribution filesystem |
| `remove PROFILE --yes` | Remove the managed container, retaining home/workspace files |

Put `--state-dir`, `--workspace` and `--dry-run` before the subcommand. For `exec`, put `--profile` before the tool name; later arguments belong to the tool. Dry runs execute no commands.

## Boundaries and license

Full collection startup currently targets Distrobox 1.8.2.5. Flagship retains a private, content-addressed copy of the installed scripts with corrections for Debian package-manager detection and copying default home files with literal filenames. Debian installations can include the `rpm` analysis tool without being mistaken for RPM-based systems, and desktop shortcuts with spaces remain intact. Live-release startup disables unavailable CD-ROM sources with backups, reconstructs missing shadow databases with standard account tools, and rebuilds a missing password-quality dictionary cache. Tsurugi's existing Tor repository key is renewed only after verifying the expected primary fingerprint and signed repository metadata. Existing account databases and package-signature checks are retained.

On an NVIDIA-capable WSL host, new environments connect the Windows-provided CUDA driver automatically. Existing environments use `flagship gpu PROFILE --setup`. CUDA, OpenCL and individual application support are checked separately; see [GPU setup and verification](docs/gpu.md).

Linux home, state and workspace paths must contain only letters, digits, `/`, `_`, `.` and `-`. Custom Distrobox configuration and remote Podman connections are rejected. Containers are named `flagship-PROFILE`; state defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/flagship`. Use consistent state/workspace options.

Distrobox deliberately integrates with host files. Separate dependencies and homes are **not a malware sandbox**. WSL's shared kernel does not reproduce distribution kernels, forensic write blocking or every device/service workflow. Image pins identify source filesystems, but live package repositories make builds mutable. See [operations and recovery](docs/operations.md).

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/check_wheel.py dist
```

FlagshipOS's own code is [MIT-licensed](LICENSE). Upstream distributions, images and tools retain their individual licenses. The locally copied Distrobox scripts retain their GPL-3.0 notices; the MIT license does not cover them. This repository does not redistribute those images or scripts and is not endorsed by Canonical or the listed distributions.
