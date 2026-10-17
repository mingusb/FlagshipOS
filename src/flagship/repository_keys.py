"""Refresh Tsurugi's existing Tor archive key without widening APT trust."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import urlopen


FINGERPRINT = 'A3C4F0F979CAA22CDBA8F512EE8CBC9E886DDD89'
BASE = 'https://deb.torproject.org/torproject.org'
KEY_URL = BASE + '/' + FINGERPRINT + '.asc'


def download(url):
    with urlopen(url, timeout=90) as response:
        data = response.read(1024 * 1024 + 1)
    if not data or len(data) > 1024 * 1024:
        raise RuntimeError('Tor verification response has an unexpected size')
    return data


def fingerprint(path, gpg_home):
    result = subprocess.run(['gpg', '--batch', '--no-options', '--homedir', str(gpg_home),
                             '--with-colons', '--show-keys', str(path)], capture_output=True, text=True, check=True)
    primary, pending = [], False
    for line in result.stdout.splitlines():
        parts = line.split(':')
        if parts[0] == 'pub':
            pending = True
        elif parts[0] == 'fpr' and pending:
            primary.append(parts[9])
            pending = False
    if primary != [FINGERPRINT]:
        raise RuntimeError('Tor key file does not contain exactly the expected primary key')
    return primary[0]


def refresh_tor_keyring(root=Path('/')):
    source = root / 'etc/apt/sources.list.d/tor.list'
    keyring = root / 'usr/share/keyrings/deb.torproject.org-keyring.gpg'
    if not source.exists():
        return
    if source.is_symlink() or keyring.is_symlink() or not keyring.is_file():
        raise RuntimeError('Tor source/keyring path requires review')
    suites = set()
    for line in source.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'deb(?:-src)?\s+\[signed-by=/usr/share/keyrings/deb\.torproject\.org-keyring\.gpg\]\s+'
                             r'https://deb\.torproject\.org/torproject\.org/?\s+([a-z0-9-]+)\s+main\s*', line)
        if not match:
            raise RuntimeError('Tor source configuration differs from the verified release layout')
        suites.add(match[1])
    if not suites:
        return
    original = keyring.read_bytes()
    with tempfile.TemporaryDirectory(prefix='flagship-tor-key-') as temporary:
        temporary = Path(temporary)
        gpg_home = temporary / 'gnupg'
        gpg_home.mkdir(mode=0o700)
        fingerprint(keyring, gpg_home)
        armored = temporary / 'renewed.asc'
        armored.write_bytes(download(KEY_URL))
        fingerprint(armored, gpg_home)
        renewed = temporary / 'renewed.gpg'
        subprocess.run(['gpg', '--batch', '--no-options', '--homedir', str(gpg_home),
                        '--dearmor', '--output', str(renewed), str(armored)], check=True)
        releases = {}
        for suite in sorted(suites):
            release = temporary / (suite + '-InRelease')
            release.write_bytes(download(BASE + '/dists/' + suite + '/InRelease'))
            subprocess.run(['gpgv', '--homedir', str(gpg_home), '--keyring', str(renewed), str(release)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            releases[suite] = hashlib.sha256(release.read_bytes()).hexdigest()
        data = renewed.read_bytes()
        backup = keyring.with_name(keyring.name + '.flagship-original')
        receipt = keyring.with_name(keyring.name + '.flagship-refresh.json')
        if backup.is_symlink() or receipt.is_symlink():
            raise RuntimeError('Tor backup or receipt path is a symbolic link')
        if backup.exists():
            fingerprint(backup, gpg_home)
        if original != data:
            if not backup.exists():
                with backup.open('xb') as stream:
                    stream.write(original)
                backup.chmod(0o644)
            with tempfile.NamedTemporaryFile(dir=keyring.parent, prefix='.flagship-tor-', delete=False) as stream:
                staging = Path(stream.name)
                stream.write(data)
            try:
                staging.chmod(0o644)
                os.replace(staging, keyring)
            finally:
                staging.unlink(missing_ok=True)
        receipt.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(),
            'primary_fingerprint': FINGERPRINT, 'key_url': KEY_URL,
            'before_sha256': hashlib.sha256(original).hexdigest(), 'after_sha256': hashlib.sha256(data).hexdigest(),
            'authenticated_release_sha256': releases, 'sources_unchanged': True}, indent=2) + '\n')
        receipt.chmod(0o644)
    print('Flagship verified the renewed Tor archive key and signed repository metadata.')


if __name__ == '__main__':
    refresh_tor_keyring()
