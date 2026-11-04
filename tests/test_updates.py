import errno
import io
import shutil
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from travelrouter.updates import MIRROR, Updates, package_architecture, package_update, repository_location, verify_update


class UpdateTests(unittest.TestCase):
    def test_package_updates_use_native_apk_architecture(self):
        for architecture in ('x86_64', 'aarch64'):
            with self.subTest(architecture=architecture), patch('travelrouter.updates.command', return_value=architecture + '\n'):
                self.assertEqual(package_architecture(), architecture)
                location = repository_location(f'{MIRROR}/main/{architecture}/python3-3.14.10-r1.apk', architecture)
                self.assertEqual(location, ('main', 'python3-3.14.10-r1.apk'))

    def test_wrong_architecture_and_unexpected_package_sources_are_rejected(self):
        for url in (f'{MIRROR}/main/aarch64/python3.apk',
                    f'{MIRROR}/main/x86_64/../python3.apk',
                    f'{MIRROR}/main/x86_64/python3.apk?redirect=1',
                    'https://untrusted.example/main/x86_64/python3.apk'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                repository_location(url, 'x86_64')
        with patch('travelrouter.updates.command', return_value='armv7\n'), self.assertRaises(ValueError):
            package_architecture()

    def test_staged_version_cannot_be_downgraded_before_reboot(self):
        class ForbiddenLock:
            def __enter__(self):
                raise AssertionError('Update must be rejected before filesystem mutation')

            def __exit__(self, *args):
                return False

        updates = Updates(SimpleNamespace(lock=ForbiddenLock()))
        updates.status['staged_version'] = '0.3.0'
        update = package_update({'travelrouter/__init__.py': b'valid',
                                 'travelrouter/__main__.py': b'valid'}, '0.2.0', self.key)
        public = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with patch('travelrouter.updates.Path.read_bytes', return_value=public), self.assertRaises(ValueError):
            updates.install_application(update)

    def setUp(self):
        self.key = Ed25519PrivateKey.generate()

    def test_signed_update_validates_and_wrong_signer_is_rejected(self):
        update = package_update({'travelrouter/__init__.py': b'__version__ = "0.2.0"\n',
                                 'travelrouter/__main__.py': b'# entry point\n'}, '0.2.0', self.key)
        manifest, files = verify_update(update, self.key.public_key(), '0.1.0')
        self.assertEqual(manifest['version'], '0.2.0')
        self.assertIn('travelrouter/__init__.py', files)
        with self.assertRaises(ValueError):
            verify_update(update, Ed25519PrivateKey.generate().public_key(), '0.1.0')

    def test_unsigned_modified_or_downgrade_update_is_rejected(self):
        update = package_update({'travelrouter/__init__.py': b'valid'}, '0.2.0', self.key)
        with self.assertRaises(ValueError):
            verify_update(update, self.key.public_key(), '0.2.0')
        update['manifest']['version'] = '1.0.0'
        with self.assertRaises(ValueError):
            verify_update(update, self.key.public_key(), '0.1.0')

    def test_even_signed_archive_cannot_escape_software_directory(self):
        update = package_update({'../../etc/passwd': b'evil'}, '0.2.0', self.key)
        with self.assertRaises(ValueError):
            verify_update(update, self.key.public_key(), '0.1.0')


class PackageStagingTests(unittest.TestCase):
    def exercise_staging(self, cleanup_fails=False, persist_fails=False):
        with tempfile.TemporaryDirectory() as temporary:
            medium = Path(temporary) / 'boot'
            medium.mkdir()
            (medium / 'repositories').mkdir()
            (medium / 'repositories/old-index').write_text('previous generation')
            world = Path(temporary) / 'world'
            world.write_text('python3\n')
            keys = Path(temporary) / 'keys'
            keys.mkdir()
            (keys / 'test.pub').write_text('fixture trust key')
            events = []
            state = {'readonly': False}
            original_rmtree, original_copytree = shutil.rmtree, shutil.copytree

            def invoke(arguments, **kwargs):
                if '--print-arch' in arguments:
                    return 'x86_64\n'
                if arguments[0] == '/bin/mount':
                    state['readonly'] = arguments[2] == 'remount,ro'
                    events.append(arguments[2])
                elif 'list' in arguments:
                    return 'python3-3.14.10-r1\n'
                elif 'fetch' in arguments:
                    if '--url' in arguments:
                        return MIRROR + '/main/x86_64/python3-3.14.10-r1.apk\n'
                    output = Path(arguments[arguments.index('--output') + 1])
                    (output / 'python3-3.14.10-r1.apk').write_bytes(b'fixture package')
                return ''

            def cleanup(path):
                events.append('cleanup')
                if state['readonly']:
                    raise OSError(errno.EROFS, 'boot medium is read-only')
                if cleanup_fails:
                    raise OSError(errno.EIO, 'injected cleanup failure')
                original_rmtree(path)

            def persist():
                events.append('persist')
                # Actual persist_overlay always remounts the medium read-only.
                state['readonly'] = True
                if persist_fails:
                    raise RuntimeError('injected persistence failure after remount')

            updates = Updates(SimpleNamespace(lock=threading.RLock(), persist=persist))
            with ExitStack() as stack:
                stack.enter_context(patch('travelrouter.system.boot_medium', return_value=medium))
                stack.enter_context(patch('travelrouter.updates.command', side_effect=invoke))
                stack.enter_context(patch('travelrouter.updates.Path', side_effect=lambda value:
                                         world if str(value) == '/etc/apk/world' else Path(value)))
                stack.enter_context(patch('travelrouter.updates.shutil.disk_usage',
                                         return_value=SimpleNamespace(free=2 * 1024**3)))
                stack.enter_context(patch('travelrouter.updates.shutil.copytree',
                                         side_effect=lambda source, dest, **kwargs:
                                         original_copytree(keys, dest, **kwargs)))
                stack.enter_context(patch('travelrouter.updates.shutil.rmtree', side_effect=cleanup))
                stack.enter_context(patch('travelrouter.updates.urllib.request.urlopen',
                                         side_effect=lambda *args, **kwargs: io.BytesIO(b'fixture index')))
                if cleanup_fails:
                    with self.assertRaises(OSError):
                        updates.stage_packages()
                elif persist_fails:
                    with self.assertRaisesRegex(RuntimeError, 'persistence failure'):
                        updates.stage_packages()
                else:
                    updates.stage_packages()
                    self.assertTrue(updates.status['reboot_required'])
                    self.assertIn('Verified Alpine packages staged', updates.status['message'])
                self.assertEqual(events[-1], 'remount,ro')
                self.assertTrue(state['readonly'])
                if cleanup_fails:
                    self.assertNotIn('persist', events)
                else:
                    self.assertLess(events.index('cleanup'), events.index('persist'))
                    self.assertFalse(list(medium.glob('.packages-*')))
                    self.assertTrue((medium / 'repositories/main/x86_64/python3-3.14.10-r1.apk').is_file())

    def test_success_cleans_staging_before_persistence_remounts_readonly(self):
        self.exercise_staging()

    def test_persistence_failure_still_finishes_readonly_without_late_cleanup(self):
        self.exercise_staging(persist_fails=True)

    def test_cleanup_failure_cannot_skip_final_readonly_remount(self):
        self.exercise_staging(cleanup_fails=True)
