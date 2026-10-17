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
- **159 automated tests passed**, with no skips. They cover argument boundaries, private state, ownership and configuration drift, immutable image receipts, checksum snapshots, selected network helpers, provider selection, workspace mapping, failure cleanup, installation-evidence parsing, explicit rootfs owner mappings, container startup compatibility, bounded package repair, guarded WSL GPU integration, and the optional MCP server's real protocol, filesystem and process boundaries.
- Compilation, wheel creation, installation outside the checkout, all seven catalog entries, and the exact bytes of all five bundled recipes passed verification.
- The first actual toolkit build exposed a missing `pasta` dependency in bootstrap. Podman stopped before Kali's package installation. Installing Ubuntu's `passt` package resolved that missing executable; bootstrap and readiness checks have been updated. A successful dependency check alone did not establish that image builds worked.
- Strict CAINE conversion correctly refused a Unix socket in the release filesystem. The converter now offers an explicit, audited socket-only omission mode. A small real ISO fixture verified that this mode preserves file bytes, numeric ownership, permissions, hard links and a FIFO while recording the omitted socket. The full CAINE archive subsequently passed independent checksum and package-fidelity checks described below.
- An isolated rootless Ubuntu 24.04 check verified `SYSTEMD_OFFLINE=1` can defer service operations during an image build without starting the test service. REMnux and SIFT scope that setting to their installer invocation. Both complete installers subsequently passed; comprehensive runtime service behavior remains unverified.

The [MCP-enabled code verification receipt](evidence/2026-10-17/code-verification-mcp.json) records the tested source fingerprint, exact recipe hashes and individual check results. It includes a second protocol test against the installed wheel outside the checkout. Documentation and evidence files changed during verification; the separate code/configuration/test fingerprint remained unchanged and identifies the tested implementation. The earlier 143-test receipt is retained separately.

## Full collection acceptance

The [combined full package audit](evidence/2026-10-17/seven-collection-package-audit.json) passed all seven managed providers after GPU setup and startup repairs. The [actual shared-shell demonstration](evidence/2026-10-17/seven-provider-demo.json) also passed. Full collection means the specified upstream metapackage, installer or release filesystem; this is not a claim that every installed application works under WSL.

| Collection | Required full installation | Acceptance result |
| --- | --- | --- |
| Kali | kali-linux-everything, including recommendations | Full image and managed package audit passed; 4,412 installed packages |
| Parrot | parrot-tools-full, including recommendations | Full image and package-preservation audit passed; 2,076 installed packages after GPU setup |
| REMnux | Upstream full dedicated installer | All 1,091 installer states, full image and managed package audit passed; 2,207 installed packages |
| BackBox | BackBox 9 backbox-tools, including recommendations | Full image, managed runtime/package audit and isolated browser integration passed; 1,234 installed packages |
| SIFT | Pinned upstream Cast release in desktop mode | All 823 installer states, full image and managed package audit passed; 2,253 installed packages |
| CAINE | Complete verified CAINE 14 release filesystem | Managed startup, full package-preservation audit and CUDA memory check passed; 4,475 installed packages |
| Tsurugi | Complete verified LAB 26.03 release filesystem | Managed startup, full package-preservation audit and CUDA memory check passed; 4,156 installed packages |

Shared-shell acceptance ran actual bare commands from all seven providers, verified their private routing shims, preserved literal arguments and nonzero exit codes, and handled relative and absolute shared-workspace paths with spaces. A real CAINE `dc3dd` to Kali `exiftool` pipeline and a shared file consumed by REMnux YARA passed on harmless generated text. Switching the same bare `nmap --version` command between Kali and Parrot passed, and every prior preference was restored. Discovery found 11,307 unique command names. The [transcript](evidence/2026-10-17/seven-provider-transcript.txt) contains actual captured output with labeled generated annotations; it is not a PTY recording.

The [first attempt](evidence/2026-10-17/first-seven-acceptance-attempt.json) passed package and GPU checks but failed the demonstration's assumption that Parrot shipped ExifTool. The [failed demonstration receipt](evidence/2026-10-17/first-seven-provider-demo.json) remains unchanged. The corrected fixture uses Parrot's existing Nmap and Kali's existing ExifTool; no replacement tool was installed for the demonstration. Its dispatcher was the published `e13fbe9` installation, and the corrected test source is published in `9013903`.

