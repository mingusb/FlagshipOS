"""Container startup adaptations for complete Debian-family installations."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from . import cli as core


RPM_PROBE = b"if command -v rpm; then"
DEBIAN_FIRST_PROBE = b"if ! command -v dpkg-query >/dev/null 2>&1 && command -v rpm; then"

# Executed inside imported live-release containers, before Distrobox runs APT.
# Keep a byte-for-byte backup; network repositories and installed packages stay intact.
MEDIA_SOURCE_SCRIPT = r'''
from pathlib import Path
import re
paths = [Path('/etc/apt/sources.list')]
paths += sorted(Path('/etc/apt/sources.list.d').glob('*.list'))
paths += sorted(Path('/etc/apt/sources.list.d').glob('*.sources'))
for path in paths:
    if not path.is_file():
        continue
    original = path.read_bytes()
    text = original.decode('utf-8')
    if path.suffix == '.sources':
        parts = re.split(r'(\n[ \t]*\n)', text)
        for index in range(0, len(parts), 2):
            if re.search(r'(?mi)^URIs:[ \t]*cdrom:', parts[index]):
                if re.search(r'https?://', parts[index]):
                    raise RuntimeError('Mixed media/network source requires review: ' + str(path))
                if re.search(r'(?mi)^Enabled:', parts[index]):
                    parts[index] = re.sub(r'(?mi)^Enabled:.*$', 'Enabled: no', parts[index])
                else:
                    parts[index] = 'Enabled: no\n' + parts[index]
        updated = ''.join(parts)
    else:
        updated = re.sub(r'(?m)^([ \t]*deb(?:-src)?[ \t]+(?:\[[^\]\n]*\][ \t]+)?cdrom:.*)$',
                         r'# Flagship disabled offline media: \1', text)
    if updated != text:
        backup = path.with_name(path.name + '.flagship-before-media-disable')
        if backup.exists() and backup.read_bytes() != original:
            raise RuntimeError('Existing media-source backup differs: ' + str(backup))
        if not backup.exists():
            with backup.open('xb') as output:
                output.write(original)
        path.write_bytes(updated.encode('utf-8'))
        print('Flagship disabled unavailable installation media in ' + str(path))
'''


def media_source_hook():
    # Distrobox puts this inside double quotes in a second shell parse. Encode
    # the fixed program so quotes, dollars and newlines cannot escape that layer.
    payload = base64.b64encode(MEDIA_SOURCE_SCRIPT.encode()).decode("ascii")
    return "printf %s " + payload + " | base64 --decode | python3"


def patch_init(source):
    """Prefer the real Debian database when an analysis toolkit includes rpm."""
    if not re.search(rb'^version="1\.8\.2\.5"$', source, re.MULTILINE) or source.count(RPM_PROBE) != 2:
        raise core.CommandError("Flagship's full-collection startup currently requires Distrobox 1.8.2.5 with its known package-manager detection layout.")
    return source.replace(RPM_PROBE, DEBIAN_FIRST_PROBE)


def private_directory(path):
    if path.is_symlink():
        raise core.CommandError(f"Compatibility directory must not be a symbolic link: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise core.CommandError(f"Compatibility directory must belong to you and have mode 0700: {path}")


def distrobox_launcher(ctx):
    """Keep an immutable private copy; never edit the host's Distrobox package.

    The copied upstream programs retain their GPL-3.0 notices. Flagship's MIT
    license covers this adapter, not those separately installed programs.
    """
    installed = shutil.which("distrobox")
    if not installed:
        raise core.CommandError("Distrobox is required before creating an environment.")
    directory = Path(installed).resolve().parent
    programs = {path.name: path.read_bytes() for path in sorted(directory.glob("distrobox*"))
                if re.fullmatch(r"distrobox(?:-[a-z-]+)?", path.name) and path.is_file()}
    required = {"distrobox", "distrobox-create", "distrobox-init", "distrobox-export",
                "distrobox-generate-entry", "distrobox-host-exec"}
    if not required.issubset(programs):
        raise core.CommandError("The installed Distrobox script distribution is incomplete.")
    original_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in programs.items()}
    programs["distrobox-init"] = patch_init(programs["distrobox-init"])
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in programs.items()}
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    parent = ctx.state_dir / "runtime"
    private_directory(parent)
    destination = parent / ("distrobox-" + identity)
    if not destination.exists() and not destination.is_symlink():
        with tempfile.TemporaryDirectory(prefix=".distrobox-", dir=parent) as temporary:
            temporary = Path(temporary)
            for name, data in programs.items():
                path = temporary / name
                path.write_bytes(data)
                path.chmod(0o755)
            core.atomic_json(temporary / "provenance.json", {
                "upstream_version": "1.8.2.5", "upstream_directory": str(directory),
                "original_sha256": original_hashes, "runtime_sha256": hashes,
                "adaptation": "Prefer dpkg-query over rpm for the two APT package-manager branches",
                "upstream_license": "GPL-3.0-only; original file notices retained"})
            # State lock serializes creation; the content-addressed directory is retained for mounts.
            os.rename(temporary, destination)
    private_directory(destination)
    for name, digest in hashes.items():
        path = destination / name
        if (path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid()
                or stat.S_IMODE(path.stat().st_mode) != 0o755
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise core.CommandError(f"Private Distrobox runtime changed: {path}")
    return str(destination / "distrobox")
