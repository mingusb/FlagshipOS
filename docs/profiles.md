# Distribution profiles

Flagship keeps each distribution's package database and libraries in its own container. The Ubuntu WSL host keeps its Ubuntu repositories. This prevents cross-distribution APT dependency conflicts; it does not guarantee that every upstream application works in a container.

The catalog contains all seven requested Debian-family collections. Three have official registry images; four require an actual distribution artifact. An import profile is not a preinstalled toolkit and is never silently replaced by bare Ubuntu.

| Profile | Source and base | Delivery | Coverage boundary |
| --- | --- | --- | --- |
| `kali` | [Official Kali image](https://www.kali.org/docs/containers/official-kalilinux-docker-images/), Debian | Digest-pinned registry image | Minimal base; explicitly provision `kali-linux-headless` for the headless collection. This is not all Kali packages. |
| `parrot` | [Official Parrot Security image](https://www.parrotsec.org/docs/containers/parrot-on-docker/), Debian | Digest-pinned registry image | Command-line collection; upstream excludes GUI applications. |
| `remnux` | [Official REMnux container](https://docs.remnux.org/install-distro/remnux-as-a-container), Ubuntu 24.04 | Digest-pinned registry image | Upstream omits VS Code and Wine-dependent tools. Some configuration expects the stock `remnux` user. |
| `sift` | [SANS SIFT](https://www.sans.org/tools/sift-workstation), Ubuntu | Import an installed rootfs | Prepare with upstream's supported Ubuntu release and installer. Current instructions specify Ubuntu 22.04, not the 26.10 host. |
| `backbox` | [BackBox Linux](https://linux.backbox.org/), Ubuntu | Import verified ISO or rootfs | Desktop, service and hardware behavior is not guaranteed. |
| `caine` | [CAINE downloads](https://www.caine-live.net/page5/page5.html), Ubuntu | Import verified ISO or rootfs | User-space tools only; live-boot write blocking does not transfer. |
| `tsurugi` | [Tsurugi LAB](https://tsurugi-linux.org/tsurugi_linux.php), Ubuntu | Import verified ISO or rootfs | User-space tools only; its custom kernel and write blocking do not transfer. |

## Registry provenance

The following tag-to-digest mappings were checked on **2026-10-17** using Docker Hub's public tag metadata and then confirmed against the Docker Registry API's `Docker-Content-Digest` response header. These are multi-platform image index digests, not architecture-specific layer hashes. All three indexes include Linux `amd64` and `arm64`; this observation does not certify every tool on both architectures.

| Upstream reference observed | Immutable digest used | Upstream tag last pushed |
| --- | --- | --- |
| `docker.io/kalilinux/kali-rolling:latest` | `sha256:02f5d6c019e549b0f55da58e835cad5355ef1030c6b2645265a324e37dfc4acc` | 2026-10-11 |
| `docker.io/parrotsec/security:latest` | `sha256:2fe6606fed814618a6bc91a07f193a5b6aa9660b774fc319e6c8fd4b569e2f06` | 2026-05-15 |
| `docker.io/remnux/remnux-distro:noble` | `sha256:880089abf02feb5240607545ab601e2d97d7b1c213d6341aa2e7ce356f65c8c2` | 2026-10-15 |

Metadata evidence: [Kali tag](https://hub.docker.com/v2/repositories/kalilinux/kali-rolling/tags/latest), [Parrot tag](https://hub.docker.com/v2/repositories/parrotsec/security/tags/latest), [REMnux tag](https://hub.docker.com/v2/repositories/remnux/remnux-distro/tags/noble). The mappings are recorded above because tags can move after verification. A digest establishes content identity; it is not a publisher-signature verification or a vulnerability assessment.

Registry verification is not an end-to-end runtime test. Consult the project's test documentation and release notes for the environments actually exercised. Smoke commands check Bash, the Debian package-query utility, and representative toolkit commands where an upstream inventory supports them. They do not assert that a distribution's complete tool collection is installed or functional.

| Profile | Additional smoke command | Evidence and interpretation |
| --- | --- | --- |
| `kali` | `nmap --version` | [Headless metapackage inventory](https://www.kali.org/tools/kali-meta/#kali-linux-headless). Requires explicit provisioning; failure on the minimal base is expected. |
| `parrot` | `nmap --version` | [Parrot metapackage inventory](https://github.com/ParrotSec/parrot-tools/blob/master/debian/control) includes Nmap in its information-gathering collection. |
| `remnux` | `yara --version` | [REMnux tool inventory](https://docs.remnux.org/discover-the-tools/gather%2Band%2Banalyze%2Bdata) lists YARA. |
| `sift` | `fls -V` | [SIFT inventory](https://www.sans.org/tools/sift-workstation) includes Sleuth Kit. |
| `caine` | `fls -V` | [CAINE tool inventory](https://www.caine-live.net/page11/page11.html) includes Sleuth Kit. |
| `tsurugi` | `fls -V` | [Tsurugi's changelog](https://tsurugi-linux.org/documentation_tsurugi_linux_changelog.php) records Sleuth Kit. |
| `backbox` | None beyond the base checks | A current version-specific package manifest was not verified; inspect the imported artifact's tool inventory. |

These commands display local versions and perform no network scanning or sample execution. The [Sleuth Kit manual](https://sleuthkit.org/sleuthkit/man/fls.html) documents `-V` as its version flag. Presence of one representative utility does not establish a distribution's identity; use verified upstream artifacts.

Pinning freezes the source filesystem. Distrobox may install integration prerequisites on first entry, and explicit package provisioning uses that distribution's live repositories. The resulting mutable environment is therefore not a bit-for-bit reproducible build. Retain your exact imported artifacts and package inventories when that level of reproducibility matters.

## Import profiles

The absence of a verified image is stated narrowly: no current official, complete OCI workstation image was verified during this review. Community images may exist, but this project does not substitute an unreviewed third party image for an upstream distribution.

For SIFT, the official [Dockerfiles repository](https://github.com/teamdfir/sift-dockerfiles) is archived and its README describes a deprecated Salt test image. That is not a complete SIFT workstation. Follow the current [SANS installation instructions](https://www.sans.org/tools/sift-workstation) in a separate supported installation, then export that installation's root filesystem. SIFT's OVA must first be installed or converted into a root filesystem; it is not directly a rootfs tar.

For BackBox, CAINE and Tsurugi, obtain the ISO from the project's download page. Check its upstream checksum and signature where available before importing. CAINE provides SHA-256 hashes. [Tsurugi publishes signed SHA-512 hashes](https://tsurugi-linux.org/downloads.php); verify those, then calculate SHA-256 for this project's import record. A checksum you calculated yourself records identity but does not establish upstream authenticity.

An ISO import uses the live user-space filesystem and does not boot its installer or kernel. It therefore cannot reproduce the full live distribution. Multi-layer live images or changed layouts can require a prepared rootfs tar. OVA, VMDK and other virtual disks are not accepted as rootfs archives. Use a clean installation without personal files or credentials when producing an archive.

The repository includes an explicit ISO conversion helper. Install its Ubuntu prerequisites, `xorriso` and `squashfs-tools-ng`, then supply the ISO and the checksum obtained from upstream. Run it from the repository checkout, replacing the paths and checksum below:

```bash
python3 scripts/iso-to-rootfs.py \
  --iso "$HOME/Downloads/distribution.iso" \
  --sha256 '<verified-upstream-ISO-SHA256>' \
  --output "$HOME/Downloads/distribution-rootfs.tar"
```

The helper uses `xorriso` and `sqfs2tar`; it does not install the distribution onto the host. Use the resulting rootfs tar, together with its own SHA-256, for the profile import. The ISO checksum and the rootfs checksum identify different artifacts and are not interchangeable. For Tsurugi, first verify the published signed SHA-512 file, then calculate the verified ISO's SHA-256 for the helper input.

For a CAINE artifact, the next steps are:

```bash
flagship import-rootfs caine "$HOME/Downloads/distribution-rootfs.tar" \
  --sha256 '<rootfs-SHA256-reported-by-the-helper>'
flagship create caine
flagship check caine
```

Choose the matching profile ID for the artifact. If the ISO has a single live root filesystem at a different location, provide `--squashfs-path path/inside/image.squashfs` to the helper after inspecting its layout. Do not arbitrarily select one layer from a multi-layer image.

All four import profiles are experimental until the particular artifact is tested on the target host. Tool availability comes from the artifact; this project does not download an unspecified collection after import. Upstream software keeps its own licenses. This repository distributes launcher/configuration code, not repackaged distribution binaries.

## Host integration and limits

The target is a fresh Ubuntu 26.10 WSL2 host. Containers can retain an older supported Debian or Ubuntu user space. They share the WSL kernel, so they do not bring a distribution's custom kernel, kernel modules or boot-time protections with them. Raw devices, USB adapters, packet capture capabilities, GUI sessions and long-running services need separate support and testing.

Separate profile homes avoid accidental dotfile collisions, but they do not make Distrobox a security sandbox. [Distrobox explicitly prioritizes host integration](https://distrobox.it/#security-implications), and its [custom-home option still mounts the host home](https://distrobox.it/usage/distrobox-create/). Use a separately isolated, disposable VM for executing untrusted malware. A forensic tool in these containers must not be assumed to provide the acquisition or write-blocking guarantees of the original live distribution.

## Catalog contract

`src/flagship/profiles.json` has `schema_version: 1` and a `profiles` object keyed by `kali`, `parrot`, `remnux`, `sift`, `backbox`, `caine` and `tsurugi`. Each entry contains:

- `name`, `description`, `source_url` and `notes` for provenance and limitations.
- `kind`: `registry` for a verified upstream OCI image or `import` for a user-supplied distribution filesystem.
- `image`: an immutable, fully qualified OCI reference for registry profiles; `null` for import profiles.
- `smoke_commands`: argument arrays for harmless local environment checks. They are not shell strings.
- `packages`: optional packages installed only by an explicit provisioning action. An empty array means no additional collection package is requested.

Update an image pin only after verifying its upstream source and architecture metadata, exercising the changed image, and recording the new digest and check date here. Do not replace import profiles with guessed image names or add a distribution's repositories to the host.
