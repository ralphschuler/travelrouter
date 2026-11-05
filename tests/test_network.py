import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from travelrouter.network import Network, parse_nmcli, write_profile


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

    def test_new_and_saved_connections_allow_time_for_wifi_and_dhcp(self):
        with tempfile.TemporaryDirectory() as directory, patch('travelrouter.network.command', return_value='') as run:
            network = Network('wlan1')
            network.profiles = Path(directory)
            identifier = network.connect('Hotel', 'safe password123')
            network.saved_action('activate', identifier)
            activations = [call for call in run.call_args_list if call.args[0][3:5] == ['connection', 'up']]
            self.assertEqual(len(activations), 2)
            for call in activations:
                wait = int(call.args[0][2])
                self.assertGreaterEqual(wait, 60)
                self.assertGreater(call.kwargs['timeout'], wait)
