import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from travelrouter.updates import Updates, package_update, verify_update


class UpdateTests(unittest.TestCase):
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
