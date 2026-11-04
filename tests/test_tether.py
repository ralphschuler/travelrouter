"""USB upstream selection must not accept a Wi-Fi, LAN or arbitrary interface."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from travelrouter.tether import discover_usb_networks, pair_iphone, perform_usb_action


class TetherTests(unittest.TestCase):
    def test_only_usb_network_devices_are_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            networks = root / 'class/net'
            networks.mkdir(parents=True)
            device = root / 'devices/usb1/1-1'
            device.mkdir(parents=True)
            (device / 'idVendor').write_text('05ac\n')
            interface = device / '1-1:4.2/net/usb0'
            interface.mkdir(parents=True)
            (interface / 'operstate').write_text('up\n')
            (networks / 'usb0').symlink_to(interface)
            wifi = device / '1-1:4.3/net/wlan1'
            wifi.mkdir(parents=True)
            (wifi / 'phy80211').mkdir()
            (networks / 'wlan1').symlink_to(wifi)
            (networks / 'eth0').mkdir()
            self.assertEqual(discover_usb_networks(networks),
                             [{'interface': 'usb0', 'kind': 'iPhone', 'state': 'up'}])

    def test_only_detected_usb_interface_can_be_activated(self):
        manager = Mock()
        with patch('travelrouter.tether.discover_usb_networks', return_value=[{'interface': 'usb0'}]):
            perform_usb_action(manager, 'connect', 'usb0')
            self.assertEqual(manager.nm.call_count, 2)
            manager.nm.assert_any_call('device', 'connect', 'usb0', timeout=40)
            manager.nm.assert_any_call('device', 'modify', 'usb0', 'ipv4.route-metric', '50', timeout=20)
            for action, name in [('connect', 'wlan0'), ('connect', 'usb0;id'), ('remove', 'usb0')]:
                with self.subTest(action=action, name=name), self.assertRaises(ValueError):
                    perform_usb_action(manager, action, name)

    def test_iphone_pairing_requires_one_valid_connected_device(self):
        with patch('travelrouter.tether.command', side_effect=['00008110-001234567890ABCD\n', '']) as run:
            pair_iphone()
            self.assertEqual(run.call_count, 2)
            run.assert_any_call(['/usr/bin/idevicepair', '-u', '00008110-001234567890ABCD', 'pair'], timeout=30)
        for devices in ('', 'bad id\n', 'one-device\nanother-device\n'):
            with self.subTest(devices=devices), patch('travelrouter.tether.command', return_value=devices):
                with self.assertRaises(ValueError):
                    pair_iphone()
