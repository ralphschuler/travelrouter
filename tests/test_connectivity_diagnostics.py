import unittest
from unittest.mock import patch

from travelrouter.network import CommandFailure
from travelrouter.system import System


class ConnectivityDiagnosticTests(unittest.TestCase):
    def test_http_failure_is_logged_without_sensitive_exception_text(self):
        router = System.__new__(System)
        with patch('travelrouter.system.command', side_effect=RuntimeError('private network data')):
            with self.assertLogs('travelrouter.system', level='INFO') as logs:
                self.assertEqual(router._probe('wlan1'), 'offline')
                self.assertEqual(router._probe('wlan1'), 'offline')
        self.assertEqual(len(logs.output), 1)
        self.assertIn('HTTP check failed', logs.output[0])
        self.assertNotIn('private network data', logs.output[0])

    def test_https_failure_is_distinguished_from_http_failure(self):
        router = System.__new__(System)
        with patch('travelrouter.system.command', side_effect=['NetworkManager is online\n200', RuntimeError('secret')]):
            with self.assertLogs('travelrouter.system', level='INFO') as logs:
                self.assertEqual(router._probe('wlan1'), 'offline')
        self.assertIn('HTTPS check failed', logs.output[0])
        self.assertNotIn('secret', logs.output[0])

    def test_curl_failure_code_is_logged_without_command_output(self):
        router = System.__new__(System)
        with patch('travelrouter.system.command', side_effect=CommandFailure('/usr/bin/curl', 6)):
            with self.assertLogs('travelrouter.system', level='INFO') as logs:
                self.assertEqual(router._probe('wlan1'), 'offline')
        self.assertIn('HTTP check failed (curl exit 6)', logs.output[0])
