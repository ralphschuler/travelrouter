import subprocess
import unittest
from unittest.mock import patch

from travelrouter.diagnostics import collect


class DiagnosticExportTests(unittest.TestCase):
    def test_failed_probes_do_not_abort_and_secrets_are_removed(self):
        results = ['Linux 6.18\n', 'wlan1: inet 192.168.1.3/24\n', 'default via 192.168.1.1\n', 'link stats', 'r92su', 'ping ok',
                   subprocess.TimeoutExpired('nslookup', 3), 'HTTP/2 200\n']
        log = {'system': ["Config: added 'psk' value 'hunter2'", 'password=verysecret',
                          'wlan1: connected to wireless network "my-private-ssid"']}
        with patch('travelrouter.diagnostics.command', side_effect=results), patch('travelrouter.diagnostics.logs', return_value=log):
            result = collect()
        text = str(result)
        self.assertNotIn('hunter2', text)
        self.assertNotIn('verysecret', text)
        self.assertNotIn('my-private-ssid', text)
        self.assertIn('timeout', text.lower())
        self.assertIn('192.168.1.3', text)
        self.assertIn('HTTP/2 200', text)
