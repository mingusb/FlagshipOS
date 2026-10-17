"""Small, dependency-free environment manager. No shell command evaluation."""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from . import __version__

LABEL = "io.github.mingusb.flagship"
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")
HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
PACKAGE_RE = re.compile(r"[a-z0-9][a-z0-9+.:~-]*\Z")
PATH_RE = re.compile(r"/[A-Za-z0-9_./-]+\Z")


class CommandError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Context:
    state_dir: Path
    workspace: Path
    dry_run: bool = False

    def record_path(self, profile):
        return self.state_dir / "profiles" / f"{profile}.json"

    def home(self, profile):
        return self.state_dir / "homes" / profile


def load_catalog():
    catalog = json.loads(files("flagship").joinpath("profiles.json").read_text("utf-8"))
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1 or not isinstance(catalog.get("profiles"), dict):
        raise CommandError("Unsupported or invalid profile catalog")
    for name, profile in catalog["profiles"].items():
        if not NAME_RE.fullmatch(name) or not isinstance(profile, dict) or profile.get("kind") not in ("registry", "import"):
            raise CommandError(f"Invalid profile: {name}")
        packages = profile.get("packages", [])
        if not isinstance(packages, list) or any(not isinstance(p, str) or not PACKAGE_RE.fullmatch(p) for p in packages):
            raise CommandError(f"Invalid package name in profile: {name}")
        if not isinstance(profile.get("name"), str):
            raise CommandError(f"Missing display name: {name}")
        commands = profile.get("smoke_commands", [])
        if not isinstance(commands, list) or any(not isinstance(command, list) or not command or
                any(not isinstance(part, str) or not part or "\x00" in part for part in command)
                for command in commands):
            raise CommandError(f"Invalid smoke command in profile: {name}")
        if profile["kind"] == "registry":
            image = profile.get("image")
            if not isinstance(image, str) or not re.fullmatch(r"[a-z0-9][a-zA-Z0-9_./:@-]+", image):
                raise CommandError(f"Invalid registry image: {name}")
    return catalog["profiles"]


