"""Container startup adaptations for complete Debian-family installations."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import tempfile

from . import cli as core


RPM_PROBE = b"if command -v rpm; then"
DEBIAN_FIRST_PROBE = b"if ! command -v dpkg-query >/dev/null 2>&1 && command -v rpm; then"

# Live releases can omit /var/cache while retaining PAM's dictionary policy.
# Rebuild the installed dictionary rather than disabling the password policy.
CRACKLIB_CACHE_SCRIPT = r'''
set -eu
if command -v update-cracklib >/dev/null 2>&1 && [ ! -s /var/cache/cracklib/cracklib_dict.pwd ]; then
    mkdir -p /var/cache/cracklib
    update-cracklib
    test -s /var/cache/cracklib/cracklib_dict.pwd
fi
'''

# Some live images create their shadow databases only during a normal boot.
# The standard converters preserve account identities and existing password data.
ACCOUNT_DATABASE_SCRIPT = r'''
set -eu
if [ ! -e /etc/shadow ]; then
    test ! -L /etc/shadow
    pwconv
    test -s /etc/shadow
fi
if [ ! -e /etc/gshadow ]; then
    test ! -L /etc/gshadow
    grpconv
    test -s /etc/gshadow
fi
'''

HOME_DIRECTORY_SCRIPT = r'''
set -eu
fail() { printf 'Flagship home: %s\n' "$1" >&2; exit 1; }
[ ! -L "$home" ] && [ -d "$home" ] && [ "$uid" -gt 0 ] && [ "$gid" -ge 0 ] || fail 'Unexpected managed home or user identity.'
for relative in .config .cache .local .local/share .local/state; do
    path=$home/$relative
    [ ! -L "$path" ] || fail 'Application directory is a symbolic link.'
    if [ -e "$path" ]; then
        [ -d "$path" ] || fail 'Application path is not a directory.'
        owner=$(stat -c %u "$path")
        [ "$owner" = 0 ] || [ "$owner" = "$uid" ] || fail 'Application directory belongs to another user.'
    fi
done
for relative in .config .cache .local .local/share .local/state; do
    path=$home/$relative
    mkdir -p -m 0700 "$path"
    chown --no-dereference "$uid:$gid" "$path"
done
printf '%s\n' 'Flagship application directories belong to the mapped user.'
'''

# Tsurugi enables hundreds of locales. Its normal locales post-install script
# explicitly accepts locales-all to retain those languages without recompiling
# every locale during container setup.
PRECOMPILED_LOCALES_SCRIPT = r'''
set -eu
if [ "$(dpkg-query -W -f='${db:Status-Status}' locales-all 2>/dev/null || :)" != installed ]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-remove --no-install-recommends locales-all
fi
test "$(dpkg-query -W -f='${db:Status-Status}' locales-all)" = installed
printf '%s\n' 'Flagship retained all supported languages using distribution-provided precompiled locales.'
'''

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


def home_directory_hook(home, uid, gid):
    script = 'home=' + shlex.quote(str(home)) + '\nuid=' + str(int(uid)) + '\ngid=' + str(int(gid)) + '\n' + HOME_DIRECTORY_SCRIPT
    payload = base64.b64encode(script.encode()).decode('ascii')
    return 'printf %s ' + payload + ' | base64 --decode | sh'


def live_release_hook(profile=None):
    payload = base64.b64encode((ACCOUNT_DATABASE_SCRIPT + CRACKLIB_CACHE_SCRIPT).encode()).decode("ascii")
    hook = media_source_hook() + " && printf %s " + payload + " | base64 --decode | sh"
    if profile == 'caine':
        from . import live_packages
        payload = base64.b64encode(Path(live_packages.__file__).read_bytes()).decode('ascii')
        hook += ' && printf %s ' + payload + ' | base64 --decode | python3'
    if profile == 'tsurugi':
        from . import repository_keys
        payload = base64.b64encode(Path(repository_keys.__file__).read_bytes()).decode('ascii')
        hook += ' && printf %s ' + payload + ' | base64 --decode | python3'
        payload = base64.b64encode(PRECOMPILED_LOCALES_SCRIPT.encode()).decode('ascii')
        hook += ' && printf %s ' + payload + ' | base64 --decode | sh'
    return hook


SKEL_START = b'\tskel_files="$(find /etc/skel/ -type f || :)"\n'
SKEL_END = b'\n\tdone'
# Bind the adaptation to the installed upstream block without vendoring it.
SKEL_COPY_SHA256 = '2ccfaf1f5d672bb274f07b21baec1741dc7cea573f52eed41428cf4594742027'

# find passes each filename as an argument, preserving spaces, glob characters
# and newlines. Existing files and links retain upstream's no-overwrite behavior.
SKEL_COPY_FIXED = b'''\tfind /etc/skel/ -type f -exec sh -eu -c '
\t\tuid=$1; gid=$2; home=$3; shift 3
\t\tfor source do
\t\t\trelative=${source#/etc/skel/}
\t\t\ttarget=$home/$relative
\t\t\tparent=${target%/*}
\t\t\tif [ ! -d "$parent" ]; then
\t\t\t\tmkdir -p -- "$parent"
\t\t\t\tchown "$uid:$gid" "$parent"
\t\t\tfi
\t\t\tif [ ! -f "$target" ] && [ ! -L "$target" ]; then
\t\t\t\tcp -- "$source" "$target"
\t\t\t\tchown "$uid:$gid" "$target"
\t\t\tfi
\t\tdone
\t' flagship-skel "$container_user_uid" "$container_user_gid" "$container_user_home" {} +'''


def skeleton_copy_block(source):
    if source.count(SKEL_START) != 1:
        raise core.CommandError('Distrobox skeleton-copy layout is not recognized.')
    start = source.index(SKEL_START)
    end = source.find(SKEL_END, start)
    block = source[start:end + len(SKEL_END)] if end >= 0 else b''
    if hashlib.sha256(block).hexdigest() != SKEL_COPY_SHA256:
        raise core.CommandError('Distrobox skeleton-copy block differs from the verified upstream version.')
    return block


def patch_init(source):
    """Correct the known Debian-detection and skeleton-copy startup branches."""
    if (not re.search(rb'^version="1\.8\.2\.5"$', source, re.MULTILINE)
            or source.count(RPM_PROBE) != 2):
        raise core.CommandError("Flagship's full-collection startup currently requires Distrobox 1.8.2.5 with its known package-manager and skeleton-copy layout.")
    block = skeleton_copy_block(source)
    return source.replace(RPM_PROBE, DEBIAN_FIRST_PROBE).replace(block, SKEL_COPY_FIXED, 1)


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
                "adaptation": "Prefer dpkg-query over rpm for the two APT branches; preserve skeleton filenames as find-exec arguments",
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
