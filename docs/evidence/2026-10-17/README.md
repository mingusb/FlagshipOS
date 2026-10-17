# Verification artifacts

These are observations from the fresh Ubuntu 26.10 `FlagshipOS-Full` WSL2 environment. Paths in receipts identify the disposable verification account. They are not installation instructions.

The [code verification receipt](code-verification.json) records 121 passing tests, wheel installation, the seven-profile catalog and all five bundled recipe hashes. It explicitly records that the live seven-environment acceptance test was not run.

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

The archive contains 1,006,847 entries and matches all 4,147 records from an independent direct read of the verified source SquashFS package database: 4,129 installed and 18 configuration-only records. The ISO's publisher manifest is empty, so the derived baseline is explicitly identified as such. Source and archive package-database hashes match. Exactly 26 verified Unix sockets were omitted. These are archive-fidelity results; runtime acceptance remains pending.
