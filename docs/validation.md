# Validation

## Fresh acceptance environment — 2026-10-17

The current acceptance environment is **FlagshipOS-Full**, a new Ubuntu 26.10 amd64 WSL2 distribution imported directly onto D:. It came from Canonical's original image, not a copy of the earlier test distro. Before setup it had 556 installed packages, no test user, and no container storage.

The image SHA-256 matched the publisher's checksum: `6c4d4affa03efa4c55ce0411242a2d28c0a8682ed3e5c30b3169ddb397777bff`.

Testing uses an ordinary UID 1000 account, rootless Podman and a native Linux checkout. The host retains Ubuntu's repositories.

| Component | Observed version |
| --- | --- |
| Ubuntu | 26.10, Stonking Stingray |
| WSL kernel | 6.18.33.2-microsoft-standard-WSL2 |
| Python | 3.14.8 |
| Podman | 5.8.6 |
| Distrobox | 1.8.2.5 |

Verified on this fresh environment:

- Bootstrap installation and repeated package installation succeeded.
- **121 automated tests passed**, with no skips. They cover argument boundaries, private state, ownership and configuration drift, immutable image receipts, checksum snapshots, selected network helpers, provider selection, workspace mapping, failure cleanup, installation-evidence parsing, explicit rootfs owner mappings and container startup compatibility.
- Compilation, wheel creation, installation outside the checkout, all seven catalog entries, and the exact bytes of all five bundled recipes passed verification.
- The first actual toolkit build exposed a missing `pasta` dependency in bootstrap. Podman stopped before Kali's package installation. Installing Ubuntu's `passt` package resolved that missing executable; bootstrap and readiness checks have been updated. A successful dependency check alone did not establish that image builds worked.
- Strict CAINE conversion correctly refused a Unix socket in the release filesystem. The converter now offers an explicit, audited socket-only omission mode. A small real ISO fixture verified that this mode preserves file bytes, numeric ownership, permissions, hard links and a FIFO while recording the omitted socket. The full CAINE archive subsequently passed independent checksum and package-fidelity checks described below.
- An isolated rootless Ubuntu 24.04 check verified `SYSTEMD_OFFLINE=1` can defer service operations during an image build without starting the test service. REMnux and SIFT scope that setting to their installer invocation. Their complete installations and runtime service behavior still require verification.

The [code verification receipt](evidence/2026-10-17/code-verification.json) records the tested source fingerprint, exact recipe hashes and individual check results. Documentation and evidence files may subsequently change; the separate code/configuration/test fingerprint identifies the tested implementation.

## Full collection acceptance

This work is **in progress**. A green unit suite or a base-container smoke test is not a complete seven-collection installation.

| Collection | Required full installation | Acceptance result |
| --- | --- | --- |
| Kali | kali-linux-everything, including recommendations | Full image built; managed runtime audit pending |
| Parrot | parrot-tools-full, including recommendations | Full image built; managed runtime audit pending |
| REMnux | Upstream full dedicated installer | Retry passed all 1,091 installer states; image completion and runtime acceptance pending |
| BackBox | BackBox 9 backbox-tools, including recommendations | Full image, managed runtime/package audit and isolated browser integration passed |
| SIFT | Pinned upstream Cast release in desktop mode | First installer failed; corrected full retry running |
| CAINE | Complete verified CAINE 14 release filesystem | Archive verified and imported; first startup failed; compatibility retry pending |
| Tsurugi | Complete verified LAB 26.03 release filesystem | Original archive verified; import found 22 files with unmappable owner IDs; explicit owner conversion running |

Shared-shell acceptance must run actual commands from all seven providers, preserve literal arguments and exit codes, work with shared files and directories containing spaces, demonstrate a pipeline, and record collision preferences and provider provenance. It has not yet passed.

The installation audit now distinguishes exact version fidelity from package preservation. Parrot's first Distrobox startup upgraded 30 base packages. The audit retains the original strict version differences and separately requires every originally installed package and architecture to remain installed at the same or a newer version, using Debian's version comparator. Missing packages, changed architectures and downgrades fail. ISO inventories must also match the conversion receipt and package baseline before this comparison is available.

### BackBox build corrections

The actual build exposed two gaps: BackBox's archive did not supply its required `metasploit-framework` package, and Ubuntu's Chromium transitional package returned success after skipping the browser's Snap payload. The recipe now uses Rapid7's authenticated vendor repository and Canonical's checksum-pinned Chromium/ChromeDriver payload with the existing Ubuntu libraries. It retains the full metapackage and recommendations. The resulting image passed a real local Selenium interaction through the ordinary command names and default browser discovery as UID 1000, without sandbox-disabling flags. [Receipts and scope](evidence/2026-10-17/README.md) distinguish these completed checks from pending seven-provider acceptance.

### CAINE archive fidelity