The installation audit now distinguishes exact version fidelity from package preservation. Parrot's first Distrobox startup upgraded 30 base packages. The audit retains the original strict version differences and separately requires every originally installed package and architecture to remain installed at the same or a newer version, using Debian's version comparator. Missing packages, changed architectures and downgrades fail. ISO inventories must also match the conversion receipt and package baseline before this comparison is available.

CAINE and Tsurugi's first preservation audits failed because Distrobox replaced their original `mtr-tiny` package with the conflicting `mtr` variant. The private startup adapter now retains `mtr-tiny` when already installed. In the existing environments, a checked two-package transaction restored the original variant and removed only Distrobox's replacement. The [resulting full audits](evidence/2026-10-17/live-release-package-audit.json) pass every package-preservation, dependency, package-database and source-binding check in both releases. The [actual adapter check](evidence/2026-10-17/mtr-adapter-check.json) selects the original variant and produces an empty APT installation plan in both real environments.

The [intermediate audit receipts](evidence/2026-10-17/README.md) retain both successful profile results and the original failed or unavailable profiles. Their overall `passed` fields have not been rewritten. The final combined audit supersedes those intermediate installation snapshots and includes GPU runtime additions.

### BackBox build corrections

The actual build exposed two gaps: BackBox's archive did not supply its required `metasploit-framework` package, and Ubuntu's Chromium transitional package returned success after skipping the browser's Snap payload. The recipe now uses Rapid7's authenticated vendor repository and Canonical's checksum-pinned Chromium/ChromeDriver payload with the existing Ubuntu libraries. It retains the full metapackage and recommendations. The resulting image passed a real local Selenium interaction through the ordinary command names and default browser discovery as UID 1000, without sandbox-disabling flags. [Receipts and scope](evidence/2026-10-17/README.md) distinguish that browser check from the subsequent seven-provider demonstration.

### CAINE archive fidelity

The verified CAINE 14 ISO produced a 13,383,929,856-byte tar with 481,144 entries, SHA-256 `902ce5f4f509a09d2839f0f600dd8fbc9a9e2193949c4b9653fcc9730219de8e`. An independent read of the archive matched all 4,561 package/version records in the ISO's manifest: 4,468 installed and 93 configuration-only records. The latter are part of the upstream release metadata, not packages lost during conversion.

The explicit omission receipt lists exactly 31 Unix sockets from heartbeat and postfix runtime directories. No other omissions were accepted. Custom CAINE directories were retained and inventoried, including `/usr/share/caine`, `/usr/local/bin` and `/opt`; this observation is not an exhaustive upstream custom-tool manifest or a runtime test. The [archive receipts and full package inventory](evidence/2026-10-17/README.md) are retained for review.

### Tsurugi package baseline

The verified LAB 26.03 ISO contains an empty `filesystem.manifest`. The acceptance pipeline therefore reads `/var/lib/dpkg/status` directly from an independently extracted source SquashFS and records 4,147 package/version entries as a derived baseline. This is not a publisher manifest. The converted archive passed comparison against that baseline, with 4,129 installed records and 18 configuration-only records. Its package-database hash matches the source database exactly.

The 34,581,695,488-byte archive contains 1,006,847 entries, with exactly 26 verified Unix sockets omitted. Its SHA-256 is `25a641c3dd132e5276392c07331f060e02e8ce4cdec6f51ce448130321e2ab38`. [Source verification, package inventories and conversion receipts](evidence/2026-10-17/README.md) retain the evidence. Subsequent managed startup, package audit, representative command and CUDA checks passed.

Rootless import found 22 files whose numeric owner IDs exceed the available user namespace. Explicit, collision-checked one-to-one mappings produced a second archive, SHA-256 `88c88766bc71e0594f9c4da584dfc2c9f6bd22550fcbe0c1e50cc3b001490ad2`. The converter verified all file bytes and metadata other than the requested owner/name changes, including binary extended attributes. Independent verification retained the same package database and 1,006,847 entries. The mapped archive imported successfully as image `sha256:b1e49931c17fa2b8c124f4027afaa37ebe3ae64c1792dd9ff01656ec1db7c3fd`; subsequent managed startup passed.

### Full-filesystem startup corrections

CAINE's first startup failed because its APT configuration still referred to installation media. Its logs also showed Distrobox choosing APT-RPM because the complete toolkit includes `rpm`, despite using a Debian package database. The startup adapter now prefers `dpkg-query` in the two affected Distrobox 1.8.2.5 branches. It preserves the installed host scripts and writes a verified private copy for container mounts, retaining upstream license notices. The live-release pre-init hook disables CD-ROM entries with exact original-file backups; network repositories remain configured.

