"""Opt-in local smoke test against one owned, rootless Kali container.

Run only on a disposable Linux runner with Podman and Distrobox installed.
No security tools are provisioned or executed. This does not test WSL.
The container is removed; its home, workspace, and state are deliberately
retained for the disposable runner to reclaim when it is destroyed.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def execute(argv, *, check=True, timeout=900, quiet=False):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    if result.stdout and not quiet:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {argv[0:3]}")
    return result


def container_id():
    result = execute(["podman", "container", "inspect", "flagship-kali"], quiet=True)
    return json.loads(result.stdout)[0]["Id"]


def main():
    if sys.platform != "linux" or os.geteuid() == 0:
        raise SystemExit("This smoke test requires an ordinary Linux user")
    rootless = execute(["podman", "info", "--format", "{{.Host.Security.Rootless}}"])
    if rootless.stdout.strip() != "true":
        raise SystemExit("Refusing to test a rootful Podman configuration")
    existing = execute(["podman", "container", "exists", "flagship-kali"], check=False)
    if existing.returncode != 1:
        raise SystemExit("Expected no existing flagship-kali container; refusing to touch it")

    executable = str(Path(sys.executable).with_name("flagship"))
    # Profile homes can contain files owned by subordinate user IDs. Python's
    # recursive cleanup cannot safely reclaim these from the host user account.
    root = Path(tempfile.mkdtemp(prefix="flagship-smoke-"))
    print(f"Smoke-test storage retained for runner disposal: {root}", flush=True)
    workspace = root / "workspace"
    base = [executable, "--state-dir", str(root / "state"), "--workspace", str(workspace)]
    cleanup_required = False
    failure = None
    try:
        execute(base + ["plan", "kali"])
        if workspace.exists() or (root / "state").exists():
            raise AssertionError("Planning modified the filesystem")
        cleanup_required = True
        execute(base + ["create", "kali"])
        original_id = container_id()
        execute(base + ["create", "kali"])
        if container_id() != original_id:
            raise AssertionError("Repeated create replaced the existing container")

        literal = "flagship-literal ; $(printf unexpected) * argument with spaces"
        result = execute(base + ["run", "kali", "--", "printf", "%s\n", literal])
        if literal not in result.stdout.splitlines():
            raise AssertionError("Container command did not preserve literal arguments")
        execute(base + [
            "run", "kali", "--", "sh", "-c",
            "printf '%s' 'flagship-workspace-ok' > /workspace/smoke.txt",
        ])
        if (workspace / "smoke.txt").read_text() != "flagship-workspace-ok":
            raise AssertionError("Shared workspace content was not visible on the host")
        execute(base + ["status", "--json"])
    except BaseException as error:
        failure = error
        execute(["podman", "logs", "--tail", "100", "flagship-kali"], check=False)
    finally:
        if cleanup_required:
            cleanup = execute(base + ["remove", "kali", "--yes"], check=False)
            if cleanup.returncode and failure is None:
                failure = RuntimeError("Owned container cleanup failed")
            remaining = execute(["podman", "container", "exists", "flagship-kali"], check=False)
            if remaining.returncode != 1 and failure is None:
                failure = RuntimeError("Smoke-test container still exists")
    if failure:
        raise failure
    print("Rootless container smoke test passed; owned container removed")


if __name__ == "__main__":
    main()
