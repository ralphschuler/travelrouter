import tempfile
import unittest
from pathlib import Path

from travelrouter.network import parse_nmcli, write_profile


class NetworkTests(unittest.TestCase):
    def test_nmcli_escaped_ssid_is_preserved(self):
        self.assertEqual(parse_nmcli(r'Cafe\:Floor\\2:WPA2:91:*'),
                         ['Cafe:Floor\\2', 'WPA2', '91', '*'])

    def test_profile_does_not_interpret_untrusted_ssid_as_ini(self):
        with tempfile.TemporaryDirectory() as directory:
            path, uuid = write_profile(Path(directory), 'Hotel;[evil]', 'safe password123', False)
            text = path.read_text()
            self.assertNotIn('ssid=Hotel', text)
            self.assertNotIn('[evil]', text)
            self.assertIn('key-mgmt=wpa-psk', text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stem, 'travelrouter-' + uuid)

    def test_open_network_requires_explicit_consent(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            write_profile(Path(directory), 'Free WiFi', '', False)

    def test_secret_newline_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            write_profile(Path(directory), 'Hotel', 'pass\n[evil]', False)