Tests execute the corrected detection in a real POSIX shell with both package commands present, check the private runtime's integrity, and exercise source-file changes and Distrobox's additional shell parsing. Subsequent real startup attempts exposed the additional problems below.

The next CAINE attempt exposed a missing `/var/cache/cracklib` dictionary required by the release's existing PAM password-quality checks. A real networkless run rebuilt the dictionary from installed word lists and verified lookup. The live-release startup hook now rebuilds a missing cache with `update-cracklib`; it retains the password-quality checks.

That attempt then exposed an absent `/etc/shadow`, normally constructed when the live system boots. A real networkless test reproduced `passwd` failure before conversion and successful password update after the standard `pwconv`/`grpconv` tools created missing databases. Account identity fields were unchanged. The hook performs conversion only when the corresponding database is absent; existing databases are preserved. The [diagnostic receipt](evidence/2026-10-17/caine-password-database-check.json) contains no test password.

The subsequent startup passed password initialization but failed when Distrobox split a desktop shortcut's filename at a space. The private adapter now passes each skeleton filename as one argument and preserves existing user files. It verifies the exact upstream block's SHA-256 before applying this correction. A regression test exercises spaces, newlines, shell metacharacters and existing files and links. A [real CAINE check](evidence/2026-10-17/caine-skeleton-check.json) reproduced the original failure and then preserved all 7,554 regular skeleton files, including names with spaces, through a successful repeated copy. The corrected managed container subsequently started and passed its tool check.

Its privileged package audit then found missing control metadata for `wasta-remastersys`; the same metadata was absent from the original archive. The managed container also lacked all 598 regular files in the maintainer's native Ubuntu 24.04 package. The [actual repair receipt](evidence/2026-10-17/caine-package-repair.json) binds the replacement package to verified signed repository metadata and records a single-package upgrade, no removals, a clean subsequent package audit and dependency check, and an unchanged repeat run. The startup hook now applies this checksum-pinned repair only to the known missing-metadata case. It checks the package plan before installation and retains the original package status. Existing configuration files are preserved and compared when present; this run had none.

