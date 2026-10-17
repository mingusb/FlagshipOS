# Verification artifacts

These are observations from the fresh Ubuntu 26.10 `FlagshipOS-Full` WSL2 environment. Paths in receipts identify the disposable verification account. They are not installation instructions.

The [code verification receipt](code-verification.json) records 107 passing tests, wheel installation, the seven-profile catalog and all five bundled recipe hashes. It explicitly records that the live seven-environment acceptance test was not run.

## CAINE 14 archive

- [Rootfs checksum, release and ownership metadata](caine-rootfs.json)
- [Comparison with the publisher's ISO package manifest](caine-manifest-audit.json)
- [All package records read from the converted filesystem](caine-package-inventory.json)
- [Exact runtime sockets omitted by explicit request](caine-socket-omissions.json)

The package/version multiset matches all 4,561 publisher manifest records. Of these, 4,468 are installed and 93 retain configuration metadata only. The archive contains 481,144 entries; 31 verified Unix sockets were omitted because tar cannot represent them. The receipt hashes bind these observations to the verified release ISO and converted archive.

These files establish archive fidelity. They do not establish a successful container start, complete tool functionality, or the seven-provider shared-shell demonstration. Consult [the validation record](../../validation.md) for current runtime results.
