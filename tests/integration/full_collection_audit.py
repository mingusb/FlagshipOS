#!/usr/bin/env python3
"""Read-only installation evidence for seven existing Flagship environments.

Run with the Python environment in which Flagship is installed:
  python tests/integration/full_collection_audit.py \
    --state-dir /path/to/state --workspace /path/to/workspace \
    --manifest caine=/path/to/caine-filesystem.manifest \
    --manifest tsurugi=/path/to/tsurugi-filesystem.manifest \
    --iso-receipt caine=/path/to/caine-manifest-audit.json \
    --output /path/to/new-installation-audit.json

Only already-running owned containers are examined. Prepared images and stopped
containers are reported as unavailable; nothing is started, installed, updated,
or provisioned. No tool scans or exploits run. The only persistent write is the
new JSON report. Do not provision or replace environments during the audit.

Manifest files use the live ISO's `Package Version` format. Duplicate package
records are retained because publisher manifests can omit architecture. Their
local hashes and supplied conversion receipts are evidence, not independent
authentication of the publisher. Keep checksum/signature verification receipts.
An ISO audit receipt binds archive_sha256, publisher_manifest_sha256 and the
source_checksum/source_checksum_algorithm. The socket-only conversion sidecar
alone has no package-manifest binding and is reported as insufficient evidence.

Exit 0 means the requested installation checks have sufficient passing evidence;
1 means failures or unavailable evidence; 2 means invalid arguments. This is not
a claim that every GUI, service, kernel, or hardware-dependent tool works.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from flagship import cli as core


PROFILES = ("kali", "parrot", "backbox", "remnux", "sift", "caine", "tsurugi")
METAPACKAGES = {"kali": "kali-linux-everything", "parrot": "parrot-tools-full", "backbox": "backbox-tools"}
CAST_EXPECTED = {
    "sift": ("teamdfir/sift-saltstack", "v2026.04.21", "desktop"),
    "remnux": ("remnux", "v2026.42.3", "dedicated"),
}
ISO_RELEASES = {
    "caine": {"release": "CAINE 14 Lightstream", "algorithm": "sha256",
              "checksum": "2702226cf9ee131ee54e9649d6d90008f3fe851ba35939f43ae8cb614a00d564",
              "source": "https://www.caine-live.net/page5/caine14.0.iso.sha256.txt"},
    "tsurugi": {"release": "Tsurugi LAB 26.03", "algorithm": "sha512",
                "checksum": "1284c3b4145ef2201e831350fde20a1445171be66ca34ab909cbd22eb77d5f19ec28a26275955538bddf7abb77ec5ac0c05f3383502c2ac83770150be1c31d8c",
                "source": "https://tsurugi-linux.org/signed_hashes.sha512"},
}
INVENTORY = "/usr/local/share/flagship/package-inventory.tsv"

# Fixed, read-only commands. Python -I ignores inherited PYTHONPATH/startup code.
# apt simulation disables locking and disk caches; it does not fetch repositories.
PROBE = r'''
import hashlib,json,os,pathlib,stat,subprocess,sys
options=json.loads(sys.argv[1])
denied=[pathlib.PurePosixPath(p) for p in options['binds']]
def blocked(path):
    path=pathlib.PurePosixPath(path)
    return any(path==root or root in path.parents for root in denied)
def read(path,content=True):
    p=pathlib.Path(path)
    if blocked(path) or blocked(str(p.resolve())):
        return {'status':'unavailable','reason':'path is supplied by a bind mount'}
    try:
        if not stat.S_ISREG(p.stat().st_mode):
            return {'status':'unavailable','reason':'not a regular file'}
        with p.open('rb') as handle:
            digest=hashlib.file_digest(handle,'sha256').hexdigest()
            size=handle.tell()
            if content:
                handle.seek(0)
                data=handle.read(16*1024*1024+1)
                if len(data)>16*1024*1024:
                    return {'status':'unavailable','reason':'text exceeds 16 MiB','sha256':digest,'bytes':size}
        item={'status':'present','sha256':digest,'bytes':size}
        if content:item['text']=data.decode('utf-8',errors='strict')
        return item
    except (OSError,UnicodeError) as error:
        return {'status':'unavailable','reason':str(error)}
def command(argv):
    try:
        value=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             env=dict(os.environ,LC_ALL='C',LANG='C'),timeout=120,check=False)
        if max(len(value.stdout),len(value.stderr))>16*1024*1024:
            return {'status':'unavailable','reason':'command output exceeds 16 MiB','argv':argv}
        return {'status':'observed','argv':argv,'exit_code':value.returncode,
                'stdout':value.stdout.decode('utf-8',errors='replace'),
                'stderr':value.stderr.decode('utf-8',errors='replace')}
    except (OSError,subprocess.TimeoutExpired) as error:
        return {'status':'unavailable','reason':str(error),'argv':argv}
result={'files':{}}
before=read('/var/lib/dpkg/status',False)
if before.get('status')!='present':
    raise SystemExit('Cannot audit an absent or host-bind-mounted package database')
paths=['/etc/os-release','/etc/lsb-release','/etc/issue','/etc/debian_version',
       '/usr/local/share/flagship/package-inventory.tsv']
if options['installer']:
    paths+=['/root/.config/cast/state.yaml','/home/'+options['profile']+'/.config/cast/state.yaml']
for path in paths:result['files'][path]=read(path)
if options['installer']:
    path='/var/cache/cast/installer/logs/results.yaml'
    result['files'][path]=read(path,False)
result['inventory']=command(['/usr/bin/dpkg-query','-W',
    '-f=${binary:Package}\t${Package}\t${Architecture}\t${Version}\t${db:Status-Abbrev}\n'])
result['dpkg_audit']=command(['/usr/bin/dpkg','--audit'])
apt=['/usr/bin/apt-get','--simulate','-o','Debug::NoLocking=1',
     '-o','Dir::Cache::pkgcache=','-o','Dir::Cache::srcpkgcache=']
result['dependencies']=command(apt+['check'])
if options['meta']:
    result['metapackage_simulation']=command(apt+['--no-remove','--no-upgrade','--install-recommends',
                                                 'install','--',options['meta']])
after=read('/var/lib/dpkg/status',False)
result['package_database']={'before':before,'after':after,'stable':
    before.get('status')=='present' and before.get('sha256')==after.get('sha256')}
print(json.dumps(result))
'''


def inventory(text, baseline=False):
    rows, seen = [], set()
    for line in text.splitlines():
        values = line.split("\t")
        if baseline and len(values) == 4:
            binary, version, architecture, status = values
            package = binary.split(":", 1)[0]
        elif not baseline and len(values) == 5:
            binary, package, architecture, version, status = values
        else:
            raise ValueError("Invalid package inventory row")
        if not all((binary, package, architecture, version)) or len(status) != 3 or binary in seen:
            raise ValueError("Invalid or duplicate package inventory identity")
        seen.add(binary)
        rows.append({"binary_package": binary, "package": package, "architecture": architecture,
                     "version": version, "status": status, "installed": status[1:] == "i "})
    if not rows:
        raise ValueError("Empty package inventory")
    return rows


def manifest(text):
    result = Counter()
    for line in text.splitlines():
        if not line.strip():
            continue
        values = line.split()
        if len(values) != 2 or not re.fullmatch(r"[a-z0-9][a-z0-9+.:-]*", values[0]):
            raise ValueError("Invalid ISO package manifest row")
        result[tuple(values)] += 1
    if not result:
        raise ValueError("Empty ISO package manifest")
    return result


def compare_packages(expected, rows, installed_only=True):
    actual = Counter((row["package"], row["version"]) for row in rows if row["installed"] or not installed_only)
    def records(items):
        return [{"package": package, "version": version, "count": count}
                for (package, version), count in sorted(items.items())]
    missing, additions = expected - actual, actual - expected
    return {"status": "pass" if not missing else "fail", "expected_records": sum(expected.values()),
            "compared_records": sum(actual.values()), "installed_only": installed_only,
            "actual_installed_records": sum(row["installed"] for row in rows), "missing_or_changed": records(missing),
            "additional_or_changed": records(additions),
            "meaning": "Package/version multiset comparison; additions are reported and allowed, changed versions are gaps"}


def iso_binding(profile, receipt, record, manifest_sha256):
    expected = ISO_RELEASES[profile]
    archive_matches = bool(receipt.get("archive_sha256") and receipt["archive_sha256"] == record.get("archive_sha256"))
    manifest_matches = bool(manifest_sha256 and receipt.get("publisher_manifest_sha256") == manifest_sha256)
    source_matches = (receipt.get("source_checksum_algorithm") == expected["algorithm"]
                      and receipt.get("source_checksum") == expected["checksum"])
    sufficient = archive_matches and manifest_matches and source_matches
    return {"status": "pass" if sufficient else "unavailable", "matches_imported_archive": archive_matches,
            "matches_supplied_manifest": manifest_matches, "matches_published_source_checksum": source_matches,
            "expected_release": expected, "receipt": receipt,
            "meaning": "Local conversion-audit receipt binds source checksum, manifest and imported archive; publisher signature verification is retained separately"}


def cast_state(text, expected):
    """Parse only Cast's emitted small scalar schema; unknown YAML fails closed.

    Source: github.com/ekristen/cast/blob/v1.0.42/pkg/state/state.go
    State is saved after successful install; it is not a per-tool runtime test.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "installations:":
        raise ValueError("Unsupported Cast state format")
    installations, current = {}, None
    for line in lines[1:]:
        if not line.strip():
            continue
        key = re.fullmatch(r"    ([A-Za-z0-9_./@+-]+):", line)
        field = re.fullmatch(r"        (distro_name|version|mode): ([A-Za-z0-9_./@+-]+)", line)
        if key:
            current = key[1]
            if current in installations:
                raise ValueError("Duplicate Cast installation")
            installations[current] = {}
        elif field and current and field[1] not in installations[current]:
            installations[current][field[1]] = field[2]
        else:
            raise ValueError("Unsupported or ambiguous Cast state field")
    name, version, mode = expected
    observed = installations.get(name)
    match = observed == {"distro_name": name, "version": version, "mode": mode}
    return {"status": "pass" if match else "fail", "expected": {"distro_name": name, "version": version, "mode": mode},
            "observed": observed, "basis": "Upstream Cast successful-install state; results log retained separately"}


