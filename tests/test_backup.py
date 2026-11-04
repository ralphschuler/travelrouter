import tempfile
import unittest
from pathlib import Path

from travelrouter.backup import seal, unseal, validate_payload
from travelrouter.config import ConfigStore
from travelrouter.security import hash_password


class BackupTests(unittest.TestCase):
    def test_unsupported_or_missing_config_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigStore(Path(directory) / 'config.json').load()
            config.update(setup_complete=True, admin_hash=hash_password('a new administrator password'),
                          ap_password='a new private wifi password', country='DE')
            for schema in (None, 2, True):
                candidate = dict(config)
                if schema is None:
                    candidate.pop('schema')
                else:
                    candidate['schema'] = schema
                with self.subTest(schema=schema), self.assertRaises(ValueError):
                    validate_payload({'version': 1, 'config': candidate})

    def test_encrypted_backup_roundtrip_and_wrong_password(self):
        original = {'version': 1, 'private': 'not-in-the-export'}
        sealed = seal(original, 'a unique backup password')
        self.assertNotIn('not-in-the-export', str(sealed))
        self.assertEqual(unseal(sealed, 'a unique backup password'), original)
        with self.assertRaises(ValueError):
            unseal(sealed, 'the wrong backup password')

    def test_modified_ciphertext_is_rejected(self):
        sealed = seal({'version': 1}, 'a unique backup password')
        sealed['ciphertext'] = 'AAAA' + sealed['ciphertext'][4:]
        with self.assertRaises(ValueError):
            unseal(sealed, 'a unique backup password')

    def test_backup_cannot_restore_arbitrary_paths_or_factory_state(self):
        with self.assertRaises(ValueError):
            validate_payload({'version': 1, 'files': {'/etc/passwd': 'evil'}})
        with self.assertRaises(ValueError):
            validate_payload({'version': 1, 'config': {'setup_complete': False}})
