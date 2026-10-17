"""Install a pinned NVIDIA compiler runtime when a collection has no NVRTC package."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen


VERSION = '12.4.127'
ARCHIVE_ROOT = 'cuda_nvrtc-linux-x86_64-' + VERSION + '-archive'
URL = 'https://developer.download.nvidia.com/compute/cuda/redist/cuda_nvrtc/linux-x86_64/' + ARCHIVE_ROOT + '.tar.xz'
SHA256 = 'b5e7a984fcf05d3123684d7926e595306d31fbf99f9b19e9a0d268a02fc75827'
SIZE = 34123316
# Hash and size are from NVIDIA's redistrib_12.4.1.json, verified 2026-10-17.


def verify_archive(archive):
    if archive.stat().st_size != SIZE:
        raise RuntimeError('NVIDIA NVRTC archive size differs from the pinned manifest')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != SHA256:
        raise RuntimeError('NVIDIA NVRTC checksum does not match the pinned manifest')


def install_runtime():
    parent = Path('/opt/flagship')
    destination = parent / ('nvrtc-' + VERSION)
    library = destination / 'lib/libnvrtc.so.12'
    target = Path('/usr/lib/x86_64-linux-gnu/libnvrtc.so')
    config = Path('/etc/ld.so.conf.d/01-flagship-nvrtc.conf')
    setting = str(destination / 'lib') + '\n'
    if parent.is_symlink() or destination.is_symlink() or config.is_symlink():
        raise RuntimeError('NVRTC installation path is an unexpected symbolic link')
    if target.exists() or target.is_symlink():
        if not target.is_symlink() or target.readlink() != library:
            raise RuntimeError('An unrelated NVRTC loader name already exists')
    if config.exists() and config.read_text() != setting:
        raise RuntimeError('An unrelated NVRTC loader configuration already exists')
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix='flagship-nvrtc-') as temporary:
            temporary = Path(temporary)
            archive = temporary / 'nvrtc.tar.xz'
            with urlopen(URL, timeout=90) as response, archive.open('xb') as stream:
                total = 0
                while data := response.read(1024 * 1024):
                    total += len(data)
                    if total > SIZE:
                        raise RuntimeError('NVIDIA NVRTC download exceeds the pinned size')
                    stream.write(data)
            verify_archive(archive)
            extracted = temporary / 'unpacked'
            extracted.mkdir()
            with tarfile.open(archive, 'r:xz') as source:
                members = source.getmembers()
                for member in members:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts or path.parts[0] != ARCHIVE_ROOT:
                        raise RuntimeError('Unexpected path in verified NVRTC archive')
                    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                        raise RuntimeError('Unsupported file type in NVRTC archive')
                source.extractall(extracted, members=members, filter='data')
            prepared = extracted / ARCHIVE_ROOT
            checksums = {str(path.relative_to(prepared)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in prepared.rglob('*') if path.is_file() and not path.is_symlink()}
            if 'LICENSE' not in checksums or 'lib/libnvrtc.so.' + VERSION not in checksums:
                raise RuntimeError('NVRTC runtime or its license is missing')
            (prepared / '.flagship-source.json').write_text(json.dumps({
                'url': URL, 'version': VERSION, 'archive_sha256': SHA256, 'archive_bytes': SIZE,
                'file_sha256': checksums, 'license': 'Upstream NVIDIA CUDA Toolkit license retained in LICENSE'}, indent=2) + '\n')
            parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.move(str(prepared), destination)
    receipt = json.loads((destination / '.flagship-source.json').read_text())
    if receipt.get('archive_sha256') != SHA256:
        raise RuntimeError('Existing NVRTC installation has different provenance')
    for name, digest in receipt['file_sha256'].items():
        path = destination / name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Existing NVRTC installation differs from its verified files')
    if not library.is_file() or not library.resolve().is_relative_to(destination.resolve()):
        raise RuntimeError('NVRTC library does not resolve inside its verified installation')
    if not config.exists():
        config.write_text(setting)
        config.chmod(0o644)
    if not target.is_symlink():
        target.symlink_to(library)
    subprocess.run(['ldconfig'], check=True)
    print('Flagship installed the verified NVIDIA NVRTC compiler runtime; its upstream license is retained.')


if __name__ == '__main__':
    install_runtime()