def os_release(text):
    values = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z_0-9]+", key) or key in values:
            raise ValueError("Invalid os-release data")
        parts = shlex.split(value)
        if len(parts) > 1:
            raise ValueError("Invalid os-release value")
        values[key] = parts[0] if parts else ""
    return values


def observe(argv, timeout=180):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=core.backend_env(), timeout=timeout, check=False)
    if result.returncode:
        raise ValueError(f"Command failed ({result.returncode}): {argv[:3]}: {result.stderr.decode(errors='replace')[:4000]}")
    return json.loads(result.stdout)


def audit_profile(ctx, profile, manifests, receipts):
    report = {"profile": profile, "checks": {}, "limitations": [
        "Installation evidence does not establish runtime functionality of every tool."]}
    checks = report["checks"]
    record = core.read_json(ctx.record_path(profile))
    report["preparation_record"] = record
    if not record:
        raise ValueError("No local preparation/import record")
    container = core.inspect_container(f"flagship-{profile}")
    if container is None:
        report["status"] = "unavailable"
        report["reason"] = "Prepared/imported image has no container; audit does not create one"
        return report
    core.ensure_owned(ctx, profile, container)
    core.ensure_configuration(record, container)
    if (not isinstance(record.get("workspace"), str)
            or Path(record["workspace"]).resolve() != ctx.workspace.resolve()):
        raise core.CommandError("Recorded container workspace differs from the requested shared workspace")
    identity = container["Id"]
    report["container"] = {"id": identity, "image": container["Image"], "state": container.get("State", {})}
    if not container.get("State", {}).get("Running"):
        report["status"], report["reason"] = "unavailable", "Container is not running; audit does not start it"
        return report
    binds = [mount["Destination"] for mount in container.get("Mounts", []) if mount.get("Type") == "bind"]
    options = {"profile": profile, "binds": binds, "meta": METAPACKAGES.get(profile), "installer": profile in CAST_EXPECTED}
    observed = observe(["podman", "exec", "--user", "0", "--workdir", "/", identity,
                        "/usr/bin/python3", "-I", "-c", PROBE, json.dumps(options)])
    report["observed"] = observed
    source = observed["inventory"]
    if source.get("exit_code") != 0:
        raise ValueError("Cannot read actual dpkg inventory")
    rows = inventory(source.pop("stdout"))
    report["package_inventory"] = rows
    report["package_counts"] = {"records": len(rows), "installed": sum(row["installed"] for row in rows)}
    checks["stable_package_database"] = {"status": "pass" if observed["package_database"]["stable"] else "fail"}
    for name in ("dpkg_audit", "dependencies"):
        item = observed[name]
        good = item.get("exit_code") == 0 and (name != "dpkg_audit" or not (item["stdout"].strip() or item["stderr"].strip()))
        checks[name] = {"status": "pass" if good else "fail"}
    release = observed["files"]["/etc/os-release"]
    if release["status"] == "present":
        report["release_identifiers"] = os_release(release["text"])
        checks["release_identifiers"] = {"status": "pass", "meaning": "Observed OS identifiers; Ubuntu alone does not identify a specialist release"}
    else:
        checks["release_identifiers"] = {"status": "unavailable"}
    if profile in METAPACKAGES:
        meta = METAPACKAGES[profile]
        present = [row for row in rows if row["package"] == meta and row["installed"]]
        checks["full_metapackage"] = {"status": "pass" if present else "fail", "package": meta, "installed": present}
        simulation = observed["metapackage_simulation"]
        pending = [line for line in simulation.get("stdout", "").splitlines() if line.startswith(("Inst ", "Remv ", "Conf "))]
        checks["metapackage_resolution"] = {"status": "pass" if simulation.get("exit_code") == 0 and not pending else "fail",
            "pending_actions": pending, "meaning": "Simulation against existing package lists; no update, download, or installation"}
    if profile not in ("caine", "tsurugi"):
        baseline = observed["files"][INVENTORY]
        if baseline["status"] == "present":
            expected = Counter((row["package"], row["version"]) for row in inventory(baseline["text"], True) if row["installed"])
            checks["build_inventory"] = compare_packages(expected, rows)
        else:
            checks["build_inventory"] = {"status": "unavailable", "reason": "No full-build package inventory"}
        recipe = files("flagship").joinpath("recipes", f"{profile}.Containerfile").read_bytes()
        digest = hashlib.sha256(recipe).hexdigest()
        checks["bundled_recipe"] = {"status": "pass" if record.get("recipe_sha256") == digest else "unavailable",
                                    "current_sha256": digest, "built_sha256": record.get("recipe_sha256")}
    if profile in CAST_EXPECTED:
        candidates = [(path, value) for path, value in observed["files"].items()
                      if path.endswith("/cast/state.yaml") and value["status"] == "present"]
        checks["upstream_installer"] = {"status": "unavailable", "reason": "No readable upstream Cast installation receipt"}
        for path, value in candidates:
            try:
                receipt = cast_state(value["text"], CAST_EXPECTED[profile])
            except ValueError as error:
                receipt = {"status": "unavailable", "reason": str(error)}
            receipt["path"] = path
            checks["upstream_installer"] = receipt
            if receipt["status"] == "pass":
                break
        results = observed["files"]["/var/cache/cast/installer/logs/results.yaml"]
        checks["installer_results"] = {"status": "pass" if results["status"] == "present" and results["bytes"] else "unavailable",
                                       "meaning": "Presence/hash of upstream YAML results; not parsed as a success assertion"}
    if profile in ("caine", "tsurugi"):
        checks["iso_manifest"] = {"status": "unavailable", "reason": "No publisher filesystem manifest supplied"}
        if profile in manifests:
            path = manifests[profile]
            data = path.read_bytes()
            checks["iso_manifest"] = dict(compare_packages(manifest(data.decode("utf-8")), rows, installed_only=False),
                path=str(path), sha256=hashlib.sha256(data).hexdigest(), provenance="Provided local manifest; publisher authentication not performed by this audit")
            checks["iso_manifest"]["residual_configuration_note"] = "ISO manifests may contain config-only packages; all dpkg status records are compared and installed counts are reported separately"
        checks["iso_conversion"] = {"status": "unavailable", "reason": "No conversion receipt supplied"}
        if profile in receipts:
            path = receipts[profile]
            data = path.read_bytes()
            receipt = json.loads(data)
            if not isinstance(receipt, dict):
                raise ValueError("ISO receipt must be an object")
            checks["iso_conversion"] = dict(iso_binding(profile, receipt, record, checks["iso_manifest"].get("sha256")),
                                             path=str(path), sha256=hashlib.sha256(data).hexdigest())
        report["limitations"].append("The package manifest does not enumerate all custom non-package files or establish forensic write-blocking behavior.")
    final, final_record = core.managed_container(ctx, profile)
    checks["stable_environment"] = {"status": "pass" if final["Id"] == identity and final_record == record
                                    and final.get("Mounts") == container.get("Mounts") else "fail"}
    statuses = [item["status"] for item in checks.values()]
    report["status"] = "fail" if "fail" in statuses else "unavailable" if "unavailable" in statuses else "pass"
    return report


