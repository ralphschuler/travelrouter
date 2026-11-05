import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from travelrouter.network import CommandFailure, Network, command, parse_nmcli, write_profile


class NetworkTests(unittest.TestCase):
    def test_failed_command_exposes_only_safe_exit_status(self):
        result = Mock(returncode=6, stdout='private data', stderr='private data')
        with patch('travelrouter.network.shutil.which', return_value='/usr/bin/curl'), \
             patch('travelrouter.network.subprocess.run', return_value=result):
            with self.assertRaises(CommandFailure) as error:
                command(['/usr/bin/curl'])
        self.assertEqual(error.exception.returncode, 6)
        self.assertNotIn('private data', str(error.exception))

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
                self.assertGreaterEqual(wait, 90)
                self.assertGreater(call.kwargs['timeout'], wait)

    def test_using_already_active_saved_network_does_not_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network('wlan1')
            network.profiles = Path(directory)
            identifier = '12345678-1234-1234-1234-123456789abc'
            (network.profiles / f'travelrouter-{identifier}.nmconnection').touch()
            with patch.object(network, 'nm', return_value=f'{identifier}:wlan1\n') as nm:
                network.saved_action('activate', identifier)
            nm.assert_called_once_with('-t', '--escape', 'yes', '-f', 'UUID,DEVICE', 'connection', 'show', '--active')

    def test_using_inactive_saved_network_requests_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network('wlan1')
            network.profiles = Path(directory)
            identifier = '12345678-1234-1234-1234-123456789abc'
            (network.profiles / f'travelrouter-{identifier}.nmconnection').touch()
            with patch.object(network, 'nm', return_value='') as nm:
                network.saved_action('activate', identifier)
            self.assertEqual(nm.call_count, 2)
            self.assertEqual(nm.call_args.args[:4], ('connection', 'up', 'uuid', identifier))
