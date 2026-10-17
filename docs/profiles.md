# Collection sources and preparation

The Ubuntu WSL host keeps its Ubuntu repositories. Each environment has its own libraries, package database and repositories. Recipes build images before Distrobox connects them to your workspace.

**Full builds and a live unified seven-profile demonstration are pending.** The methods below describe implemented recipes and verified upstream sources, not completed installation results.

## Five build recipes

Use `flagship prepare PROFILE`, then `flagship create PROFILE` and `flagship check PROFILE` for Kali, Parrot, REMnux, SIFT and BackBox. Preview with `flagship --dry-run prepare PROFILE`. Preparation refuses an existing same-name container and records a successful build's recipe SHA-256 and immutable image ID.

| Profile | Recipe and upstream evidence | Scope |
| --- | --- | --- |
| Kali | Official image plus [`kali-linux-everything`](https://www.kali.org/docs/general-use/metapackages/), with recommends | Full selected metapackage; the upstream image alone is minimal |
| Parrot | Official Security image plus [`parrot-tools-full`](https://github.com/ParrotSec/parrot-tools/blob/master/debian/control), with recommends | Adds tools omitted from the command-line image; recommends are essential |
| REMnux | Official Ubuntu 24.04 container plus its [documented full installer expansion](https://docs.remnux.org/install-distro/remnux-as-a-container) | Dedicated mode, release `v2026.42.3`; intended to add VS Code and Wine-dependent tools omitted from the base |
| SIFT | Ubuntu 24.04, Cast `v1.0.42`, SIFT [`v2026.04.21` desktop mode](https://github.com/teamdfir/sift-saltstack/releases/download/v2026.04.21/manifest.yml) | Release manifest supports Ubuntu 22.04 and 24.04; current recipe requires amd64. Some introductory SANS instructions still name 22.04 |
| BackBox | Ubuntu 24.04 plus the official [BackBox nine/noble archive](https://api.launchpad.net/1.0/~backbox/+archive/ubuntu/nine), `backbox-tools` with recommends | Full tool metapackage, observed version 9.0.1 on 2026-10-17; desktop appearance/settings are separate |

Inspect the bundled [Containerfiles](../src/flagship/recipes). Recipes check APT dependencies and pending dpkg problems and save `/usr/local/share/flagship/package-inventory.tsv`. This does not enumerate every custom `/opt` or user-installed tool. REMnux/SIFT installer service and home assumptions still need live verification.

BackBox's repository key fingerprint is `F10FF8AFAF205A39312C0A20F2B4C9A44882013D`, checked against official Launchpad metadata. The repository is configured inside that image only. Never add these sources to the Ubuntu host or another collection.

## Registry provenance

These mappings were verified on **2026-10-17** against official image references, public tag metadata and Docker Registry digest headers. They are multi-platform index digests; architecture presence does not certify every tool.

| Upstream reference | Digest |
| --- | --- |
| `docker.io/kalilinux/kali-rolling:latest` | `sha256:02f5d6c019e549b0f55da58e835cad5355ef1030c6b2645265a324e37dfc4acc` |
| `docker.io/parrotsec/security:latest` | `sha256:2fe6606fed814618a6bc91a07f193a5b6aa9660b774fc319e6c8fd4b569e2f06` |
| `docker.io/remnux/remnux-distro:noble` | `sha256:880089abf02feb5240607545ab601e2d97d7b1c213d6341aa2e7ce356f65c8c2` |

Publisher references: [Kali](https://www.kali.org/docs/containers/official-kalilinux-docker-images/), [Parrot](https://www.parrotsec.org/docs/containers/parrot-on-docker/), [REMnux](https://docs.remnux.org/install-distro/remnux-as-a-container). Ubuntu base digests and installer checksums are recorded in the recipes. Digest identity is not publisher-signature verification or a runtime test.

Creating these registry profiles without preparation uses the original upstream image and its omissions. SIFT and BackBox can use recipes even where catalog source kind is `import`: preparation registers a local image for creation. Genuine preinstalled rootfs imports remain possible.

## Import profiles: CAINE and Tsurugi

Only these two collections require official ISO extraction in the documented workflow. No current complete public package installer was verified. Preserve the release filesystem, including custom files outside dpkg.

| Profile | Verified artifact | Coverage boundary |
| --- | --- | --- |
| CAINE | [CAINE 14 Lightstream](https://www.caine-live.net/page5/page5.html), Ubuntu 24.04, released 2025-03-24 | Current release intentionally omits Autopsy and Gimp. Its public tools page describes CAINE 11, not an exhaustive CAINE 14 manifest |
| Tsurugi | [LAB 26.03](https://tsurugi-linux.org/downloads.php), Ubuntu 24.04 lineage, released 2026-04-04 | [Current FAQ](https://tsurugi-linux.org/documentation_faq1.php) still places a public custom repository on the roadmap; custom files also live in `/usr/bin` and `/opt` |

CAINE-FROM-DEB targets Ubuntu 10.04 and is unsuitable here. Tsurugi's newest published tool list is 25.11, preceding its current release. Complete release userspace is the baseline; additional desired tools are a separate supplement.

Verify the ISO against its publisher's checksum. CAINE 14's [published SHA-256](https://www.caine-live.net/page5/caine14.0.iso.sha256.txt) is:

```text
2702226cf9ee131ee54e9649d6d90008f3fe851ba35939f43ae8cb614a00d564
```

Tsurugi publishes [signed SHA-512 hashes](https://tsurugi-linux.org/signed_hashes.sha512) and a [public key](https://tsurugi-linux.org/tsurugi_linux_pub_key.asc). Verify the signature and ISO hash first. The key retrieved on 2026-10-17 had fingerprint `68A60308FCD7BCA0F81E75016DF20CE124289711`, anchored to the official HTTPS site. Pass the verified publisher hash with the helper's `--sha512` option.

Install the Ubuntu conversion packages and inspect the actual layout:

```bash
sudo apt-get install xorriso squashfs-tools-ng
xorriso -indev /path/to/verified.iso -find / -name '*.squashfs'
```

The helper defaults to `casper/filesystem.squashfs`; use `--squashfs-path PATH` if needed. Multiple layered filesystems require additional review: the helper converts one selected SquashFS only.

```bash
python3 scripts/iso-to-rootfs.py \
  --iso /path/to/verified.iso \
  --sha256 VERIFIED_ISO_SHA256 \
  --output /path/to/rootfs.tar

flagship import-rootfs caine /path/to/rootfs.tar --sha256 PRINTED_ROOTFS_SHA256
flagship create caine
flagship check caine
```

For Tsurugi, replace `--sha256 VERIFIED_ISO_SHA256` with `--sha512 VERIFIED_ISO_SHA512` and use profile `tsurugi`. The resulting rootfs receipt and `import-rootfs` still use SHA-256. The helper verifies a private ISO copy, preserves numeric ownership in the tar and refuses existing output. It neither boots the image nor extracts a filesystem tree onto the host. Allow space for the source ISO, private copy, SquashFS, tar, import snapshot and unpacked Podman image. OVA and virtual-disk files are not rootfs tar archives.

The default conversion stops on unsupported filesystem entries. CAINE 14 contains a Unix socket, which tar cannot represent. For that case, explicitly add `--omit-runtime-sockets`: the helper independently verifies every omitted inode is a socket, rejects other omissions or ambiguous metadata, and writes `rootfs.tar.omissions.json` with the exact paths and archive hash. Retain this receipt with the rootfs. This option does not omit packages or regular tool files; it also does not recreate the corresponding running services.

## Verification boundaries

`check` runs representative local version commands. `tools --refresh` inventories discovered executables in created environments. Neither establishes complete application functionality. Live package repositories also mean a source pin does not make the final build reproducible.

Distrobox integrates with host files and is not malware containment. WSL's kernel does not provide CAINE/Tsurugi live write blocking, custom kernels or acquisition guarantees. Desktop, service and hardware behavior needs separate validation. All upstream components retain their own licenses; only FlagshipOS code is MIT-licensed.
