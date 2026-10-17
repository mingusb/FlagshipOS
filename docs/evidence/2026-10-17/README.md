# Verification artifacts

These are observations from the fresh Ubuntu 26.10 `FlagshipOS-Full` WSL2 environment. Paths in receipts identify the disposable verification account. They are not installation instructions.

The [MCP-enabled code verification receipt](code-verification-mcp.json) records 159 passing tests with no skips, wheel installation, a real MCP connection against the installed wheel, the seven-profile catalog and all five bundled recipe hashes. Its code/configuration/test fingerprint matches published commit `9013903`. The [earlier code receipt](code-verification.json) retains the prior 143-test result. These source/package checks are separate from live acceptance.

## Completed seven-provider acceptance

- [Acceptance summary with source revisions, scope, limitations and receipt hashes](acceptance-summary.json)
- [Combined full package audit: all seven providers passed after GPU setup and startup repairs](seven-collection-package-audit.json)
- [All seven CUDA memory checks and installed application device queries](gpu-seven-collections.json)
- [SIFT: all 823 full desktop installer states succeeded](sift-installer-results.json)
- [Actual seven-provider shell demonstration, shared files, pipeline, provider switching and failure status](seven-provider-demo.json)
- [Captured shell demonstration output with labeled generated annotations](seven-provider-transcript.txt)
- [First combined attempt: package/GPU checks passed; the initial demonstration assumption failed](first-seven-acceptance-attempt.json)
- [Original demonstration failure: ExifTool was absent from Parrot's full collection](first-seven-provider-demo.json)
- [Live MCP: eight operations and 27 successful protocol calls across seven providers](mcp-seven-providers.json)
- [Actual Windows-to-WSL MCP connection](windows-mcp.json)
- [Actual interactive Windows launcher and bare Hashcat GPU discovery](windows-launcher.json)
- [Installed MCP-enabled package bytes match the public source](published-install-mcp.json)

The corrected demonstration uses tools already present: Kali ExifTool and Parrot Nmap. It installed no substitute tools. It ran the published `e13fbe9` dispatcher with the corrected test fixture subsequently published in `9013903`; the CLI routing implementation is unchanged between those commits. Discovery found 11,307 unique command names across the seven providers. These are installation and bounded interoperability results, not every-tool certification.

## GPU and startup diagnostics

- [Four real environments: CUDA memory round trips and application device listings](gpu-four-collections.json)
- [Six real environments: original observations combined with timestamps and source hashes](gpu-six-collections.json)
- [SIFT timezone: reproduced failure and actual Salt-state success after correction](sift-timezone-check.json)
- [CAINE password database: reproduced failure and successful standard conversion](caine-password-database-check.json)
- [CAINE default home: reproduced filename failure and preserved all 7,554 files](caine-skeleton-check.json)
- [CAINE package repair: authenticated native package, original defect, actual repair and clean audits](caine-package-repair.json)
- [Tsurugi repository key: exact pre-init repair and authenticated APT update](tsurugi-repository-check.json)
- [Tsurugi precompiled locales: all 326 original variants actually activate](tsurugi-locales-check.json)
- [Original mtr-tiny restored in both releases, with exact package plans and clean audits](original-mtr-restoration.json)
- [Patched upstream initialization: syntax and actual mtr-tiny selection in both releases](mtr-adapter-check.json)

The GPU report retains absent tools and failed OpenCL-device commands. It establishes neither universal GPU-tool compatibility nor performance. The startup diagnostics are bounded tests; full managed-container acceptance is recorded separately.

CAINE's Hashcat 5.1.0 fails to discover an OpenCL platform. Tsurugi's Hashcat 7.0.0 identifies the RTX A5000 through CUDA. The six-environment report retains both results.

CAINE's original image omitted the remastering package's control metadata. The actual managed container also lacked all 598 regular payload files in the maintainer's native Ubuntu 24.04 package. The repair upgraded only `wasta-remastersys`, from `4.7.2~ubuntu22.04.1` to `4.7.2~ubuntu24.04.1`, using a package bound to successfully verified signed repository metadata. No packages were removed. The subsequent package audit and dependency check passed; repeated repair performed no installation. The receipt's empty prior-configuration map means there were no existing regular configuration files to compare in this run.

The locale report records package-managed configuration drift separately: the package update removes `ks_IN@devanagari` from the generation selection, but the precompiled package still provides it and the actual activation check passes. The original and updated configuration hashes and complete selection difference are retained.

## Intermediate full-collection package audits

- [CAINE and Tsurugi: complete package-preservation, dependency and source-binding audits passed](live-release-package-audit.json)
- [Kali and REMnux passing profile results](four-collection-audit-kali-remnux.json); the same snapshot records unavailable CAINE, so its overall `passed` remains false.
- [Parrot passing package-preservation audit](four-collection-audit-parrot.json), retaining the separate exact-version differences from Distrobox's upgrades.
- [BackBox passing profile result](four-collection-audit-backbox.json); this earlier snapshot also retains Parrot's original strict-version failure, so its overall `passed` remains false.

The original bytes and observations are retained. The older four-collection audits precede GPU runtime additions; CAINE and Tsurugi's later audit includes their GPU setup and startup repairs. The completed seven-provider audit above covers all environments together. These intermediate reports are separate from the seven-provider demonstration.

## REMnux full installer

The [installer result receipt](remnux-installer-results.json) contains all 1,091 parsed upstream state results, all successful, with the original YAML and log hashes. This was the second complete attempt with the same recipe; the first attempt had 12 failed states whose original cause was not conclusively reproduced. Saving the image, creating the managed environment and demonstrating shared-shell behavior remain separate checks.

## BackBox dependency and browser checks

The [dependency resolution receipt](backbox-dependency-resolution.json) records successful authenticated APT resolution after adding Rapid7's repository for the metapackage's required dependency. The subsequent full image build completed.

The [browser acceptance receipt](backbox-browser-acceptance.json) records an actual rootless, networkless run of that image with Canonical's verified Chromium payload. UID 1000 ran the ordinary `chromium`, `chromium-browser` and `chromedriver` commands, then Selenium discovered the browser and clicked a generated local page. No sandbox-disabling flags were supplied. The receipt binds the image ID, build recipe and test script hashes. This is a browser integration check, not the complete seven-provider demonstration.

## CAINE 14 archive

- [Rootfs checksum, release and ownership metadata](caine-rootfs.json)
- [Comparison with the publisher's ISO package manifest](caine-manifest-audit.json)
- [All package records read from the converted filesystem](caine-package-inventory.json)
- [Exact runtime sockets omitted by explicit request](caine-socket-omissions.json)

The package/version multiset matches all 4,561 publisher manifest records. Of these, 4,468 are installed and 93 retain configuration metadata only. The archive contains 481,144 entries; 31 verified Unix sockets were omitted because tar cannot represent them. The receipt hashes bind these observations to the verified release ISO and converted archive.

These files establish archive fidelity. They do not establish a successful container start, complete tool functionality, or the seven-provider shared-shell demonstration. Consult [the validation record](../../validation.md) for current runtime results.

## Tsurugi LAB 26.03 archive

- [Publisher checksum/signature verification receipt](tsurugi-source-verification.txt)
- [Independent source-to-archive package comparison](tsurugi-manifest-audit.json)
- [Derived source package baseline](tsurugi-package-baseline.manifest)
- [All package records from the converted filesystem](tsurugi-package-inventory.json)
- [Exact omitted runtime sockets](tsurugi-socket-omissions.json)
- [Verified explicit owner conversion](tsurugi-owner-conversion.json)
- [Independent comparison of the owner-adjusted archive](tsurugi-mapped-manifest-audit.json)

The archive contains 1,006,847 entries and matches all 4,147 records from an independent direct read of the verified source SquashFS package database: 4,129 installed and 18 configuration-only records. The ISO's publisher manifest is empty, so the derived baseline is explicitly identified as such. Source and archive package-database hashes match. Exactly 26 verified Unix sockets were omitted. These archive-fidelity results are supplemented by the successful managed runtime checks above.
