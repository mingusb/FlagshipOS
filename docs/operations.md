# Operations and recovery

## Start with a healthy host

Run `flagship doctor` as your normal Linux user. Rootful Podman and running FlagshipOS under sudo are unsupported. In a fresh WSL session, confirm systemd is enabled and that rootless Podman can run `podman info`. If WSL was imported as root, create a normal user before bootstrapping.

Bootstrap dependencies come from your current Ubuntu repositories. FlagshipOS does not add Kali, Parrot or another distribution's repositories to the Ubuntu host. Ubuntu interim releases have a short support lifecycle; plan normal host upgrades separately from toolkit updates.

## Understand persistence

The container's writable layer contains packages installed after creation. The profile home and shared workspace are separate host directories. Removing a container discards its writable layer but preserves those directories and the source image identity recorded by FlagshipOS. Back up important work independently.

Use one runtime state directory consistently. `--state-dir` is for a separate installation identity; it is not a way to adopt containers created by another state directory. A same-name container with a different installation identity is deliberately rejected.

If state is lost, do not forge labels or state to force adoption. Inspect the container with Podman's read-only commands, preserve needed files, and use a different profile/container setup only after resolving the collision. FlagshipOS never deletes unrelated containers, entire Podman storage, or your work directory automatically.

## Updates

The bundled registry profile references include immutable content digests. A catalog update should record the upstream tag, retrieval date and new digest, then pass tests and a real container smoke check. Tags alone do not prove publisher identity; use official project documentation to verify image ownership.

Existing profile manifests preserve the image chosen at first creation. Package provisioning runs against that environment's live APT repositories and may change its writable layer. Preserve a rootfs export or container snapshot if you need a specific installed toolset later.

Version 0.1 intentionally has no automatic image-refresh, mass-upgrade or prune command. Review Podman inventories before any manual image cleanup. Resetting the source lock requires a deliberate backup and removal of that profile's state after its container is removed; this is an advanced maintenance operation and is not needed for normal use.

## Failure and interruption

Mutating operations hold a file lock. State files are replaced atomically. Container creation records its intended identity before Distrobox runs, so retrying can recognize a container produced by an interrupted attempt. A failed download or checksum stops the operation. A failed provision is reported through its real exit status; it is not marked as completed.

If initialization is interrupted, retry the same command and inspect Distrobox's error. Do not run APT simultaneously in the same environment. Use `flagship status --json` and `podman logs flagship-PROFILE` as diagnostic starting points.

## What isolation means

Every environment has separate distro packages and libraries. Distrobox also intentionally exposes host integration. Rootless Podman limits the container to your user privileges, but that still includes your files. Distrobox may request privileged behavior inside the rootless user namespace. A separate profile home is an organization feature, not a confidentiality boundary.

No profile gives CAINE or Tsurugi's live-boot forensic guarantees under WSL. No smoke test establishes evidentiary soundness or the safety of an arbitrary sample. These boundaries are part of the supported operating model.
