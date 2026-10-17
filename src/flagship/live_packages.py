"""Repair the known missing CAINE package metadata using its maintainer's package."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request


PACKAGE = 'wasta-remastersys'
OLD_VERSION = '4.7.2~ubuntu22.04.1'
VERSION = '4.7.2~ubuntu24.04.1'
SIZE = 3340328
SHA256 = '5b0a4a164e45f27b077ab6b2373d383f8f0fe98059160326eb965c221723e170'
URL = ('https://ppa.launchpadcontent.net/wasta-linux/wasta-apps/ubuntu/pool/main/w/'
       'wasta-remastersys/wasta-remastersys_' + VERSION + '_all.deb')


def verify_package(data):
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('CAINE repair package differs from the authenticated maintainer release.')


def verify_plan(output):
    installs = [line.split()[1] for line in output.splitlines() if line.startswith('Inst ')]
    if installs != [PACKAGE] or any(line.startswith('Remv ') for line in output.splitlines()):
        raise RuntimeError('CAINE repair would change packages beyond wasta-remastersys.')


def repair():
    if os.geteuid() != 0:
        raise RuntimeError('The CAINE package repair must run inside the container as root.')
    info = Path('/var/lib/dpkg/info')
    controls = [info / (PACKAGE + suffix) for suffix in ('.list', '.md5sums')]
    if all(path.is_file() and not path.is_symlink() for path in controls):
        return
    if any(path.is_symlink() for path in controls):
        raise RuntimeError('Unexpected symbolic link in CAINE package metadata.')
    version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', PACKAGE], text=True)
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if version != OLD_VERSION or release.get('VERSION_ID', '').strip('"') != '24.04':
        raise RuntimeError('Missing CAINE package metadata does not match the verified repair case.')
    status = subprocess.check_output(['dpkg-query', '--status', PACKAGE], text=True)
    configs = {}
    in_configs = False
    for line in status.splitlines():
        if line == 'Conffiles:':
            in_configs = True
        elif not line.startswith(' '):
            in_configs = False
        elif in_configs:
            path = Path(line.split()[0])
            if path.is_file() and not path.is_symlink():
                configs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='flagship-caine-package-') as temporary:
        package = Path(temporary) / (PACKAGE + '.deb')
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(SIZE + 1)
        verify_package(data)
        package.write_bytes(data)
        # APT's _apt downloader must be able to read this already-verified file.
        Path(temporary).chmod(0o755)
        package.chmod(0o644)
        command = ['apt-get', '--no-remove', '--no-install-recommends',
                   '-o', 'Dpkg::Options::=--force-confold']
        environment = dict(os.environ, LC_ALL='C', DEBIAN_FRONTEND='noninteractive')
        plan = subprocess.check_output(command + ['--simulate', 'install', str(package)], env=environment, text=True)
        verify_plan(plan)
        record = Path('/var/lib/flagship/caine-package-repair')
        record.mkdir(mode=0o700, parents=True, exist_ok=True)
        if record.is_symlink() or record.stat().st_uid != 0:
            raise RuntimeError('Unexpected CAINE package repair record location.')
        before = record / 'original-package-status.txt'
        if before.exists() and before.read_text() != status:
            raise RuntimeError('Existing CAINE package repair record differs.')
        if not before.exists():
            before.write_text(status)
        subprocess.run(command + ['--yes', 'install', str(package)], env=environment, check=True)
    installed = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', PACKAGE], text=True)
    if installed != VERSION or not all(path.is_file() for path in controls):
        raise RuntimeError('CAINE package repair did not restore the package metadata.')
    for name, digest in configs.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('CAINE package repair changed an existing configuration file: ' + name)
    receipt = {'package': PACKAGE, 'previous_version': version, 'installed_version': installed,
               'url': URL, 'size': SIZE, 'sha256': SHA256, 'existing_config_sha256': configs,
               'configuration_preserved': True, 'plan': plan}
    (record / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Flagship repaired CAINE package metadata with the verified native Ubuntu 24.04 maintainer package.')


if __name__ == '__main__':
    repair()
