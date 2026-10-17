"""Unified command discovery and routing over verified Flagship environments."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import sys
import tempfile

from . import cli as core

TOOL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
FORBIDDEN_ROOTS = ("/run/host", "/workspace", "/proc", "/sys", "/dev")
BASE_DIRS = ("/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/usr/sbin", "/bin", "/sbin", "/opt/bin")
MARKER = "FLAGSHIP_EXECUTABLES_V1\x00"
# This script is fixed source, never assembled from a tool name, path or argument.
# Paths enter as positional parameters; output uses NUL separators.
DISCOVERY_SCRIPT = r'''printf 'FLAGSHIP_EXECUTABLES_V1\000'
set -f
original_ifs=$IFS
IFS=:
set -- "$@" $PATH
IFS=$original_ifs
set +f
for directory in "$@" /opt/*/bin /home/*/.local/bin /home/*/bin /root/.local/bin /root/bin "$HOME/.local/bin" "$HOME/bin"; do
    [ -d "$directory" ] || continue
    for executable in "$directory"/*; do
        [ -f "$executable" ] && [ -x "$executable" ] || continue
        resolved=$(/usr/bin/readlink -f -- "$executable") || continue
        printf '%s\000%s\000%s\000' "${executable##*/}" "$executable" "$resolved"
    done
done
'''


def validate_tool_name(name):
    if not isinstance(name, str) or not TOOL_RE.fullmatch(name):
        raise core.CommandError("Tool names may contain letters, digits, dots, underscores, + and -; paths are not tool names.", 2)
    return name


def image_path(path):
    return (isinstance(path, str) and path.startswith("/") and path != "/"
            and "\x00" not in path and "\n" not in path
            and ".." not in PurePosixPath(path).parts
            and not any(path == root or path.startswith(root + "/") for root in FORBIDDEN_ROOTS))


def container_id(container):
    identity = container.get("Id") or container.get("ID")
    if not isinstance(identity, str) or not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", identity):
        raise core.CommandError("Container inspection did not return a valid identity.")
    return identity.removeprefix("sha256:")


def bound_paths(container):
    return [item["Destination"].rstrip("/") or "/" for item in container.get("Mounts", [])
            if isinstance(item, dict) and item.get("Type") == "bind" and isinstance(item.get("Destination"), str)]


def is_host_path(path, mounts, home=None):
    matching = [prefix for prefix in mounts if prefix == "/" or path == prefix or path.startswith(prefix + "/")]
    if not matching:
        return False
    closest = max(matching, key=len)
    return not (home and (path == home or path.startswith(home + "/"))
                and (closest == home or closest == "/" or home.startswith(closest + "/")))


def managed_home(ctx, profile, container, record):
    home = record.get("home")
    if home is None:
        return None
    expected = ctx.home(profile).absolute()
    if not isinstance(home, str) or Path(home).absolute() != expected or expected.resolve() != expected:
        raise core.CommandError(f"The {profile} home is outside its expected private directory.")
    mounts = [item for item in container.get("Mounts", []) if isinstance(item, dict) and item.get("Destination") == home]
    if (len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("RW") is not True
            or not isinstance(mounts[0].get("Source"), str) or Path(mounts[0]["Source"]).resolve() != expected):
        raise core.CommandError(f"The {profile} private home mount differs from its recorded directory.")
    return home


def discover_argv(profile, container, home=None):
    directories = []
    for variable in container.get("Config", {}).get("Env", []):
        if isinstance(variable, str) and variable.startswith("PATH="):
            directories += [path for path in variable[5:].split(":") if image_path(path)]
    directories += BASE_DIRS
    mounts = bound_paths(container)
    directories = list(dict.fromkeys(path for path in directories if not is_host_path(path, mounts, home)))
    return environment_argv(profile, ["/bin/sh", "-c", DISCOVERY_SCRIPT, "flagship-inventory", *directories])


def environment_argv(profile, command):
    argv = core.enter_argv(profile, command)
    argv.insert(2, "--clean-path")
    return argv


def parse_inventory(output, container, home=None):
    if MARKER not in output:
        raise core.CommandError("Executable discovery did not return its expected inventory marker.")
    fields = output.split(MARKER, 1)[1].split("\x00")
    if fields[-1] != "" or len(fields) % 3 != 1:
        raise core.CommandError("Executable discovery returned an incomplete inventory.")
    mounts, result = bound_paths(container), {}
    for name, path, resolved in zip(fields[0::3], fields[1::3], fields[2::3]):
        if (TOOL_RE.fullmatch(name) and image_path(path) and image_path(resolved)
                and not is_host_path(path, mounts, home) and not is_host_path(resolved, mounts, home)):
            result.setdefault(name, path)
    return dict(sorted(result.items()))


def refresh_inventory(ctx, catalog):
    entries = {}
    with core.state_lock(ctx):
        for profile in catalog:
            record = core.read_json(ctx.record_path(profile))
            if not record or record.get("status") in ("removed", "imported", "prepared"):
                continue
            print(f"Discovering commands in {profile}...", file=sys.stderr, flush=True)
            container, record = core.managed_container(ctx, profile)
            home = managed_home(ctx, profile, container, record)
            output = core.capture(discover_argv(profile, container, home)).stdout
            # Initialization may change process state, but may not replace this container.
            after, after_record = core.managed_container(ctx, profile)
            if container_id(after) != container_id(container):
                raise core.CommandError(f"Container {profile} changed during discovery; refresh again.")
            if managed_home(ctx, profile, after, after_record) != home:
                raise core.CommandError(f"Container {profile} home changed during discovery; refresh again.")
            entries[profile] = {"container_id": container_id(after), "image_id": after_record["image_id"],
                                "installation_id": after_record["installation_id"],
                                "home": home, "tools": parse_inventory(output, after, home)}
        if not entries:
            raise core.CommandError("No created environments to discover. Create and provision environments first.")
        inventory = {"schema_version": 1, "refreshed_at": datetime.now(timezone.utc).isoformat(), "profiles": entries}
        core.atomic_json(ctx.state_dir / "inventory.json", inventory)
    return inventory


def read_inventory(ctx, catalog):
    inventory = core.read_json(ctx.state_dir / "inventory.json")
    if not inventory:
        raise core.CommandError("No command inventory. Run 'flagship tools --refresh' first.")
    entries = inventory.get("profiles")
    if inventory.get("schema_version") != 1 or not isinstance(entries, dict):
        raise core.CommandError("Invalid command inventory; run 'flagship tools --refresh'.")
    for profile, entry in entries.items():
        if profile not in catalog or not isinstance(entry, dict) or not isinstance(entry.get("tools"), dict):
            raise core.CommandError("Invalid profile in command inventory; refresh it.")
        for name, path in entry["tools"].items():
            validate_tool_name(name)
            if not image_path(path):
                raise core.CommandError("Invalid executable path in command inventory; refresh it.")
    return inventory


def validate_provider(ctx, profile, entry):
    container, record = core.managed_container(ctx, profile)
    if (container_id(container) != entry.get("container_id") or record["image_id"] != entry.get("image_id")
            or record["installation_id"] != entry.get("installation_id")):
        raise core.CommandError(f"The cached {profile} inventory belongs to a different container; run 'flagship tools --refresh'.")
    mounts = bound_paths(container)
    home = managed_home(ctx, profile, container, record)
    if home != entry.get("home"):
        raise core.CommandError(f"The cached {profile} home has changed; refresh the inventory.")
    if any(is_host_path(path, mounts, home) for path in entry["tools"].values()):
        raise core.CommandError(f"The {profile} inventory includes a host mount; refresh it.")


def load_inventory(ctx, catalog):
    inventory = read_inventory(ctx, catalog)
    for profile, entry in inventory["profiles"].items():
        validate_provider(ctx, profile, entry)
    return inventory


def preferences(ctx, catalog):
    saved = core.read_json(ctx.state_dir / "preferences.json", {"schema_version": 1, "tools": {}})
    if saved.get("schema_version") != 1 or not isinstance(saved.get("tools"), dict):
        raise core.CommandError("Invalid tool preferences.")
    for name, profile in saved["tools"].items():
        validate_tool_name(name)
        if profile not in catalog:
            raise core.CommandError(f"Unknown preferred provider for {name}: {profile}")
    return saved["tools"]


def resolve_tool(inventory, name, catalog, profile=None, preferred=None):
    validate_tool_name(name)
    candidates = [{"profile": provider, "path": inventory["profiles"][provider]["tools"][name]}
                  for provider in catalog if provider in inventory["profiles"]
                  and name in inventory["profiles"][provider]["tools"]]
    selection = profile or (preferred or {}).get(name)
    selected = next((item for item in candidates if not selection or item["profile"] == selection), None)
    if selected is None:
        detail = f" in requested provider {selection}" if selection else ""
        raise core.CommandError(f"No indexed executable named {name}{detail}. Provision tools and refresh the inventory.", 127)
    return {"tool": name, "selected": selected, "candidates": candidates,
            "selection": "override" if profile else "preference" if (preferred or {}).get(name) else "catalog-priority"}


def exec_argv(ctx, profile, path, arguments, cwd=None):
    try:
        relative = Path(cwd or os.getcwd()).resolve().relative_to(ctx.workspace.resolve())
        workdir = str(PurePosixPath("/workspace") / relative.as_posix())
    except ValueError:
        workdir = "/workspace"
    # env handles a cwd containing spaces as one literal argument, without a shell.
    return environment_argv(profile, ["/usr/bin/env", "--chdir=" + workdir, path, *arguments])


def host_path(ctx):
    shell_root = (ctx.state_dir / "shells").resolve()
    result = []
    for path in os.environ.get("PATH", os.defpath).split(os.pathsep):
        if path and not Path(path).resolve().is_relative_to(shell_root):
            result.append(path)
    return os.pathsep.join(result)


def shell(ctx, inventory, command):
    names = sorted({name for entry in inventory["profiles"].values() for name in entry["tools"]})
    if not names:
        raise core.CommandError("The inventory has no executable commands.")
    with core.state_lock(ctx):
        directory = ctx.state_dir / "shells"
        directory.mkdir(mode=0o700, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="session-", dir=directory)
        shims = Path(temporary.name)
        dispatcher = shims / ".dispatch"
        launch = [str(Path(sys.executable).absolute()), "-m", "flagship", "--state-dir", str(ctx.state_dir),
                  "--workspace", str(ctx.workspace), "exec"]
        dispatcher.write_text('#!/bin/sh\ntool=${0##*/}\nexec ' + shlex.join(launch) + ' "$tool" -- "$@"\n', encoding="utf-8")
        dispatcher.chmod(0o700)
        for name in names:
            (shims / name).symlink_to(".dispatch")
        rcfile = shims / ".bashrc"
        rcfile.write_text('if [ -r "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n'
                          + 'export PATH="$PATH":' + shlex.quote(str(shims)) + '\n'
                          + 'cd -- ' + shlex.quote(str(ctx.workspace)) + '\n'
                          + 'PS1="[FlagshipOS] ${PS1:-\\u@\\h:\\w\\$ }"\n', encoding="utf-8")
    try:
        environment = core.backend_env()
        environment["PATH"] = host_path(ctx)
        environment["FLAGSHIP_WORKSPACE"] = str(ctx.workspace)
        environment["FLAGSHIP_ACTIVE"] = "1"
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            bash = shutil.which("bash", path=host_path(ctx))
            if not bash:
                raise core.CommandError("Bash is required for the unified shell.")
            command = [bash, "--noprofile", "--rcfile", str(rcfile), "-i"]
            print("FlagshipOS shell: host commands take priority; specialist commands route automatically. Exit to return.", flush=True)
        else:
            environment["PATH"] += os.pathsep + str(shims)
        return core.stream(command, env=environment, cwd=ctx.workspace)
    finally:
        temporary.cleanup()


def main(ctx, args, catalog):
    if getattr(args, "tool", None):
        validate_tool_name(args.tool)
    if getattr(args, "profile", None) and args.profile not in catalog:
        raise core.CommandError("Unknown provider profile.", 2)
    if args.command == "prefer":
        if bool(args.provider) == args.clear:
            raise core.CommandError("Use 'flagship prefer TOOL PROFILE' or 'flagship prefer TOOL --clear'.", 2)
        if args.provider and args.provider not in catalog:
            raise core.CommandError("Unknown preferred provider profile.", 2)
    if ctx.dry_run:
        print(json.dumps({"command": args.command, "tool": getattr(args, "tool", None),
                          "notes": ["Planning only: no discovery, commands, files or state changes."]}, indent=2))
        return 0
    core.require_runtime()
    if args.command == "tools" and args.refresh:
        inventory = refresh_inventory(ctx, catalog)
    elif args.command == "exec":
        inventory = read_inventory(ctx, catalog)
    elif args.command == "prefer" and args.clear:
        inventory = None
    else:
        inventory = load_inventory(ctx, catalog)
    saved = preferences(ctx, catalog)
    if args.command == "tools":
        names = sorted({name for entry in inventory["profiles"].values() for name in entry["tools"]})
        rows = [resolve_tool(inventory, name, catalog, preferred=saved) for name in names]
        result = {"refreshed_at": inventory["refreshed_at"], "tools": rows, "profiles": list(inventory["profiles"])}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{len(names)} commands from {len(inventory['profiles'])} environments; refreshed {inventory['refreshed_at']}")
            for row in rows:
                providers = ", ".join(item["profile"] for item in row["candidates"])
                print(f"{row['tool']:32} {row['selected']['profile']:10} {providers}")
        return 0
    if args.command == "prefer":
        with core.state_lock(ctx):
            saved = preferences(ctx, catalog)
            if args.clear:
                saved.pop(args.tool, None)
            else:
                resolve_tool(inventory, args.tool, catalog, profile=args.provider)
                saved[args.tool] = args.provider
            core.atomic_json(ctx.state_dir / "preferences.json", {"schema_version": 1, "tools": saved})
        print(f"Cleared preference for {args.tool}." if args.clear else f"{args.tool} now uses {args.provider}.")
        return 0
    if args.command == "shell":
        return shell(ctx, inventory, args.argv)
    result = resolve_tool(inventory, args.tool, catalog, profile=args.profile, preferred=saved)
    selected = result["selected"]
    if args.command == "which":
        result["host_command"] = shutil.which(args.tool, path=host_path(ctx))
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{args.tool} -> {selected['profile']}:{selected['path']} ({result['selection']})")
            print("Available: " + ", ".join(item["profile"] for item in result["candidates"]))
            if result["host_command"]:
                print(f"Host command wins in the unified shell: {result['host_command']}. Use flagship exec to select an environment.")
        return 0
    validate_provider(ctx, selected["profile"], inventory["profiles"][selected["profile"]])
    arguments = list(args.argv)
    if arguments and arguments[0] == "--":
        arguments.pop(0)
    return core.stream(exec_argv(ctx, selected["profile"], selected["path"], arguments))