def read_json(path, default=None):
    try:
        value = json.loads(path.read_text("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise CommandError(f"Cannot read state {path}: {exc}") from exc


def atomic_json(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".flagship-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def rootless_network_status(info):
    host = info.get("host", {}) if isinstance(info, dict) else {}
    command = host.get("rootlessNetworkCmd") if isinstance(host, dict) else None
    if command not in ("pasta", "slirp4netns"):
        return False, "Cannot determine Podman's rootless build network helper from podman info."
    helper = host.get(command, {})
    location = helper.get("executable") if isinstance(helper, dict) else None
    available = bool((isinstance(location, str) and os.path.isabs(location) and os.access(location, os.X_OK))
                     or shutil.which(command))
    if not available:
        package = "passt" if command == "pasta" else "slirp4netns"
        return False, f"Podman selected {command} for rootless networking; install Ubuntu's {package} package."
    return True, f"Podman rootless network helper: {command}."


def require_runtime(*, build=False):
    if sys.platform != "linux":
        raise CommandError("Run this command inside Linux (Ubuntu WSL2 is supported).")
    if os.geteuid() == 0:
        raise CommandError("Run Flagship as your normal Linux user, without sudo.")
    missing = [tool for tool in ("podman", "distrobox") if not shutil.which(tool)]
    if missing:
        raise CommandError("Install the required tools first: " + ", ".join(missing))
    result = capture(["podman", "info", "--format", "json"])
    try:
        info = json.loads(result.stdout)
        rootless = info["host"]["security"]["rootless"]
    except (ValueError, KeyError, TypeError) as exc:
        raise CommandError("Cannot determine whether Podman is rootless.") from exc
    if rootless is not True:
        raise CommandError("Flagship requires rootless Podman; rootful or remote rootful engines are unsupported.")
    if build:
        ready, detail = rootless_network_status(info)
        if not ready:
            raise CommandError(detail)


def validate_paths(ctx):
    """Distrobox generates shell commands internally, so its paths need a narrow alphabet."""
    if sys.platform != "linux":
        return  # Other platforms support read-only planning; execution is Linux-only.
    candidates = {"state path": ctx.state_dir, "workspace path": ctx.workspace, "HOME path": Path.home()}
    for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "SHELL"):
        if os.environ.get(key):
            candidates[f"{key} path"] = Path(os.environ[key])
    for label, path in candidates.items():
        if not PATH_RE.fullmatch(str(path)) or not PATH_RE.fullmatch(str(path.resolve(strict=False))):
            raise CommandError(f"Distrobox requires a safe absolute {label}: use only letters, digits, /, _, . and -. "
                               f"Move it to a path without spaces, colons or shell characters: {path}")


def validate_backend_configuration():
    if sys.platform != "linux":
        return
    if any(os.environ.get(key) for key in ("CONTAINER_HOST", "CONTAINER_CONNECTION")):
        raise CommandError("Remote Podman is unsupported; unset CONTAINER_HOST and CONTAINER_CONNECTION to use the local workspace.")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    custom_configs = [Path.home() / ".distroboxrc", config_home / "distrobox" / "distrobox.conf",
                      Path("/etc/distrobox/distrobox.conf"), Path("/usr/etc/distrobox/distrobox.conf"),
                      Path("/usr/local/share/distrobox/distrobox.conf")]
    existing = [str(path) for path in custom_configs if path.exists()]
    if existing:
        raise CommandError("Custom Distrobox configuration can override image and mount settings. "
                           "Temporarily move these configuration files before using Flagship: " + ", ".join(existing))


def backend_env():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("DBX_")}
    environment["DBX_CONTAINER_MANAGER"] = "podman"
    # Distrobox reads user configuration; deny any configured host sudo escalation.
    # This does not affect sudo executed inside a container for package management.
    environment["DBX_SUDO_PROGRAM"] = "/bin/false"
    if sys.platform == "linux":
        import pwd
        account = pwd.getpwuid(os.getuid()).pw_name
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*\$?", account):
            raise CommandError("Distrobox requires a conventional Linux account name.")
        environment["USER"] = environment["LOGNAME"] = account
    return environment


def capture(argv, check=True):
    result = subprocess.run(argv, env=backend_env(), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if check and result.returncode:
        raise CommandError(f"{argv[0]} failed: {result.stderr.strip() or result.stdout.strip()}",
                           exit_code(result.returncode))
    return result


def exit_code(code):
    return code if code >= 0 else 128 - code


def group_alive(group):
    """Ignore zombies: they cannot mutate state and are reaped by their parent."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            if int(fields[2]) == group and fields[0] not in ("Z", "X"):
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def signal_child(child, signum, grouped):
    with contextlib.suppress(ProcessLookupError):
        if grouped:
            os.killpg(child.pid, signum)
        elif child.poll() is None:
            child.send_signal(signum)


def stop_child(child, signum, grouped):
    """Keep the caller's state lock until interrupted descendants have exited."""
    signal_child(child, signum, grouped)
    deadline = time.monotonic() + 3
    def alive():
        child.poll()
        return group_alive(child.pid) if grouped else child.returncode is None
    while alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if alive():
        signal_child(child, signal.SIGKILL, grouped)
    while alive():
        time.sleep(0.05)
    child.wait()


def stream(argv, *, stdin=None, supervise=False, env=None, cwd=None):
    """Supervise noninteractive mutations without changing interactive job control."""
    grouped = supervise and sys.platform == "linux" and (stdin is not None or not (sys.stdin.isatty() and sys.stdout.isatty()))
    options = {"start_new_session": True} if grouped else {}
    if cwd is not None:
        options["cwd"] = str(cwd)
    child = subprocess.Popen(argv, env=backend_env() if env is None else env, stdin=stdin, **options)
    requested_signal = None
    def terminate(signum, _frame):
        nonlocal requested_signal
        requested_signal = signum
        signal_child(child, signum, grouped)
    handled = (signal.SIGTERM, signal.SIGINT) if grouped else (signal.SIGTERM,)
    previous = {signum: signal.getsignal(signum) for signum in handled}
    for signum in handled:
        signal.signal(signum, terminate)
    try:
        try:
            while True:
                if requested_signal is not None:
                    stop_child(child, requested_signal, grouped)
                    return 128 + requested_signal
                try:
                    code = child.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except KeyboardInterrupt:
            stop_child(child, signal.SIGINT, grouped)
            return 130
        if requested_signal is not None:
            stop_child(child, requested_signal, grouped)
            return 128 + requested_signal
        if code < 0 and grouped:
            stop_child(child, -code, grouped)
        return exit_code(code)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def checked_stream(argv, *, stdin=None):
    code = stream(argv, stdin=stdin, supervise=True)
    if code:
        raise CommandError(f"Command failed (exit {code}): {argv[0]}", code)


@contextlib.contextmanager
def state_lock(ctx):
    import fcntl
    if ctx.state_dir.is_symlink():
        raise CommandError("State directory must not be a symbolic link.")
    ctx.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = ctx.state_dir.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise CommandError(f"State directory must belong to you and have mode 0700: {ctx.state_dir}")
    lock_path = ctx.state_dir / ".lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def installation(ctx, create=False):
    path = ctx.state_dir / "install.json"
    info = read_json(path)
    if info is None and create:
        info = {"schema_version": 1, "installation_id": str(uuid.uuid4())}
        atomic_json(path, info)
    if info is not None:
        try:
            if info.get("schema_version") != 1 or str(uuid.UUID(info["installation_id"])) != info["installation_id"]:
                raise ValueError("unsupported installation state")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise CommandError(f"Invalid installation state: {path}") from exc
    return info


def inspect_container(name):
    result = capture(["podman", "container", "inspect", name], check=False)
    if result.returncode:
        exists = capture(["podman", "container", "exists", name], check=False)
        if exists.returncode == 1:
            return None
        raise CommandError(f"Cannot inspect container {name}: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)[0]
        if not isinstance(value, dict) or not isinstance(value.get("Config"), dict):
            raise ValueError("expected container configuration")
        return value
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise CommandError(f"Invalid inspection data for {name}") from exc


def ensure_owned(ctx, profile, container):
    record = read_json(ctx.record_path(profile))
    install = installation(ctx)
    configuration = container.get("Config", {})
    labels = (configuration.get("Labels") or {}) if isinstance(configuration, dict) else {}
    if not isinstance(labels, dict):
        labels = {}
    if not (install and record and record.get("installation_id") == install["installation_id"]
            and record.get("container") == f"flagship-{profile}"
            and labels.get(f"{LABEL}.installation") == install["installation_id"]
            and labels.get(f"{LABEL}.profile") == profile
            and labels.get(f"{LABEL}.managed") == "true"):
        raise CommandError(f"Refusing to use or remove foreign container flagship-{profile}.")
    return record


def ensure_configuration(record, container):
    image_id = record.get("image_id")
    actual_id = container.get("Image", "")
    if (not isinstance(image_id, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
            or not isinstance(actual_id, str) or actual_id.removeprefix("sha256:") != image_id.removeprefix("sha256:")):
        raise CommandError("Managed container image differs from its recorded identity; remove and recreate it.")
    mounts = container.get("Mounts") or []
    mounts = [mount for mount in mounts if isinstance(mount, dict) and mount.get("Destination") == "/workspace"]
    expected = record.get("workspace")
    if (len(mounts) != 1 or not isinstance(expected, str) or mounts[0].get("Type") != "bind"
            or mounts[0].get("RW") is not True or not isinstance(mounts[0].get("Source"), str)
            or Path(mounts[0]["Source"]).resolve() != Path(expected).resolve()):
        raise CommandError("Managed container workspace mount differs from its recorded path; remove and recreate it.")


def managed_container(ctx, profile, verify=True):
    container = inspect_container(f"flagship-{profile}")
    if container is None:
        raise CommandError(f"No container for {profile}; run 'flagship create {profile}' first.")
    record = ensure_owned(ctx, profile, container)
    if verify:
        ensure_configuration(record, container)
    return container, record


def create_argv(ctx, profile, image, instance):
    from . import gpu, integration
    flags = " ".join([f"--label={LABEL}.managed=true",
                      f"--label={LABEL}.installation={instance}",
                      f"--label={LABEL}.profile={profile}"])
    argv = ["distrobox", "create", "--yes", "--no-entry", "--name", f"flagship-{profile}",
            "--hostname", f"flagship-{profile}",
            "--image", image, "--home", str(ctx.home(profile)),
            "--volume", f"{ctx.workspace}:/workspace:rw", "--additional-flags", flags]
    if profile in ("caine", "tsurugi"):
        argv += ["--pre-init-hooks", integration.live_release_hook(profile)]
    hooks = [integration.home_directory_hook(ctx.home(profile), os.getuid(), os.getgid())]
    if gpu.host_available():
        hooks.append(gpu.setup_hook(with_runtime=True))
    argv += ["--init-hooks", " && ".join(hooks)]
    return argv


def enter_argv(profile, command):
    return ["distrobox", "enter", "--name", f"flagship-{profile}",
            "--additional-flags", "--workdir=/workspace", "--", *command]


def provision_argv(profile, definition):
    packages = definition.get("packages", [])
    if not packages:
        return []
    return [enter_argv(profile, ["sudo", "apt-get", "update"]),
            enter_argv(profile, ["sudo", "env", "DEBIAN_FRONTEND=noninteractive",
                                 "apt-get", "install", "--yes", "--install-recommends", "--", *packages])]


def locked_image(record):
    image = record.get("image") or record.get("imported_image")
    if image is not None and (not isinstance(image, str) or not re.fullmatch(
            r"(?:[a-z0-9][a-zA-Z0-9_./:-]+@)?sha256:[a-f0-9]{64}", image)):
        raise CommandError("Invalid immutable image reference in state; refusing to execute it.")
    return image


def print_plan(ctx, args, definition):
    profile = args.profile
    record = read_json(ctx.record_path(profile), {})
    install = installation(ctx) or {"installation_id": "${installation_id}"}
    command = "create" if args.command == "plan" else args.command
    steps, notes = [], ["Planning only: no commands run and no directories or state created."]
    if command == "create":
        image = locked_image(record)
        if not image and definition["kind"] == "registry":
            steps += [["podman", "pull", definition["image"]],
                      ["podman", "image", "inspect", definition["image"]]]
            image = definition["image"] if "@sha256:" in definition["image"] else "${resolved_image_digest}"
            notes.append("Resolve RepoDigests from image inspection and lock the digest before creation.")
        if not image:
            image = "${verified_imported_image_id}"
            notes.append("Import this profile's root filesystem with a verified SHA-256 before creation.")
        steps.append(create_argv(ctx, profile, image, install["installation_id"]))
        notes.append("A matching managed container is reused; a foreign name collision is rejected.")
    elif command == "provision":
        steps = provision_argv(profile, definition)
    elif command == "run":
        steps = [enter_argv(profile, command_arguments(args))]
    elif command == "check":
        steps = [enter_argv(profile, argv) for argv in definition.get("smoke_commands", [])]
    elif command == "remove":
        steps = [["distrobox", "rm", "--force", f"flagship-{profile}"]]
        notes.append("Ownership is checked before removal; home and workspace files are retained.")
    elif command == "import-rootfs":
        validate_import(definition, args)
        tag = import_tag(profile, args.sha256)
        steps = [import_argv(tag), ["podman", "image", "inspect", tag]]
        notes.append(f"Copy {args.path} to a private snapshot while computing SHA-256, verify it, then stream that snapshot on standard input.")
    print(json.dumps({"profile": profile, "environment": {"DBX_CONTAINER_MANAGER": "podman",
                      "DBX_SUDO_PROGRAM": "/bin/false"},
                      "steps": [{"argv": argv} for argv in steps], "notes": notes}, indent=2))
    return 0


def image_identity(reference, registry):
    raw = capture(["podman", "image", "inspect", reference]).stdout
    try:
        info = json.loads(raw)[0]
        if not isinstance(info, dict):
            raise ValueError("expected image configuration")
        if registry:
            if re.search(r"@sha256:[a-f0-9]{64}\Z", reference):
                return reference
            digests = info.get("RepoDigests") or []
            matching = [digest for digest in digests if isinstance(digest, str) and re.search(r"@sha256:[a-f0-9]{64}\Z", digest)]
            if not matching:
                raise CommandError("Registry image has no immutable RepoDigest; refusing an unpinned image.")
            # A pull normally produces one digest; use the requested repository when several exist.
            repository = reference.split("@")[0].rsplit(":", 1)[0] if ":" in reference.rsplit("/", 1)[-1] else reference.split("@")[0]
            preferred = [item for item in matching if item.split("@")[0] in (repository, "docker.io/" + repository)]
            if len(matching) > 1 and not preferred:
                raise CommandError("Ambiguous image digest; use a fully qualified repository reference.")
            return (preferred or matching)[0]
        image_id = info.get("Id") or info.get("ID")
        if isinstance(image_id, str) and re.fullmatch(r"[a-f0-9]{64}", image_id):
            image_id = "sha256:" + image_id
        if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise CommandError("Imported image lacks a valid immutable image ID.")
        return image_id
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise CommandError("Invalid image inspection data") from exc


def create(ctx, profile, definition):
    from . import integration
    name = f"flagship-{profile}"
    existing = inspect_container(name)
    if existing is not None:
        record = ensure_owned(ctx, profile, existing)
        ensure_configuration(record, existing)
        if record.get("workspace") != str(ctx.workspace):
            raise CommandError("Existing container uses a different workspace; use its original --workspace.")
        print(f"Reusing {name} ({record.get('image', 'recorded image')})")
        return 0
    record = read_json(ctx.record_path(profile), {})
    install = installation(ctx, create=True)
    image = locked_image(record)
    if not image:
        if definition["kind"] == "import":
            raise CommandError(f"Import a verified root filesystem for {profile} first.")
        checked_stream(["podman", "pull", definition["image"]])
        image = image_identity(definition["image"], registry=True)
    image_id = image_identity(image, registry=False)
    ctx.workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    ctx.home(profile).mkdir(mode=0o700, parents=True, exist_ok=True)
    for relative in (".config", ".cache", ".local/share", ".local/state"):
        (ctx.home(profile) / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
    record.update({"schema_version": 1, "profile": profile, "container": name,
                   "installation_id": install["installation_id"], "image": image, "image_id": image_id,
                   "workspace": str(ctx.workspace), "home": str(ctx.home(profile)),
                   "status": "creating"})
    atomic_json(ctx.record_path(profile), record)
    arguments = create_argv(ctx, profile, image, install["installation_id"])
    arguments[0] = integration.distrobox_launcher(ctx)
    checked_stream(arguments)
    created = inspect_container(name)
    if created is None:
        raise CommandError("Distrobox returned success but the container does not exist.")
    ensure_owned(ctx, profile, created)
    ensure_configuration(record, created)
    record["status"] = "created"
    atomic_json(ctx.record_path(profile), record)
    print(f"Created {name}; image locked to {image}")
    return 0


def validate_import(definition, args):
    if definition["kind"] != "import":
        raise CommandError("This profile uses a registry image; rootfs import is not supported.")
    if not HASH_RE.fullmatch(args.sha256):
        raise CommandError("--sha256 must contain exactly 64 hexadecimal characters.")


def import_tag(profile, digest):
    return f"localhost/flagship/{profile}:sha256-{digest.lower()}"


def import_argv(tag):
    return ["podman", "import", "--change", f"LABEL {LABEL}.managed=true", "-", tag]


def import_rootfs(ctx, args, definition):
    validate_import(definition, args)
    if inspect_container(f"flagship-{args.profile}") is not None:
        raise CommandError("Remove the existing container before importing its replacement image.")
    path = Path(args.path).expanduser()
    if not path.is_file():
        raise CommandError(f"Root filesystem archive is not a regular file: {path}")
    tag = import_tag(args.profile, args.sha256)
    with path.open("rb") as handle, tempfile.TemporaryFile(dir=ctx.state_dir) as snapshot:
        hasher = hashlib.sha256()
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
            snapshot.write(chunk)
        digest = hasher.hexdigest()
        if digest != args.sha256.lower():
            raise CommandError(f"SHA-256 mismatch: expected {args.sha256.lower()}, got {digest}; nothing imported.")
        snapshot.seek(0)
        checked_stream(import_argv(tag), stdin=snapshot)
    image = image_identity(tag, registry=False)
    install = installation(ctx, create=True)
    atomic_json(ctx.record_path(args.profile), {
        "schema_version": 1, "profile": args.profile, "container": f"flagship-{args.profile}",
        "installation_id": install["installation_id"], "imported_image": image,
        "archive_sha256": digest, "import_tag": tag, "status": "imported"})
    print(f"Imported {args.profile}: {image} (archive SHA-256 {digest})")
    return 0


def command_arguments(args):
    command = list(args.argv)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise CommandError("Supply a command after --, for example: flagship run kali -- bash", 2)
    return command


def profiles(catalog, as_json):
    if as_json:
        print(json.dumps({"schema_version": 1, "profiles": catalog}, indent=2))
    else:
        for name, definition in catalog.items():
            print(f"{name:10} {definition['kind']:8} {definition['name']}")
    return 0


def doctor(as_json, dry_run=False):
    checks = {"linux": sys.platform == "linux", "non_root": hasattr(os, "geteuid") and os.geteuid() != 0,
              "podman": bool(shutil.which("podman")), "distrobox": bool(shutil.which("distrobox"))}
    details = {}
    if checks["linux"] and checks["podman"] and not dry_run:
        result = capture(["podman", "info", "--format", "json"], check=False)
        try:
            info = json.loads(result.stdout)
            checks["rootless"] = info["host"]["security"]["rootless"] is True
            checks["rootless_network"], details["rootless_network"] = rootless_network_status(info)
        except (ValueError, KeyError, TypeError):
            checks["rootless"] = False
            checks["rootless_network"] = False
            details["podman"] = result.stderr.strip() or "Cannot parse podman info"
    else:
        checks["rootless"] = False
        checks["rootless_network"] = False
        if dry_run:
            details["rootless"] = "Engine checks skipped during dry run."
    result = {"ok": all(checks.values()), "checks": checks, "details": details}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        for name, passed in checks.items():
            print(f"{'OK' if passed else 'FAIL'} {name}")
        for message in details.values():
            print(message)
    return 0 if result["ok"] else 1


def status(ctx, catalog, as_json):
    containers = []
    for profile in catalog:
        record = read_json(ctx.record_path(profile))
        if not record:
            continue
        item = {"profile": profile, "name": f"flagship-{profile}", "image": record.get("image") or record.get("imported_image"),
                "status": record.get("status", "unknown"), "managed": False}
        if shutil.which("podman") and sys.platform == "linux" and not ctx.dry_run:
            container = inspect_container(item["name"])
            if container:
                try:
                    ensure_owned(ctx, profile, container)
                    item["managed"] = True
                    item["status"] = container.get("State", {}).get("Status", "unknown")
                    try:
                        ensure_configuration(record, container)
                    except CommandError as exc:
                        item["status"] = "configuration-drift"
                        item["detail"] = str(exc)
                except CommandError:
                    item["status"] = "foreign-collision"
            elif record.get("status") not in ("imported", "prepared"):
                item["status"] = "absent"
        containers.append(item)
    if as_json:
        print(json.dumps({"containers": containers, "state_dir": str(ctx.state_dir)}, indent=2))
    elif containers:
        for item in containers:
            print(f"{item['name']:24} {item['status']}")
    else:
        print("No recorded environments.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="flagship", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    def common(target, root=False):
        default = None if root else argparse.SUPPRESS
        target.add_argument("--state-dir", default=default, help="Private state directory")
        target.add_argument("--workspace", default=default, help="Shared directory mounted at /workspace")
        target.add_argument("--dry-run", action="store_true", default=False if root else argparse.SUPPRESS)
    common(parser, root=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("profiles", "doctor", "status", "plan", "prepare", "create", "provision", "run", "check", "import-rootfs", "remove",
                 "tools", "which", "exec", "shell", "prefer", "gpu"):
        sub = subparsers.add_parser(name)
        common(sub)
        if name in ("profiles", "doctor", "status", "tools", "which", "gpu"):
            sub.add_argument("--json", action="store_true")
        if name in ("plan", "prepare", "create", "provision", "run", "check", "import-rootfs", "remove", "gpu"):
            sub.add_argument("profile")
        if name == "gpu":
            sub.add_argument("--setup", action="store_true", help="Connect the WSL driver and add a verified NVRTC runtime when Hashcat needs it")
        if name == "run":
            sub.add_argument("argv", nargs=argparse.REMAINDER)
        if name == "import-rootfs":
            sub.add_argument("path")
            sub.add_argument("--sha256", required=True)
        if name == "remove":
            sub.add_argument("--yes", action="store_true", help="Confirm removal of the managed container")
        if name == "tools":
            sub.add_argument("--refresh", action="store_true", help="Discover executable commands from existing environments")
        if name in ("which", "exec", "prefer"):
            sub.add_argument("tool")
        if name in ("which", "exec"):
            sub.add_argument("--profile", help="Select an explicit provider")
        if name in ("exec", "shell"):
            sub.add_argument("argv", nargs=argparse.REMAINDER)
        if name == "prefer":
            sub.add_argument("provider", nargs="?")
            sub.add_argument("--clear", action="store_true", help="Clear a saved provider preference")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog()
        if args.command == "profiles":
            return profiles(catalog, args.json)
        if args.command == "doctor":
            return doctor(args.json, args.dry_run)
        state_base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        state_dir = Path(args.state_dir).expanduser() if args.state_dir else state_base / "flagship"
        workspace = Path(args.workspace).expanduser() if args.workspace else Path.home() / "flagship"
        ctx = Context(state_dir.absolute(), workspace.absolute(), args.dry_run)
        validate_paths(ctx)
        if args.command == "status":
            return status(ctx, catalog, args.json)
        if args.command in ("tools", "which", "exec", "shell", "prefer"):
            from . import tooling
            validate_backend_configuration()
            return tooling.main(ctx, args, catalog)
        if not NAME_RE.fullmatch(args.profile) or args.profile not in catalog:
            raise CommandError("Unknown profile; use 'flagship profiles' to list available names.", 2)
        definition = catalog[args.profile]
        if args.command == "run":
            command_arguments(args)
        validate_backend_configuration()
        if args.command == "gpu":
            from . import gpu
            return gpu.main(ctx, args.profile, args.setup, args.json)
        if args.command == "prepare":
            from . import preparation
            return preparation.main(ctx, args.profile)
        if args.command == "plan" or args.dry_run:
            return print_plan(ctx, args, definition)
        if args.command == "remove" and not args.yes:
            raise CommandError("Removal requires --yes. Home and workspace files will be retained.", 2)
        require_runtime()
        if args.command in ("run", "check"):
            managed_container(ctx, args.profile)
            if args.command == "run":
                return stream(enter_argv(args.profile, command_arguments(args)))
            failures = 0
            for command in definition.get("smoke_commands", []):
                code = stream(enter_argv(args.profile, command))
                print(f"{'PASS' if code == 0 else 'FAIL'} {json.dumps(command)} (exit {code})", flush=True)
                failures += code != 0
            return 1 if failures else 0
        with state_lock(ctx):
            if args.command == "create":
                return create(ctx, args.profile, definition)
            if args.command == "import-rootfs":
                return import_rootfs(ctx, args, definition)
            managed_container(ctx, args.profile, verify=args.command != "remove")
            if args.command == "provision":
                commands = provision_argv(args.profile, definition)
                for command in commands:
                    checked_stream(command)
                print("Provisioning complete." if commands else "This profile has no additional package installation step.")
            elif args.command == "remove":
                checked_stream(["distrobox", "rm", "--force", f"flagship-{args.profile}"])
                if inspect_container(f"flagship-{args.profile}") is not None:
                    raise CommandError("Container still exists after removal.")
                record = read_json(ctx.record_path(args.profile))
                record["status"] = "removed"
                atomic_json(ctx.record_path(args.profile), record)
                print(f"Removed flagship-{args.profile}; image lock, home and workspace retained.")
        return 0
    except CommandError as exc:
        print(f"flagship: {exc}", file=sys.stderr)
        return exc.code
    except (OSError, ValueError) as exc:
        print(f"flagship: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("flagship: interrupted", file=sys.stderr)
        return 130
