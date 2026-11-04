import unittest

from travelrouter.metrics import parse_meminfo, parse_netdev


class MetricsTests(unittest.TestCase):
    def test_available_memory_is_used_instead_of_free_memory(self):
        result = parse_meminfo('MemTotal: 1024 kB\nMemFree: 64 kB\nMemAvailable: 512 kB\n')
        self.assertEqual(result, {'total_bytes': 1048576, 'available_bytes': 524288})

    def test_network_counters_preserve_receive_and_transmit(self):
        text = 'wlan0: 1234 1 0 0 0 0 0 0 5678 2 0 0 0 0 0 0 0\n'
        self.assertEqual(parse_netdev(text, ['wlan0']), {'wlan0': {'rx_bytes': 1234, 'tx_bytes': 5678}})
