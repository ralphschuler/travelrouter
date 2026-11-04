"""Do not start DHCP while the real Wi-Fi client is still associating or down."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'image_e2e_wifi', Path(__file__).resolve().parents[1] / 'image/e2e/wifi.py')
WIFI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WIFI)


class WifiReadinessTests(unittest.TestCase):
    def test_association_and_handshake_in_progress_do_not_permit_dhcp(self):
        link = {'ifname': 'wlan2', 'operstate': 'UP', 'flags': ['UP', 'LOWER_UP']}
        for state in ('SCANNING', 'ASSOCIATED', '4WAY_HANDSHAKE', 'DISCONNECTED'):
            with self.subTest(state=state):
                self.assertFalse(WIFI.associated({'wpa_state': state, 'ssid': 'Expected'}, link, 'Expected'))
        self.assertTrue(WIFI.associated({'wpa_state': 'COMPLETED', 'ssid': 'Expected'}, link, 'Expected'))

    def test_completed_handshake_does_not_mask_missing_carrier_or_wrong_network(self):
        status = {'wpa_state': 'COMPLETED', 'ssid': 'Expected'}
        for link in ({'ifname': 'wlan2', 'operstate': 'DOWN', 'flags': ['UP']},
                     {'ifname': 'wlan2', 'operstate': 'UP', 'flags': ['UP']},
                     {'ifname': 'wlan0', 'operstate': 'UP', 'flags': ['UP', 'LOWER_UP']}):
            with self.subTest(link=link):
                self.assertFalse(WIFI.associated(status, link, 'Expected'))
        link = {'ifname': 'wlan2', 'operstate': 'UP', 'flags': ['UP', 'LOWER_UP']}
        self.assertFalse(WIFI.associated(status, link, 'Different'))


if __name__ == '__main__':
    unittest.main()
