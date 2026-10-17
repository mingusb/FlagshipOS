"""Real shell/file checks for the WSL library bridge; no simulated GPU success."""

import os
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flagship import cli, gpu


@unittest.skipUnless(os.name == 'posix', 'requires POSIX symlinks and shell')
class GpuBridgeTests(unittest.TestCase):
    def fixture(self, root):
        host = root / 'host'
        (host / 'lib').mkdir(parents=True)
        (host / 'lib/libcuda.so.1').write_bytes(b'fixture, not a GPU driver')
        smi = host / 'lib/nvidia-smi'
        smi.write_text('#!/bin/sh\nexit 0\n')
        smi.chmod(0o755)
        (root / 'usr/lib').mkdir(parents=True)
        (root / 'etc/ld.so.conf.d').mkdir(parents=True)
        (root / 'bin').mkdir()
        cache = root / 'bin/ldconfig'
        cache.write_text('#!/bin/sh\nprintf cache-refreshed\n')
        cache.chmod(0o755)
        script = gpu.WSL_GPU_SCRIPT.replace('/run/host/usr/lib/wsl', str(host))
        script = script.replace('/usr/lib/wsl', str(root / 'usr/lib/wsl'))
        script = script.replace('/etc/ld.so.conf.d', str(root / 'etc/ld.so.conf.d'))
        script = script.replace('/usr/local/bin', str(root / 'usr/local/bin'))
        script = script.replace('/dev/dxg', '/dev/null')  # A real character device; no GPU claim.
        environment = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'])
        return script, environment

    def run_hook(self, script, environment):
        return subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True)

    def test_connects_existing_host_files_idempotently_without_copying(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script, environment = self.fixture(root)
            for _ in range(2):
                result = self.run_hook(script, environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('cache-refreshed', result.stdout)
            self.assertEqual((root / 'usr/lib/wsl').readlink(), root / 'host')
            self.assertEqual((root / 'usr/local/bin/nvidia-smi').readlink(), root / 'usr/lib/wsl/lib/nvidia-smi')
            self.assertEqual((root / 'host/lib/libcuda.so.1').read_bytes(), b'fixture, not a GPU driver')

    def test_foreign_destinations_fail_before_any_other_change(self):
        for conflict in ('directory', 'loader-link', 'loader-content', 'launcher'):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                script, environment = self.fixture(root)
                if conflict == 'directory':
                    (root / 'usr/lib/wsl').mkdir()
                elif conflict.startswith('loader'):
                    config = root / 'etc/ld.so.conf.d/00-flagship-wsl-gpu.conf'
                    if conflict == 'loader-link':
                        config.symlink_to(root / 'unrelated')
                    else:
                        config.write_text('unrelated configuration')
                else:
                    (root / 'usr/local/bin').mkdir(parents=True)
                    (root / 'usr/local/bin/nvidia-smi').write_text('unrelated launcher')
                result = self.run_hook(script, environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'usr/lib/wsl').is_symlink())
                self.assertNotIn('cache-refreshed', result.stdout)

    def test_missing_driver_fails_without_creating_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script, environment = self.fixture(root)
            (root / 'host/lib/libcuda.so.1').unlink()
            result = self.run_hook(script, environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'usr/lib/wsl').exists())

    def test_hook_survives_distrobox_quoting(self):
        with patch.object(gpu, 'WSL_GPU_SCRIPT', "printf '%s\\n' 'GPU hook parsed'\n"):
            hook = gpu.setup_hook()
        transport = 'printf "%s\\n" "' + hook + '"'
        result = subprocess.run(['/bin/sh', '-c', 'eval "$1"', 'fixture', transport], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, hook + '\n')
        result = subprocess.run(['/bin/sh', '-c', result.stdout], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, 'GPU hook parsed\n')

    def test_creation_adds_only_the_wsl_hook_when_host_support_is_present(self):
        ctx = cli.Context(Path('/private-state'), Path('/shared-workspace'))
        with patch.object(gpu, 'host_available', return_value=False):
            self.assertNotIn('--init-hooks', cli.create_argv(ctx, 'kali', 'image', 'instance'))
        with patch.object(gpu, 'host_available', return_value=True):
            arguments = cli.create_argv(ctx, 'caine', 'image', 'instance')
        self.assertIn('--pre-init-hooks', arguments)
        self.assertEqual(arguments[arguments.index('--init-hooks') + 1], gpu.setup_hook(with_runtime=True))


