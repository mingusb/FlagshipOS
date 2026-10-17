"""Exercise startup compatibility with real shell parsing and temporary files."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flagship import cli, integration


COPY_FIXTURE = (integration.SKEL_START + b'\tfor skel_file in ${skel_files}; do\n'
                + b'\t\tcp "${skel_file}" "${container_user_home}/"' + integration.SKEL_END)
INIT = b'''#!/bin/sh
version="1.8.2.5"
if command -v rpm; then echo rpm-exceptions; else echo deb-exceptions; fi
if command -v rpm; then echo apt-rpm; else echo apt-deb; fi
''' + b'if [ -n "${DISTROBOX_HOST_HOME-}" ]; then\n' + COPY_FIXTURE + b'\nfi\n'


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        expected = patch.object(integration, 'SKEL_COPY_SHA256', hashlib.sha256(COPY_FIXTURE).hexdigest())
        expected.start()
        self.addCleanup(expected.stop)

    def test_unknown_runtime_layout_is_rejected(self):
        for source in (b"", INIT.replace(b'1.8.2.5', b'2.0.0'), INIT.replace(integration.RPM_PROBE, b'false', 1),
                       INIT.replace(COPY_FIXTURE, b':'), INIT.replace(b'\t\tcp ', b'\t\tcp -f ')):
            with self.subTest(source=source), self.assertRaises(cli.CommandError):
                integration.patch_init(source)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX filenames and ownership')
    def test_skeleton_copy_preserves_literal_names_and_existing_user_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skeleton, home = root / 'skel', root / 'managed home'
            skeleton.mkdir()
            home.mkdir()
            names = ['Disk utility.desktop', 'literal [*] ;$().desktop', 'line\nbreak.desktop']
            for name in names + ['existing', 'linked']:
                (skeleton / name).write_text('original ' + name)
            (home / 'existing').write_text('user changes')
            (home / 'linked').symlink_to('existing')
            script = integration.patch_init(INIT).replace(b'/etc/skel', str(skeleton).encode())
            environment = dict(os.environ, DISTROBOX_HOST_HOME='present', container_user_home=str(home),
                               container_user_uid=str(os.getuid()), container_user_gid=str(os.getgid()))
            for _ in range(2):
                result = subprocess.run(['/bin/sh'], input=script.decode(), env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in names:
                self.assertEqual((home / name).read_text(), 'original ' + name)
            self.assertEqual((home / 'existing').read_text(), 'user changes')
            self.assertEqual((home / 'linked').readlink(), Path('existing'))

    @unittest.skipUnless(os.name == "posix", "requires POSIX executables")
    def test_real_shell_prefers_debian_without_hiding_rpm(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ('rpm', 'dpkg-query'):
                path = directory / name
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            script = directory / 'init'
            script.write_bytes(integration.patch_init(INIT))
            environment = dict(os.environ, PATH=str(directory))
            result = subprocess.run(['/bin/sh', str(script)], env=environment, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), ['deb-exceptions', 'apt-deb'])
            self.assertTrue(os.access(directory / 'rpm', os.X_OK))
            (directory / 'dpkg-query').unlink()
            result = subprocess.run(['/bin/sh', str(script)], env=environment, capture_output=True, text=True, check=True)
            self.assertIn('rpm-exceptions', result.stdout)
            self.assertIn('apt-rpm', result.stdout)

    @unittest.skipUnless(os.name == "posix", "requires POSIX file ownership")
    def test_private_runtime_is_reused_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed, state = root / 'installed', root / 'state'
            installed.mkdir()
            state.mkdir(mode=0o700)
            for name in ('distrobox', 'distrobox-create', 'distrobox-init', 'distrobox-export',
                         'distrobox-generate-entry', 'distrobox-host-exec'):
                (installed / name).write_bytes(INIT if name == 'distrobox-init' else b'#!/bin/sh\nexit 0\n')
            ctx = cli.Context(state, root / 'workspace')
            with patch.object(integration.shutil, 'which', return_value=str(installed / 'distrobox')):
                first = Path(integration.distrobox_launcher(ctx))
                self.assertEqual(first, Path(integration.distrobox_launcher(ctx)))
                self.assertEqual((installed / 'distrobox-init').read_bytes(), INIT)
                self.assertEqual((first.parent / 'distrobox-init').read_bytes(), integration.patch_init(INIT))
                first.write_text('changed')
                with self.assertRaisesRegex(cli.CommandError, 'runtime changed'):
                    integration.distrobox_launcher(ctx)
                shutil.rmtree(state / 'runtime')
                (state / 'runtime').symlink_to(installed, target_is_directory=True)
                with self.assertRaisesRegex(cli.CommandError, 'symbolic link'):
                    integration.distrobox_launcher(ctx)

    def run_media_fixture(self, root):
        script = integration.MEDIA_SOURCE_SCRIPT.replace('/etc/apt', root.as_posix())
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(script, '<media-source-fixture>', 'exec'), {})

    def test_media_sources_are_backed_up_and_network_sources_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extra = root / 'sources.list.d'
            extra.mkdir()
            original = b'deb cdrom:[CAINE 24.04]/ dists/\ndeb https://archive.ubuntu.com/ubuntu noble main\n'
            listing = root / 'sources.list'
            listing.write_bytes(original)
            deb822 = extra / 'media.sources'
            deb822.write_text('Types: deb\nURIs: cdrom:[CAINE]/\nSuites: noble\n\nTypes: deb\nURIs: https://archive.ubuntu.com/ubuntu\nSuites: noble\n')
            self.run_media_fixture(root)
            self.assertEqual(listing.with_name(listing.name + '.flagship-before-media-disable').read_bytes(), original)
            self.assertIn('deb https://archive.ubuntu.com/ubuntu noble main\n', listing.read_text())
            self.assertTrue(listing.read_text().startswith('# Flagship disabled offline media: deb cdrom:'))
            self.assertEqual(deb822.read_text().count('Enabled: no'), 1)
            snapshot = {path.name: path.read_bytes() for path in root.rglob('*') if path.is_file()}
            self.run_media_fixture(root)
            self.assertEqual(snapshot, {path.name: path.read_bytes() for path in root.rglob('*') if path.is_file()})

    def test_conflicting_backup_and_mixed_media_sources_fail_before_edit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extra = root / 'sources.list.d'
            extra.mkdir()
            listing = root / 'sources.list'
            original = b'deb cdrom:[CAINE]/ dists/\n'
            listing.write_bytes(original)
            backup = listing.with_name(listing.name + '.flagship-before-media-disable')
            backup.write_text('different original')
            with self.assertRaisesRegex(RuntimeError, 'backup differs'):
                self.run_media_fixture(root)
            self.assertEqual(listing.read_bytes(), original)
            listing.unlink()
            (extra / 'mixed.sources').write_text('Types: deb\nURIs: cdrom:[CAINE]/ https://example.invalid/ubuntu\nSuites: noble\n')
            with self.assertRaisesRegex(RuntimeError, 'Mixed media/network'):
                self.run_media_fixture(root)

    @unittest.skipUnless(os.name == "posix", "requires POSIX shell parsing")
    def test_live_release_rebuilds_missing_dictionary_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'cache'
            binary = root / 'bin'
            binary.mkdir()
            updater = binary / 'update-cracklib'
            updater.write_text('#!/bin/sh\nprintf dictionary > "' + str(cache / 'cracklib_dict.pwd')
                               + '"\nprintf updated\\n\n')
            updater.chmod(0o755)
            script = integration.CRACKLIB_CACHE_SCRIPT.replace('/var/cache/cracklib', str(cache))
            environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'])
            first = subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True, check=True)
            self.assertIn('updated', first.stdout)
            second = subprocess.run(['/bin/sh', '-c', script], env=environment, capture_output=True, text=True, check=True)
            self.assertEqual(second.stdout, '')
            self.assertEqual((cache / 'cracklib_dict.pwd').read_text(), 'dictionary')

    @unittest.skipUnless(os.name == "posix", "requires POSIX shell parsing")
    def test_hook_survives_distrobox_double_quoted_shell_layer(self):
        with patch.object(integration, 'MEDIA_SOURCE_SCRIPT', "print('fixture hook ran')\n"):
            hook = integration.media_source_hook()
        transport = 'printf "%s\\n" "' + hook + '"'
        result = subprocess.run(['/bin/sh', '-c', 'eval "$1"', 'fixture', transport],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, hook + '\n')
        result = subprocess.run(['/bin/sh', '-c', result.stdout], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, 'fixture hook ran\n')


if __name__ == '__main__':
    unittest.main()
