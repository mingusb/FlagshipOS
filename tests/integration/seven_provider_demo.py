#!/usr/bin/env python3
"""Real, opt-in acceptance demonstration for seven already-created environments.

Run with the installed flagship executable, as its ordinary Linux owner:
  python3 tests/integration/seven_provider_demo.py \
    --state-dir /path/to/private/state --workspace /path/to/shared/workspace

Requires Kali, Parrot, BackBox, REMnux, CAINE, Tsurugi and SIFT to be created
and provisioned. This script does not install tools, create environments, use
simulated providers, scan targets, or execute exploits. Missing environments,
tools or a host command that would shadow a specialist command are failures.

The real unified shell runs all seven version checks, changes an actual
exiftool collision preference, and performs this local evidence workflow:
  CAINE dc3dd -> Parrot exiftool over a pipe;
  CAINE dc3dd writes a shared file -> Parrot reads metadata -> REMnux YARA reads it.
The source filename contains spaces and literal shell syntax. A missing YARA
rules file checks that the bare command preserves the direct command's failure
status. The same evidence is also opened using its absolute host workspace path.
Only newly generated text and a harmless matching YARA rule are used.

Run in a dedicated verification state/workspace, without concurrent preference
changes. Touched preferences are restored in finally. A unique private workspace
subdirectory retains proof.json, transcript.txt, shell scripts and small fixtures.
Receipts include bounded excerpts, output hashes and byte counts. Transcript
headers are generated annotations around actual captured output; this is not a
PTY recording or a claim that every installed tool works.

dc3dd stdout convention: https://www.kali.org/tools/dc3dd/
ExifTool stdin convention: https://exiftool.org/exiftool_pod.html
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


TOOLS = {
    "kali": ("nmap", "--version"),
    "parrot": ("exiftool", "-ver"),
    "remnux": ("yara", "--version"),
    "backbox": ("foremost", "-V"),
    "sift": ("mmls", "-V"),
    "caine": ("dc3dd", "--version"),
    "tsurugi": ("fls", "-V"),
}
MAX_OUTPUT = 32 * 1024 * 1024
EXCERPT = 8000

VERSION_SCRIPT = r'''#!/bin/bash
set -euo pipefail
cd -- "$1"
for tool in nmap exiftool yara foremost mmls dc3dd fls; do
    resolved=$(command -v "$tool")
    case "$resolved" in
        "$2"/shells/session-*/"$tool") ;;
        *) printf 'FAIL: %s resolved outside the private Flagship session: %s\n' "$tool" "$resolved" >&2; exit 1 ;;
    esac
    test -L "$resolved"
    test "$(readlink -- "$resolved")" = .dispatch
    test -x "${resolved%/*}/.dispatch"
    printf 'FLAGSHIP_SHIM_PROOF\t%s\t%s\n' "$tool" "$resolved"
done
printf '\n[annotation: Kali / nmap]\n'
nmap --version
printf '\n[annotation: Parrot / exiftool]\n'
exiftool -ver
printf '\n[annotation: REMnux / yara]\n'
yara --version
printf '\n[annotation: BackBox / foremost]\n'
foremost -V
printf '\n[annotation: SIFT / mmls]\n'
mmls -V
printf '\n[annotation: CAINE / dc3dd]\n'
dc3dd --version
printf '\n[annotation: Tsurugi / fls]\n'
fls -V
'''

WORKFLOW_SCRIPT = r'''#!/bin/bash
set -euo pipefail
cd -- "$1"
printf '\n[annotation: CAINE -> Parrot, real stdin/stdout pipeline]\n'
dc3dd "if=$2" hash=sha256 'log=dc3dd pipeline.log' \
    | exiftool -j -FileType -FileSize - \
    | tee 'pipeline metadata.json'
printf '\n[annotation: CAINE writes the shared evidence copy]\n'
dc3dd "if=$2" "of=$3" hash=sha256 'log=dc3dd copy.log'
printf '\n[annotation: Parrot reads metadata from the same shared file]\n'
exiftool -j -FileName -FileType "$3" | tee 'shared file metadata.json'
printf '\n[annotation: REMnux matches a harmless text marker in the same file]\n'
yara 'fixture rules.yar' "$3" | tee 'YARA result.txt'
'''


class AcceptanceFailure(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class Demo:
    def __init__(self, executable, state, workspace, timeout):
        self.state, self.workspace, self.timeout = state, workspace, timeout
        self.directory = Path(tempfile.mkdtemp(prefix="flagship-seven-provider-", dir=workspace))
        self.base = [executable, "--state-dir", str(state), "--workspace", str(workspace)]
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in ("BASH_ENV", "ENV", "CDPATH") and not key.startswith("BASH_FUNC_")}
        self.proof = {"schema_version": 1, "started_at": now(), "passed": False,
                      "workspace": str(workspace), "artifacts": str(self.directory),
                      "scope": "Seven real providers; version checks and newly generated local text fixtures only",
                      "transcript_kind": "Captured output with labeled generated annotations; not a PTY recording",
                      "steps": [], "providers": {}, "preference_restore": []}
        self.transcript = (self.directory / "transcript.txt").open("x", encoding="utf-8")
        self.transcript.write(self.proof["transcript_kind"] + "\n")
        self.changed = []
        self.previous = {}

    @staticmethod
    def stop(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)

    @staticmethod
    def output(handle):
        size = handle.tell()
        handle.seek(0)
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        handle.seek(0)
        data = handle.read(min(size, MAX_OUTPUT))
        text = data.decode("utf-8", errors="replace")
        excerpt = text if len(text) <= EXCERPT else text[:EXCERPT // 2] + "\n[output excerpt truncated]\n" + text[-EXCERPT // 2:]
        return text, {"bytes": size, "sha256": digest, "excerpt": excerpt, "truncated": len(text) > EXCERPT}

    def run(self, label, arguments, *, expected=0, external=False):
        argv = list(arguments) if external else self.base + list(arguments)
        started = time.monotonic()
        error = None
        with tempfile.TemporaryFile(dir=self.directory) as stdout, tempfile.TemporaryFile(dir=self.directory) as stderr:
            process = subprocess.Popen(argv, cwd=self.directory, env=self.environment,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                code = process.wait(timeout=self.timeout)
            except BaseException as exception:
                self.stop(process)
                code = process.returncode
                error = f"{type(exception).__name__}: {exception}"
            code = code if code >= 0 else 128 - code
            out, out_receipt = self.output(stdout)
            err, err_receipt = self.output(stderr)
        receipt = {"label": label, "argv": argv, "exit_code": code,
                   "seconds": round(time.monotonic() - started, 3), "stdout": out_receipt, "stderr": err_receipt}
        if error:
            receipt["interruption"] = error
        self.proof["steps"].append(receipt)
        self.transcript.write(f"\n[generated command annotation: {label}]\n$ {shlex.join(argv)}\n")
        self.transcript.write(out_receipt["excerpt"])
        if err_receipt["excerpt"]:
            self.transcript.write("\n[generated stderr annotation]\n" + err_receipt["excerpt"])
        self.transcript.write(f"\n[generated exit-status annotation: {code}]\n")
        self.transcript.flush()
        print(f"{label}: exit {code}", flush=True)
        if max(out_receipt["bytes"], err_receipt["bytes"]) > MAX_OUTPUT:
            raise AcceptanceFailure(f"{label}: output exceeded the {MAX_OUTPUT}-byte parsing limit")
        if error:
            raise AcceptanceFailure(f"{label}: {error}")
        if expected is not None and code != expected:
            raise AcceptanceFailure(f"{label}: expected exit {expected}, got {code}; see transcript")
        return code, out, err

    def json(self, label, arguments):
        _, output, _ = self.run(label, arguments)
        try:
            return json.loads(output)
        except ValueError as error:
            raise AcceptanceFailure(f"{label}: command did not produce valid JSON") from error

    def prefer(self, tool, provider):
        if tool not in self.changed:
            self.changed.append(tool)
        self.run(f"Prefer {tool} from {provider}", ["prefer", tool, provider])

    def provenance(self, tool, provider):
        receipt = self.json(f"Resolve {tool} to {provider}", ["which", tool, "--json"])
        if receipt.get("host_command"):
            raise AcceptanceFailure(f"Host command {receipt['host_command']} shadows {tool}; the real provider would not run")
        if receipt.get("selected", {}).get("profile") != provider or receipt.get("selection") != "preference":
            raise AcceptanceFailure(f"{tool} did not resolve to its requested actual provider {provider}")
        return receipt

    def shell(self, label, command, *, expected=0):
        return self.run(label, ["shell", "--", *command], expected=expected)

    def validate(self):
        if sys.platform != "linux" or os.geteuid() == 0:
            raise AcceptanceFailure("Run as the ordinary Linux user who owns these seven environments")
        saved = self.state / "preferences.json"
        if saved.exists():
            preferences = json.loads(saved.read_text(encoding="utf-8"))
            if preferences.get("schema_version") != 1 or not isinstance(preferences.get("tools"), dict):
                raise AcceptanceFailure("Existing preferences are invalid; refusing to change them")
            self.previous = preferences["tools"]
        status = self.json("Require all seven real managed containers", ["status", "--json"])
        containers = {item["profile"]: item for item in status.get("containers", [])}
        for profile in TOOLS:
            item = containers.get(profile, {})
            if not item.get("managed") or item.get("status") not in ("running", "exited", "created", "configured", "stopped"):
                raise AcceptanceFailure(f"{profile}: a real managed, correctly configured container is required; got {item.get('status', 'missing')}")
        inventory = self.json("Refresh real executable inventory", ["tools", "--refresh", "--json"])
        if not set(TOOLS).issubset(inventory.get("profiles", [])):
            raise AcceptanceFailure("Executable discovery did not include all seven real providers")
        rows = {row["tool"]: row for row in inventory["tools"]}
        counts = {profile: sum(any(candidate["profile"] == profile for candidate in row["candidates"])
                               for row in rows.values()) for profile in TOOLS}
        self.proof["inventory"] = {"refreshed_at": inventory["refreshed_at"], "unique_commands": len(rows),
                                   "commands_per_provider": counts}
        _, identities, _ = self.run("Record actual container identities", ["podman", "container", "inspect", "--format",
            "{{.Id}} {{.Name}} {{.Image}}", *[f"flagship-{profile}" for profile in TOOLS]], external=True)
        self.proof["container_identities"] = identities.splitlines()
        for profile, (tool, _) in TOOLS.items():
            if not any(item["profile"] == profile for item in rows.get(tool, {}).get("candidates", [])):
                raise AcceptanceFailure(f"Required command {tool} is missing from {profile}; no substitute will be installed or selected")
        collision = rows["exiftool"]["candidates"]
        if not {"kali", "parrot"}.issubset({item["profile"] for item in collision}):
            raise AcceptanceFailure("The collision demonstration requires real exiftool installations in both Kali and Parrot")
        for profile, (tool, _) in TOOLS.items():
            self.prefer(tool, profile)
            self.proof["providers"][profile] = self.provenance(tool, profile)

        version_script = self.directory / "versions.sh"
        version_script.write_text(VERSION_SCRIPT, encoding="utf-8")
        _, versions, _ = self.shell("All seven bare specialist commands in one shell",
            ["bash", "--noprofile", "--norc", str(version_script), str(self.directory), str(self.state)])
        observed_shims = {}
        for line in versions.splitlines():
            if line.startswith("FLAGSHIP_SHIM_PROOF\t"):
                _, tool, path = line.split("\t", 2)
                observed_shims[tool] = path
        if set(observed_shims) != {tool for tool, _ in TOOLS.values()}:
            raise AcceptanceFailure("The real shell did not verify all seven private dispatcher shims")
        self.proof["observed_private_shims"] = observed_shims
        self.prefer("exiftool", "kali")
        selected_kali = self.provenance("exiftool", "kali")
        self.shell("Same bare exiftool name now runs Kali", ["exiftool", "-ver"])
        self.prefer("exiftool", "parrot")
        selected_parrot = self.provenance("exiftool", "parrot")
        self.proof["collision"] = {"tool": "exiftool", "first": selected_kali, "second": selected_parrot}

        source_name = "evidence with spaces ; $(touch SHOULD_NOT_EXIST).txt"
        copy_name = "copied evidence with spaces.txt"
        evidence = b"FlagshipOS deterministic local evidence\nFLAGSHIP_SEVEN_PROVIDER_FIXTURE_v1\n"
        (self.directory / source_name).write_bytes(evidence)
        (self.directory / "fixture rules.yar").write_text(
            'rule FlagshipFixture { strings: $marker = "FLAGSHIP_SEVEN_PROVIDER_FIXTURE_v1" condition: $marker }\n', encoding="utf-8")
        workflow = self.directory / "shared-workflow.sh"
        workflow.write_text(WORKFLOW_SCRIPT, encoding="utf-8")
        self.shell("Three-provider shared evidence workflow and two-provider pipeline",
                   ["bash", "--noprofile", "--norc", str(workflow), str(self.directory), source_name, copy_name])
        copied = (self.directory / copy_name).read_bytes()
        if copied != evidence:
            raise AcceptanceFailure("CAINE's shared evidence copy did not match the original bytes")
        if (self.directory / "SHOULD_NOT_EXIST").exists():
            raise AcceptanceFailure("Literal filename contents were interpreted as shell syntax")
        pipeline = json.loads((self.directory / "pipeline metadata.json").read_text())
        metadata = json.loads((self.directory / "shared file metadata.json").read_text())
        if pipeline[0].get("FileType") != "TXT" or metadata[0].get("FileName") != copy_name:
            raise AcceptanceFailure("Parrot did not identify the piped and shared text evidence correctly")
        yara = (self.directory / "YARA result.txt").read_text()
        if f"FlagshipFixture {copy_name}" not in yara.splitlines():
            raise AcceptanceFailure("REMnux did not match the fixture rule against the shared evidence file")
        self.proof["shared_evidence"] = {"source_name": source_name, "copy_name": copy_name,
            "bytes": len(evidence), "sha256": hashlib.sha256(evidence).hexdigest(), "identical_copy": True,
            "pipeline": "caine:dc3dd stdout -> parrot:exiftool stdin", "yara_match": yara.strip()}

        absolute_copy = str(self.directory / copy_name)
        _, absolute_metadata, _ = self.shell("Bare exiftool reads the absolute host workspace filename",
            ["exiftool", "-j", "-FileName", absolute_copy])
        if json.loads(absolute_metadata)[0].get("FileName") != copy_name:
            raise AcceptanceFailure("Parrot could not read the evidence by its absolute host workspace path")
        _, absolute_yara, _ = self.shell("Bare yara reads absolute host workspace filenames",
            ["yara", str(self.directory / "fixture rules.yar"), absolute_copy])
        if f"FlagshipFixture {absolute_copy}" not in absolute_yara.splitlines():
            raise AcceptanceFailure("REMnux could not read the evidence and rule by their absolute host workspace paths")
        self.proof["absolute_workspace_paths"] = {"evidence": absolute_copy,
            "parrot_metadata": True, "remnux_rule_and_evidence": True,
            "scope": "This actual workspace path; arbitrary host paths are not inferred to be accessible"}

        # The rules file deliberately does not exist. Neither call can run a scan.
        missing = "rules file deliberately absent.yar"
        direct, _, _ = self.run("Direct provider failure status", ["exec", "--profile", "remnux", "yara", "--", missing, copy_name], expected=None)
        bare, _, _ = self.shell("Bare command preserves failure status", ["bash", "--noprofile", "--norc", "-c",
            'cd -- "$1"; exec yara "$2" "$3"', "flagship-local-failure", str(self.directory), missing, copy_name], expected=None)
        if direct == 0 or bare != direct:
            raise AcceptanceFailure(f"Failure status was not preserved: direct={direct}, bare={bare}")
        self.proof["failure_status"] = {"direct": direct, "bare": bare, "preserved": True}
        # Validate ownership/configuration and the same IDs again after execution.
        final = self.json("Validate providers after demonstration", ["tools", "--json"])
        if not set(TOOLS).issubset(final.get("profiles", [])):
            raise AcceptanceFailure("A provider disappeared during the demonstration")

    def finish(self, failure):
        for tool in reversed(self.changed):
            provider = self.previous.get(tool)
            command = ["prefer", tool, provider] if provider else ["prefer", tool, "--clear"]
            try:
                self.run(f"Restore original preference for {tool}", command)
                self.proof["preference_restore"].append({"tool": tool, "restored": True})
            except Exception as error:
                self.proof["preference_restore"].append({"tool": tool, "restored": False, "error": str(error)})
                failure = failure or f"Preference restoration failed for {tool}: {error}"
        self.proof["finished_at"] = now()
        self.proof["passed"] = failure is None
        if failure:
            self.proof["failure"] = failure
        with (self.directory / "proof.json").open("x", encoding="utf-8") as output:
            json.dump(self.proof, output, indent=2)
            output.write("\n")
        self.transcript.write(f"\n[generated result annotation: {'FAIL: ' + failure if failure else 'PASS'}]\n")
        self.transcript.close()
        print(f"{'FAIL' if failure else 'PASS'}: proof and captured output retained at {self.directory}", flush=True)
        return 1 if failure else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--flagship", default="flagship", help="Installed Flagship executable; no mock dispatcher")
    parser.add_argument("--timeout", type=int, default=600, help="Maximum seconds per command (default: 600)")
    args = parser.parse_args(argv)
    executable = shutil.which(args.flagship)
    if not executable:
        parser.error("The installed flagship executable was not found")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    state, workspace = args.state_dir.expanduser().resolve(), args.workspace.expanduser().resolve()
    if not state.is_dir() or not workspace.is_dir():
        parser.error("State and workspace must already exist; create and provision all seven environments first")
    demo = Demo(executable, state, workspace, args.timeout)
    failure = None
    try:
        demo.validate()
    except BaseException as error:
        failure = f"{type(error).__name__}: {error}"
    return demo.finish(failure)


if __name__ == "__main__":
    raise SystemExit(main())