The verified CAINE 14 ISO produced a 13,383,929,856-byte tar with 481,144 entries, SHA-256 `902ce5f4f509a09d2839f0f600dd8fbc9a9e2193949c4b9653fcc9730219de8e`. An independent read of the archive matched all 4,561 package/version records in the ISO's manifest: 4,468 installed and 93 configuration-only records. The latter are part of the upstream release metadata, not packages lost during conversion.

The explicit omission receipt lists exactly 31 Unix sockets from heartbeat and postfix runtime directories. No other omissions were accepted. Custom CAINE directories were retained and inventoried, including `/usr/share/caine`, `/usr/local/bin` and `/opt`; this observation is not an exhaustive upstream custom-tool manifest or a runtime test. The [archive receipts and full package inventory](evidence/2026-10-17/README.md) are retained for review.

### Tsurugi package baseline

The verified LAB 26.03 ISO contains an empty `filesystem.manifest`. The acceptance pipeline therefore reads `/var/lib/dpkg/status` directly from an independently extracted source SquashFS and records 4,147 package/version entries as a derived baseline. This is not a publisher manifest. The converted archive passed comparison against that baseline, with 4,129 installed records and 18 configuration-only records. Its package-database hash matches the source database exactly.

The 34,581,695,488-byte archive contains 1,006,847 entries, with exactly 26 verified Unix sockets omitted. Its SHA-256 is `25a641c3dd132e5276392c07331f060e02e8ce4cdec6f51ce448130321e2ab38`. [Source verification, package inventories and conversion receipts](evidence/2026-10-17/README.md) retain the evidence. Runtime acceptance remains pending.

### Full-filesystem startup corrections

CAINE's first startup failed because its APT configuration still referred to installation media. Its logs also showed Distrobox choosing APT-RPM because the complete toolkit includes `rpm`, despite using a Debian package database. The startup adapter now prefers `dpkg-query` in the two affected Distrobox 1.8.2.5 branches. It preserves the installed host scripts and writes a verified private copy for container mounts, retaining upstream license notices. The live-release pre-init hook disables CD-ROM entries with exact original-file backups; network repositories remain configured.

Tests execute the corrected detection in a real POSIX shell with both package commands present, check the private runtime's integrity, and exercise source-file changes and Distrobox's additional shell parsing. CAINE's corrected real startup has not yet passed; those tests alone do not establish it.

### REMnux installer failure

The first full dedicated installation reported 1,079 successful and 12 failed Salt states. Its first reported failure depended on the Thug package state. The failed image was not registered as prepared. A second complete installation with the same recipe passed all 1,091 states with zero failures. The [parsed result receipt](evidence/2026-10-17/remnux-installer-results.json) records every state result and the original YAML hash. The first failure's cause was not conclusively reproduced; this success does not establish an identified repair for it. Image completion and managed runtime acceptance remain separate checks.

### SIFT full desktop retry

The first desktop installation reported 810 successful and 13 failed states. Its log contained an ExifTool archive download returning HTTP 404. The recipe now seeds the exact author-checksummed archive from the author's SourceForge distribution; Salt still performs its own verification and full installation. The upstream desktop states also require a real UID 1000 D-Bus session and Ubuntu Dock's schema. A disposable Ubuntu check reproduced the missing-session error and verified persistent settings with a real session. The corrected recipe supplies that session and the Dock package. The full retry is running; these bounded diagnostics do not establish that all 13 original failures are fixed.

Full installation is distinct from every tool working under WSL. Kernel modules, device access, live-system write blocking, desktop integration and long-running services require their own validation. SIFT's default UID 1000 path has specific integration support; arbitrary host UIDs and migration of original distro home configuration remain unverified.

## Earlier bounded checks

An earlier disposable Ubuntu 26.10 environment passed Kali and Parrot base lifecycle checks. A harmless synthetic ISO conversion preserved file contents, numeric ownership and a symbolic link, and a toy rootfs import recorded matching archive and image checksums. These were plumbing checks, not full CAINE or Tsurugi installations. They do not substitute for the fresh acceptance environment above.

Some preliminary unit tests ran on an existing Ubuntu 26.04 distribution. All acceptance work after the clean-install correction uses the new Ubuntu 26.10 distribution on D:.

## Continuous integration

[Package CI](https://github.com/mingusb/FlagshipOS/actions/runs/39064706990) and the [real Kali base-container smoke test](https://github.com/mingusb/FlagshipOS/actions/runs/39064740823) passed commit `20f7225`, including SIFT desktop setup and explicit rootfs ownership handling. See [GitHub Actions](https://github.com/mingusb/FlagshipOS/actions) for later exact-commit results.

The hosted container job uses Ubuntu 24.04 and a pinned Distrobox version. It validates a base container with harmless local commands; it does not prove seven full collections work on WSL.