Tsurugi's first managed startup reached an expired signing subkey in its existing Tor keyring. The repair fetches the publisher's renewed key, requires exactly primary fingerprint `A3C4F0F979CAA22CDBA8F512EE8CBC9E886DDD89`, authenticates the configured suite's signed metadata, and retains the original keyring. A [disposable-image check](evidence/2026-10-17/tsurugi-repository-check.json) then passed APT update across the configured repositories. It did not disable signature verification or change repository source lines. The upstream key location is documented in [Tor's installation guide](https://support.torproject.org/little-t-tor/getting-started/installing/).

Tsurugi's next attempt spent substantial time regenerating hundreds of locales and then encountered the same skeleton filename bug. Its pre-init hook now adds the signed distribution `locales-all` package, with package removal disabled, before Distrobox installs its base dependencies. The distribution's own post-install script accepts that package and skips recompilation. A [real check](evidence/2026-10-17/tsurugi-locales-check.json) installed it in 137 seconds, found 511 available locales and successfully activated all 326 originally requested variants. Package-managed configuration changes are reported separately: `ks_IN@devanagari` leaves the generation selection but remains available and activatable. This is functional language preservation, not byte-identical configuration. The corrected managed startup, tool check, package audit and dependency check subsequently passed.

### REMnux installer failure

The first full dedicated installation reported 1,079 successful and 12 failed Salt states. Its first reported failure depended on the Thug package state. The failed image was not registered as prepared. A second complete installation with the same recipe passed all 1,091 states with zero failures. The [parsed result receipt](evidence/2026-10-17/remnux-installer-results.json) records every state result and the original YAML hash. The first failure's cause was not conclusively reproduced; this success does not establish an identified repair for it. The resulting full image and managed package audit also passed; the shared-shell demonstration subsequently passed.

### SIFT full desktop retry

The first desktop installation reported 810 successful and 13 failed states. Its log contained an ExifTool archive download returning HTTP 404. The recipe now seeds the exact author-checksummed archive from the author's SourceForge distribution; Salt still performs its own verification and full installation. The upstream desktop states also require a real UID 1000 D-Bus session and Ubuntu Dock's schema. A disposable Ubuntu check reproduced the missing-session error and verified persistent settings with a real session. The corrected recipe supplies that session and the Dock package. Its complete retry passed 821 states and failed two: a timezone query attempted to use `timedatectl` without systemd as PID 1, and the aggregate configuration state depended on it. The failed attempts were retained as failures; neither was registered as prepared.

The [isolated timezone check](evidence/2026-10-17/sift-timezone-check.json) reproduced that exact Salt failure and then passed using the actual UTC configuration files. The recipe temporarily diverts `timedatectl` during image construction so Salt uses its existing file-based implementation, then restores the packaged executable and verifies its checksum. The third complete build passed all 823 states with zero failures. The [full installer receipt](evidence/2026-10-17/sift-installer-results.json) records every parsed state and the original YAML hash. The resulting managed environment passed startup, package audit, CUDA memory checks and the shared-shell demonstration.

Full installation is distinct from every tool working under WSL. Kernel modules, device access, live-system write blocking, desktop integration and long-running services require their own validation. SIFT's default UID 1000 path has specific integration support; arbitrary host UIDs and migration of original distro home configuration remain unverified.

## NVIDIA GPU verification

Windows and the fresh Ubuntu host identify an NVIDIA RTX A5000 Laptop GPU with 16 GiB of memory and Windows driver 616.92. Initial Parrot and BackBox checks exposed `/dev/dxg` but could not load `libcuda.so.1`. Connecting the existing Windows-provided WSL libraries made CUDA device discovery succeed in both.

BackBox's Hashcat 6.2.6 required its distribution NVRTC runtime and the unversioned library name used by that build. Parrot additionally needed writable application directories in its managed home. Kali's current repositories supplied no NVRTC package, so its setup used NVIDIA's checksum-pinned compiler redistributable without adding another distribution's repository. The [seven-environment report](evidence/2026-10-17/gpu-seven-collections.json) retains passing 4 KiB CUDA device-memory round trips in all seven providers, including SIFT. Hashcat identifies the RTX A5000 through CUDA in Kali, Parrot, BackBox and Tsurugi; REMnux and SIFT have no Hashcat executable. CAINE's bundled Hashcat 5.1.0 fails because it finds no OpenCL platform. All seven OpenCL probes returned no GPU, and the installed John commands did not provide a successful OpenCL-device listing. Complete application workloads remain unverified. See [GPU setup and diagnosis](gpu.md).

## Earlier bounded checks

An earlier disposable Ubuntu 26.10 environment passed Kali and Parrot base lifecycle checks. A harmless synthetic ISO conversion preserved file contents, numeric ownership and a symbolic link, and a toy rootfs import recorded matching archive and image checksums. These were plumbing checks, not full CAINE or Tsurugi installations. They do not substitute for the fresh acceptance environment above.

Some preliminary unit tests ran on an existing Ubuntu 26.04 distribution. All acceptance work after the clean-install correction uses the new Ubuntu 26.10 distribution on D:.

## Continuous integration

[Package CI](https://github.com/mingusb/FlagshipOS/actions/runs/39075632025) passed the MCP implementation and assistant guide at `9013903`. The [real Kali base-container smoke test](https://github.com/mingusb/FlagshipOS/actions/runs/39073537973) passed the preceding container implementation at `e13fbe9`. See [GitHub Actions](https://github.com/mingusb/FlagshipOS/actions) for later exact-commit results.

The hosted container job uses Ubuntu 24.04 and a pinned Distrobox version. It validates a base container with harmless local commands; it does not prove seven full collections work on WSL.

## MCP and Windows entry points

The [live MCP receipt](evidence/2026-10-17/mcp-seven-providers.json) records a real stdio connection to the installed `9013903` package and 27 successful protocol calls. It discovers all eight MCP operations, resolves and obtains fixed version information from all seven providers, repeats their bounded CUDA probes, reads and hashes a generated workspace fixture, and rejects traversal. CAINE Hashcat's device query is transported successfully but retains its actual application failure, exit 255. A successful MCP call does not make that application test pass.

The [Windows connection receipt](evidence/2026-10-17/windows-mcp.json) verifies the actual `wsl.exe` stdio launch, protocol initialization, operation discovery, capabilities resource and all seven running providers. The [launcher receipt](evidence/2026-10-17/windows-launcher.json) records a real interactive Windows launch into the shared shell; bare Hashcat routed to Kali and identified the RTX A5000. The user-specific configuration and launcher are local deliverables; the portable MCP configuration example is in [the MCP guide](mcp.md).

The [acceptance summary](evidence/2026-10-17/acceptance-summary.json) binds the installation, code, shell, GPU and MCP receipts with hashes and states the limits of the completed checks. The [installed-package receipt](evidence/2026-10-17/published-install-mcp.json) verifies every installed Flagship package file against the public source commit.