@unittest.skipUnless(os.name == 'posix', 'requires POSIX symlinks and shell')
class NvrtcRuntimeTests(unittest.TestCase):
    def fixture(self, root):
        directory = root / 'usr/lib/x86_64-linux-gnu'
        directory.mkdir(parents=True)
        (root / 'lib').symlink_to(root / 'usr/lib')
        binary = root / 'bin'
        binary.mkdir()
        # Keep these fixtures off the real package manager and GPU libraries.
        for name, body in {
            'hashcat': 'exit 0',
            'ldconfig': 'if [ -f "' + str(directory / 'libnvrtc.so.12') + '" ]; then printf "%s\\n" "libnvrtc.so.12 (libc6,x86-64) => ' + str(root / 'lib/x86_64-linux-gnu/libnvrtc.so.12') + '"; fi',
            'apt-cache': 'printf "%s\\n" libnvrtc12 libnvrtc-builtins12.0 libnvrtc12-dev',
            'apt-get': 'printf "%s\\n" "$*" >> "' + str(root / 'apt.log') + '"\nif [ "$1" = install ]; then printf runtime-fixture > "' + str(directory / 'libnvrtc.so.12') + '"; fi',
        }.items():
            path = binary / name
            path.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
            path.chmod(0o755)
        # Resolve /lib aliases to the canonical /usr path before accepting them.
        script = gpu.HASHCAT_RUNTIME_SCRIPT.replace('/usr/lib/x86_64-linux-gnu', str(directory))
        environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'])
        return directory, script, environment

    def test_existing_runtime_uses_canonical_path_without_apt_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, script, environment = self.fixture(root)
            library = directory / 'libnvrtc.so.12'
            library.write_bytes(b'runtime-fixture')
            for _ in range(2):
                result = subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((directory / 'libnvrtc.so').readlink(), library)
            self.assertFalse((root / 'apt.log').exists())

    def test_missing_runtime_installs_only_a_runtime_without_removals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, script, environment = self.fixture(root)
            result = subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'apt.log').read_text().splitlines(), [
                'update', 'install --yes --no-remove --no-install-recommends libnvrtc12'])
            self.assertEqual((directory / 'libnvrtc.so').read_bytes(), b'runtime-fixture')

    def test_broken_preexisting_link_is_preserved_without_apt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, script, environment = self.fixture(root)
            target = directory / 'libnvrtc.so'
            target.symlink_to(directory / 'missing-library')
            result = subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.readlink(), directory / 'missing-library')
            self.assertFalse((root / 'apt.log').exists())

    def test_failed_package_install_does_not_create_a_loader_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, script, environment = self.fixture(root)
            (root / 'bin/apt-get').write_text('#!/bin/sh\nexit 42\n')
            result = subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 42)
            self.assertFalse((directory / 'libnvrtc.so').is_symlink())


class GpuCommandTests(unittest.TestCase):
    def test_dry_run_never_queries_or_mutates_a_container(self):
        with tempfile.TemporaryDirectory() as temporary:
            ctx = cli.Context(Path(temporary) / 'state', Path(temporary) / 'workspace', True)
            output = io.StringIO()
            with patch.object(cli, 'require_runtime', side_effect=AssertionError('runtime called')), contextlib.redirect_stdout(output):
                self.assertEqual(gpu.main(ctx, 'parrot', setup=True, as_json=True), 0)
            self.assertTrue(json.loads(output.getvalue())['setup'])
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
