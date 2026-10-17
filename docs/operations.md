# Operations and recovery

Full builds and the live seven-environment demonstration remain pending. Read the [validation record](validation.md) and exact CI commit when assessing support. A passing base-container check does not establish full installation.

## Host and persistence

Run as a normal Linux user. Rootful Podman, sudo execution of FlagshipOS, remote connections and custom Distrobox configuration are unsupported. `flagship doctor` checks prerequisites and rootless-engine readiness. Host packages come from Ubuntu; other repositories stay inside their respective images.

Keep storage and working files in the Linux filesystem. A WSL virtual disk may reside on another Windows drive while preserving native Linux paths. Budget for source layers, full images, rootless ownership conversion and writable layers. ISO conversion/import additionally makes verification copies. There is no verified fixed disk requirement for all seven complete collections yet.

State defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/flagship`, workspace to `~/flagship`. Home, state and workspace paths allow letters, digits, `/`, `_`, `.` and `-`. Keep `--state-dir` and `--workspace` consistent. Another state directory has a different installation identity and cannot adopt same-name containers.

## Prepare and replace

Use `prepare PROFILE`, `create PROFILE`, `check PROFILE`, then `tools --refresh`. For CAINE/Tsurugi, verified `import-rootfs` replaces `prepare`. A successful build records its recipe hash and immutable image ID. Creation verifies ownership, image and workspace/home mounts.

Preparation refuses an existing `flagship-PROFILE`. Preserve anything needed from its writable layer before replacement:

```bash
flagship remove parrot --yes
flagship prepare parrot
flagship create parrot
flagship check parrot
flagship tools --refresh
```

Removal preserves home/workspace directories and the source record, but discards files and package changes held only in the container's writable layer. Preparation replaces its source record with the new image. Old Podman images are not automatically pruned. Back up valuable files and images independently.

`provision` installs only the catalog's explicit package list in an existing container. It uses live repositories and changes the writable layer. It does not run REMnux/SIFT full installers or replace the BackBox recipe. Use preparation for the documented full collection workflow.

## Discovery and routing

```bash
flagship tools --refresh
flagship tools --json
flagship which nmap
flagship exec --profile parrot nmap -- --version
flagship prefer nmap parrot
flagship shell
```

Refresh scans executable commands in created environments, including standard tool directories and supported user/`/opt` bin directories. Host-mounted paths are excluded except the verified managed profile home. This is not a recursive index of every file. GUI launchers, non-executable scripts and tools elsewhere may need `flagship run PROFILE -- COMMAND ...`.

Selection follows explicit provider, saved preference, then catalog order: Kali, Parrot, REMnux, SIFT, BackBox, CAINE, Tsurugi. `which` explains the choice. `prefer TOOL --clear` removes it. An unavailable preferred provider fails instead of silently choosing another version.

The unified shell retains host commands and builtins first. Temporary routing shims cover indexed commands absent from the host PATH; `flagship exec` forces container selection when names overlap. `shell -- COMMAND ...` supplies routing to a one-shot command. Shims are removed when that session exits.

Routed commands preserve a current directory inside the shared workspace as `/workspace/...`; elsewhere they start at `/workspace`. Arguments remain literal: arbitrary host paths are not translated. Use workspace-relative paths or `/workspace/...` as appropriate. Direct `run` starts at `/workspace`.

The inventory is bound to installation, container, image and managed-home identity. Refresh after container replacement or changes to installed executables. Presence is not proof of complete functionality or provenance.

## Failures and updates

Mutating operations hold a state lock and replace state files atomically. Creation records intended identity before Distrobox runs so a retry can recognize a matching container. Failed builds are not registered as prepared; checksum failures stop imports. Review the error and retry the same operation. Podman may reuse completed build layers.

First entry may install Distrobox prerequisites and take time. Avoid concurrent APT operations in one environment. Inspect `flagship status --json` and `podman logs flagship-PROFILE`. Version checks are bounded checks, not exhaustive acceptance tests.

If state is lost or configuration differs, inspect and preserve files before resolving the collision. Do not forge ownership labels or state. FlagshipOS refuses unrelated containers and does not delete Podman storage or work directories automatically.

Source digests and installer checksums are reviewed inputs. APT and some installer resources remain mutable; recipe hashes do not make builds reproducible. Retain image IDs, build logs, package inventories, custom-tool inventories and original import artifacts. Distrobox initialization can subsequently change packages.

There is no automatic image-refresh, mass-upgrade or prune command. Review recipe/source changes, preserve required images, rebuild deliberately, then refresh discovery. Upgrade the interim Ubuntu host separately as needed.

## Isolation and kernel behavior

Distrobox intentionally exposes host integration. Rootless containers still have access associated with your Linux user; separate homes organize configuration and do not conceal the host home. WSL does not reproduce upstream custom kernels, live write blocking or all device/service behavior. Use a separately isolated VM for untrusted samples and the original booted distribution when its forensic guarantees are required.