def assignments(values):
    result = {}
    for value in values:
        profile, separator, path = value.partition("=")
        if not separator or profile not in ("caine", "tsurugi") or profile in result or not path:
            raise ValueError("Evidence must be unique caine=PATH or tsurugi=PATH assignments")
        result[profile] = Path(path).expanduser().resolve(strict=True)
        if not result[profile].is_file():
            raise ValueError("Evidence must be a regular file")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--manifest", action="append", default=[], metavar="PROFILE=PATH")
    parser.add_argument("--iso-receipt", action="append", default=[], metavar="PROFILE=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if sys.platform != "linux" or os.geteuid() == 0:
            raise ValueError("Run as the ordinary Linux user who owns the environments")
        manifests, receipts = assignments(args.manifest), assignments(args.iso_receipt)
        ctx = core.Context(args.state_dir.expanduser().resolve(strict=True), args.workspace.expanduser().resolve(strict=True))
        core.validate_paths(ctx)
        core.validate_backend_configuration()
        core.require_runtime()
        output = args.output.expanduser().absolute()
        output.parent.resolve(strict=True)
        if output.exists() or output.is_symlink():
            raise ValueError("Refusing to overwrite an existing audit report")
        report = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
                  "scope": "Installation evidence from seven real environments; no per-tool runtime acceptance",
                  "state_dir": str(ctx.state_dir), "workspace": str(ctx.workspace), "profiles": {}}
        for profile in PROFILES:
            try:
                report["profiles"][profile] = audit_profile(ctx, profile, manifests, receipts)
            except (core.CommandError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
                report["profiles"][profile] = {"profile": profile, "status": "unavailable", "reason": str(error)}
        report["passed"] = all(value["status"] == "pass" for value in report["profiles"].values())
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory(prefix="flagship-audit-", dir=output.parent) as temporary:
            private = Path(temporary) / "report.json"
            with private.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(private, output)
        print(f"{'PASS' if report['passed'] else 'INCOMPLETE'}: {output}", file=sys.stderr)
        return 0 if report["passed"] else 1
    except (core.CommandError, OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
