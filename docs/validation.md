# Validation

## Host and package validation — 2026-10-17

A fresh, disposable **Ubuntu 26.10 amd64 WSL2** installation was imported from the official Ubuntu WSL image. Its SHA-256 matched the publisher's checksum, `6c4d4affa03efa4c55ce0411242a2d28c0a8682ed3e5c30b3169ddb397777bff`. Testing used an ordinary Linux account with rootless Podman. The user's existing distributions were not modified.

| Component | Observed version |
| --- | --- |
| Ubuntu | 26.10, Stonking Stingray |
| WSL kernel | `6.18.33.2-microsoft-standard-WSL2` |
| Python | 3.14.8 |
| Podman | 5.8.6 |
| Distrobox | 1.8.2.5 |

Verified results:

- Bootstrap installed the package from a native Linux checkout; a repeated installation succeeded.
- `flagship doctor --json` reported every dependency and rootless-engine check passing.
- **56 automated tests passed**, with no skips, on Ubuntu 26.10. These include subprocess argument handling, file locking, ownership and configuration drift, snapshot integrity, failure cleanup, and termination of signal-ignoring child processes.
- Python compilation, wheel creation and bundled-catalog inspection passed. A separate virtual environment installed the wheel and loaded all seven profiles from outside the source checkout.
- A real synthetic ISO was converted with `xorriso` and `sqfs2tar`; file contents, numeric root ownership and a symbolic link were preserved.
- The resulting harmless toy rootfs was imported through Podman. The recorded archive checksum and image identity matched. This validates import plumbing; the fixture was **not a CAINE distribution**.
- Host APT sources remained the official Ubuntu archive and security repositories.

The earlier unit suite also passed on Ubuntu 26.04 WSL. Linux test results do not imply native Windows execution support.

## Profile verification scope

The initial catalog contains three official registry profiles and four experimental rootfs-import profiles. The three registry digests were verified against official upstream image references and Docker Registry metadata. Complete runtime results will be recorded here after their dedicated lifecycle checks finish; digest verification alone does not establish runtime support.

No full SIFT, BackBox, CAINE or Tsurugi root filesystem has been runtime-validated in this release. All four remain explicitly experimental. No claim is made that every upstream package, GUI application, service or device workflow functions in WSL.

## Continuous integration

See [GitHub Actions](https://github.com/mingusb/FlagshipOS/actions) for the exact commits tested. Ordinary CI runs the automated suite and installs the built wheel. The manually triggered container workflow tests a Kali base environment with harmless local commands on hosted Ubuntu 24.04; that is separate from WSL evidence. It deliberately retains its temporary home/workspace files for runner disposal because container-created files can have subordinate user IDs.
