# FlagshipOS

[![CI](https://github.com/mingusb/FlagshipOS/actions/workflows/ci.yml/badge.svg)](https://github.com/mingusb/FlagshipOS/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A unified CTF workbench for Ubuntu on WSL2.**

FlagshipOS makes Debian-family security and forensic tool collections available through one terminal command. Each collection keeps its own package database, libraries and home directory. Your projects live in a shared workspace. Ubuntu's APT sources stay Ubuntu-only.

The `flagship` command manages rootless Podman containers through Distrobox. It includes seven profiles: **Kali, Parrot, REMnux, SIFT, BackBox, CAINE and Tsurugi**.

This is an environment manager built on Ubuntu, not a bootable replacement operating system. Version 0.1 provides three official container profiles and four experimental import profiles. It does not claim to install every package from seven distributions or make every tool compatible with WSL.

## Quick start

Start with a fresh **Ubuntu 26.10 on WSL2**, signed in as a normal Linux user. Obtain the WSL image from [Ubuntu's official release directory](https://releases.ubuntu.com/26.10/), verify it against the publisher's checksums, and follow [Ubuntu's WSL installation instructions](https://documentation.ubuntu.com/wsl/latest/guides/install-ubuntu-wsl2/). Python 3.11 or newer is required.

Run inside Ubuntu, keeping the checkout and work files in the Linux filesystem:

```bash
git clone https://github.com/mingusb/FlagshipOS.git
cd FlagshipOS
bash scripts/bootstrap.sh --yes
export PATH="$HOME/.local/bin:$PATH"

flagship doctor
flagship profiles
flagship plan kali
flagship create kali
flagship run kali -- cat /etc/os-release
```

The bootstrap installs Ubuntu's Podman, Distrobox and Python prerequisites, then installs FlagshipOS into a private virtual environment. It requests sudo only for Ubuntu package installation. It does not create tool environments or alter your shell configuration. Review the script first; omit `--yes` to retain APT's installation prompt. Use `--skip-system-packages` when an administrator has already installed the prerequisites.

The official Kali container starts with a minimal filesystem. Provision its headless tool collection explicitly:

```bash
flagship --dry-run provision kali
flagship provision kali
flagship check kali
```

Provisioning may download substantial data. `check` runs representative version commands, not network scans, and does not certify every installed tool.

## Collections

| Profile | Source | Initial coverage |
| --- | --- | --- |
| `kali` | Official Kali container, pinned by digest | Minimal base; `provision` adds Kali's headless metapackage |
| `parrot` | Official Parrot Security container, pinned by digest | Upstream's command-line collection; GUI tools excluded |
| `remnux` | Official REMnux Noble container, pinned by digest | Upstream's container collection, with documented exclusions |
| `sift` | Import a genuine, provisioned SIFT root filesystem | Experimental import path |
| `backbox` | Import a verified BackBox filesystem | Experimental import path |
| `caine` | Import a verified CAINE filesystem | Experimental import path |
| `tsurugi` | Import a verified Tsurugi LAB filesystem | Experimental import path |

See [profile sources, image digests and import instructions](docs/profiles.md). An import profile is never silently replaced with an empty Ubuntu container. No distribution images are redistributed by this repository.

## One workspace, separate dependencies

```bash
flagship create parrot
flagship create remnux
flagship run parrot -- bash
flagship run remnux -- yara --version
```

The host workspace defaults to `~/flagship` and appears as `/workspace` inside every environment. Commands start in `/workspace`; pass paths under that directory when referring to shared files.

```bash
printf 'example\n' > ~/flagship/example.txt
flagship run kali -- cat /workspace/example.txt
```

To use another directory, provide the same `--workspace` when creating an environment. Existing environments retain their recorded workspace; FlagshipOS refuses a conflicting path instead of silently changing mounts. Keep runtime state and Podman storage on the Linux filesystem, not under `/mnt/c`.

Distrobox builds shell commands internally. For dependable path handling, FlagshipOS requires absolute Linux home, state and workspace paths containing only letters, digits, `/`, `_`, `.` and `-`. Paths with spaces or shell characters, custom Distrobox configuration and remote Podman connections are rejected with an explanation.

Container names are `flagship-<profile>`. State, image locks and per-profile homes are stored under `${XDG_DATA_HOME:-~/.local/share}/flagship`. Each container has an installation identity and ownership labels; FlagshipOS refuses to adopt or remove an unrelated container with the same name.

## Commands

| Command | Purpose |
| --- | --- |
| `flagship profiles --json` | Inspect all profile metadata |
| `flagship doctor --json` | Check host dependencies and rootless engine readiness |
| `flagship plan kali` | Print the proposed creation steps without making changes |
| `flagship create kali` | Create a managed environment; repeating it is safe |
| `flagship provision kali` | Install the profile's explicitly listed packages |
| `flagship run kali -- COMMAND ...` | Run a command using that environment's dependencies |
| `flagship check kali` | Run the profile's representative version checks |
| `flagship status --json` | Inspect managed environments |
| `flagship import-rootfs caine rootfs.tar --sha256 HASH` | Verify and register a real root filesystem |
| `flagship remove kali --yes` | Remove that managed container while retaining home/workspace data |

Use `--dry-run` to review mutating operations. Global options are best placed before the subcommand, especially for `run`: everything after its profile and optional `--` is command input. Run `flagship --help` for the complete interface.

## Imports

For an import profile, first obtain a clean upstream filesystem and verify its authenticity. The SHA-256 argument records the exact artifact used; a hash calculated from an untrusted download does not establish its origin.

Importing makes a private temporary copy while hashing, then sends those exact verified bytes to Podman. Allow free space for another copy of the archive in the state directory as well as Podman's unpacked image storage.

```bash
flagship import-rootfs caine /path/to/verified-rootfs.tar --sha256 FULL_SHA256
flagship create caine
flagship check caine
```

For supported live-ISO layouts, `scripts/iso-to-rootfs.py` converts the embedded SquashFS into a tar archive using `xorriso` and `sqfs2tar`. It does not mount the image or extract its filesystem tree onto the host. It makes a private copy, verifies that copy against the supplied ISO checksum, and refuses to overwrite output. Allow disk space for the ISO copy, embedded SquashFS and output tar together. [Full import guide](docs/profiles.md#import-profiles).

## Operational boundaries

- **Dependency separation is not a malware sandbox.** Distrobox intentionally integrates with the host, including access to host files. Separate homes prevent ordinary configuration collisions but do not conceal your host home. Use a separately isolated VM when executing untrusted samples.
- **WSL and containers share a kernel.** Custom kernels, forensic write-blocking guarantees, Wi-Fi features, some services and device workflows do not transfer automatically.
- **Image identity is pinned; installed packages remain mutable.** Distrobox installs integration prerequisites, and explicit provisioning uses upstream repositories. Preserve artifacts and package inventories when exact software reproducibility matters.
- **No silent updates.** Image changes are reviewed changes to the profile catalog. Existing local image locks remain recorded. See [maintenance and recovery](docs/operations.md).

## Development and verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/check_wheel.py dist
```

Tests cover command arguments, dry runs, ownership, checksums, file locking, atomic writes and import failure handling. Pull-request CI also builds and checks the installable wheel. A manually triggered container workflow exercises a real Kali base environment on hosted Ubuntu. That workflow is distinct from WSL verification. See [validation evidence](docs/validation.md) for the precise release scope.

## License

FlagshipOS code is [MIT-licensed](LICENSE). Upstream distributions, container images and packaged tools retain their own licenses. FlagshipOS is an independent project and is not endorsed by Canonical or the listed distributions.
