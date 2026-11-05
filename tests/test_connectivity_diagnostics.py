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

    def test_http_probe_timeout_uses_independent_verified_https_fallback(self):
        router = System.__new__(System)
        with patch('travelrouter.system.command', side_effect=[CommandFailure('/usr/bin/curl', 28), '200']):
            self.assertEqual(router._probe('wlan1'), 'online')

    def test_http_probe_timeout_does_not_trust_unexpected_fallback_status(self):
        router = System.__new__(System)
        with patch('travelrouter.system.command', side_effect=[CommandFailure('/usr/bin/curl', 28), '302']):
            self.assertEqual(router._probe('wlan1'), 'offline')

    def test_captive_response_is_not_bypassed_by_fallback(self):
        router = System.__new__(System)
        with patch('travelrouter.system.command', return_value='login\n302') as run:
            self.assertEqual(router._probe('wlan1'), 'captive')
            self.assertEqual(run.call_count, 1)

    def test_transient_offline_probes_do_not_immediately_interrupt_online_clients(self):
        from travelrouter.system import should_apply_connectivity

        for failures in range(1, 6):
            self.assertFalse(should_apply_connectivity('offline', 'online', failures, 'wlan1', 'direct'))
        self.assertTrue(should_apply_connectivity('offline', 'online', 6, 'wlan1', 'direct'))
        self.assertTrue(should_apply_connectivity('online', 'offline', 2, 'wlan1', 'direct'))

    def test_lost_route_and_protected_connections_fail_closed_immediately(self):
        from travelrouter.system import should_apply_connectivity

        self.assertTrue(should_apply_connectivity('offline', 'online', 1, None, 'direct'))
        for mode in ('wireguard', 'proxy'):
            self.assertTrue(should_apply_connectivity('offline', 'online', 1, 'wlan1', mode))
