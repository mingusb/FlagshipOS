"""Guard real startup paths and the boundaries of repository/runtime trust."""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flagship import gpu, gpu_nvrtc, integration, repository_keys


@unittest.skipUnless(os.name == 'posix', 'requires POSIX shell and file ownership')
class HomeRepairTests(unittest.TestCase):
    def test_ordinary_user_directories_are_writable_without_changing_nested_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / '.config'
            existing.mkdir(mode=0o755)
            (existing / 'application.conf').write_text('preserved')
            hook = integration.home_directory_hook(root, os.getuid(), os.getgid())
            for _ in range(2):
                result = subprocess.run(['/bin/sh', '-c', hook], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((existing / 'application.conf').read_text(), 'preserved')
            self.assertEqual(existing.stat().st_mode & 0o777, 0o755)
            (root / '.local/share/new-application').mkdir()

    def test_symlink_conflict_fails_before_any_directory_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, outside = root / 'home', root / 'outside'
            home.mkdir()
            outside.mkdir()
            (home / '.local').symlink_to(outside)
            hook = integration.home_directory_hook(home, os.getuid(), os.getgid())
            result = subprocess.run(['/bin/sh', '-c', hook], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((home / '.config').exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_shadow_repair_retains_existing_databases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shadow, gshadow = root / 'shadow', root / 'gshadow'
            shadow.write_bytes(b'existing private database')
            gshadow.write_bytes(b'existing group database')
            script = integration.ACCOUNT_DATABASE_SCRIPT.replace('/etc/shadow', str(shadow)).replace('/etc/gshadow', str(gshadow))
            result = subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(shadow.read_bytes(), b'existing private database')
            self.assertEqual(gshadow.read_bytes(), b'existing group database')

    def test_vendor_fallback_is_limited_to_missing_runtime_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            vendor = Path(temporary) / 'fixture.py'
            vendor.write_text("print('vendor-fixture')\n")
            for code in (0, 42, 77):
                with self.subTest(code=code), patch.object(gpu, 'WSL_GPU_SCRIPT', 'exit 0\n'), \
                        patch.object(gpu, 'HASHCAT_RUNTIME_SCRIPT', 'exit ' + str(code) + '\n'), \
                        patch.object(gpu_nvrtc, '__file__', str(vendor)):
                    result = subprocess.run(['/bin/sh', '-c', gpu.setup_hook(with_runtime=True)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 42 if code == 42 else 0, result.stderr)
                self.assertEqual('vendor-fixture' in result.stdout, code == 77)


class TrustBoundaryTests(unittest.TestCase):
    def test_extra_primary_keys_are_rejected(self):
        output = ('pub:-:2048:1:key::::::::\nfpr:::::::::' + repository_keys.FINGERPRINT + ':\n'
                  + 'pub:-:2048:1:another::::::::\nfpr:::::::::' + 'B' * 40 + ':\n')
        with patch.object(repository_keys.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            with self.assertRaisesRegex(RuntimeError, 'exactly the expected'):
                repository_keys.fingerprint(Path('fixture'), Path('unused-home'))

    def test_unexpected_source_layout_is_preserved_without_fetching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'etc/apt/sources.list.d/tor.list'
            source.parent.mkdir(parents=True)
            source.write_text('deb [trusted=yes] https://deb.torproject.org/torproject.org noble main\n')
            key = root / 'usr/share/keyrings/deb.torproject.org-keyring.gpg'
            key.parent.mkdir(parents=True)
            key.write_bytes(b'original fixture')
            with patch.object(repository_keys, 'download', side_effect=AssertionError('network called')):
                with self.assertRaisesRegex(RuntimeError, 'configuration differs'):
                    repository_keys.refresh_tor_keyring(root)
            self.assertEqual(key.read_bytes(), b'original fixture')
            self.assertIn('trusted=yes', source.read_text())

    def test_vendor_archive_requires_both_size_and_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'fixture.tar.xz'
            archive.write_bytes(b'fixture')
            digest = hashlib.sha256(b'fixture').hexdigest()
            with patch.object(gpu_nvrtc, 'SIZE', 7), patch.object(gpu_nvrtc, 'SHA256', digest):
                gpu_nvrtc.verify_archive(archive)
                archive.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    gpu_nvrtc.verify_archive(archive)
                archive.write_bytes(b'')
                with self.assertRaisesRegex(RuntimeError, 'size'):
                    gpu_nvrtc.verify_archive(archive)


if __name__ == '__main__':
    unittest.main()
