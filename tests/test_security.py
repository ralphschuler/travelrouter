import os
import tempfile
import unittest
from pathlib import Path

from travelrouter.config import ConfigStore
from travelrouter.security import hash_password, validate_setup, verify_password


class SecurityTests(unittest.TestCase):
    def test_password_hash_is_salted_and_rejects_wrong_password(self):
        first = hash_password('a unique administrator password')
        self.assertNotEqual(first, hash_password('a unique administrator password'))
        self.assertTrue(verify_password('a unique administrator password', first))
        self.assertFalse(verify_password('wrong', first))
        self.assertFalse(verify_password('wrong', 'malformed'))

    def test_setup_rejects_default_and_short_passwords(self):
        for admin, wifi in [('ChangeMe-TravelRouter!', 'a good wifi password'),
                            ('new admin password', 'TravelRouter-Setup!'),
                            ('short', 'a good wifi password'),
                            ('a good admin password', 'short'),
                            ('same-password-123', 'same-password-123')]:
            with self.subTest(admin=admin, wifi=wifi), self.assertRaises(ValueError):
                validate_setup(admin, wifi, 'Private Router', 'DE')

    def test_setup_rejects_injection_and_invalid_country(self):
        for ssid, country in [('Bad\nSSID', 'DE'), ('a' * 33, 'DE'),
                              ('TravelRouter', 'XX!'), ('', 'DE')]:
            with self.subTest(ssid=ssid), self.assertRaises(ValueError):
                validate_setup('a new admin password', 'a new wifi password', ssid, country)
        validate_setup('a new admin password', 'a new wifi password', 'My café', 'DE')
        validate_setup('a longer pàssword 123', 'a separate wifi password', 'My café', 'DE')

    def test_configuration_is_private_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private' / 'config.json'
            store = ConfigStore(path)
            data = store.load()
            self.assertFalse(data['setup_complete'])
            self.assertTrue(verify_password('ChangeMe-TravelRouter!', data['admin_hash']))
            data['setup_complete'] = True
            data['admin_hash'] = hash_password('my replacement password')
            store.save(data)
            self.assertTrue(ConfigStore(path).load()['setup_complete'])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(path.parent).st_mode & 0o777, 0o700)
            self.assertNotIn('my replacement password', path.read_text())

    def test_corrupt_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                ConfigStore(path).load()
