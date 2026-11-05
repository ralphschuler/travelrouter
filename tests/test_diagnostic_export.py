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

    def test_bundle_tests_the_detected_gateway_and_preserves_failed_probe_output(self):
        import io
        import json
        import zipfile
        from types import SimpleNamespace

        from travelrouter.diagnostics import bundle

        initial = {'checks': {'ipv4_routes': {'status': 'ok', 'output': 'default via 192.168.4.1 dev wlan1\n'}},
                   'logs': {'router': []}}
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[0].endswith('ping'):
                return SimpleNamespace(returncode=1, stdout='3 packets transmitted, 0 packets received', stderr='')
            if args[0].endswith('dmesg'):
                return SimpleNamespace(returncode=0, stdout='r92su warning\npassword=do-not-share\n', stderr='')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        with patch('travelrouter.diagnostics.collect', return_value=initial), \
             patch('travelrouter.diagnostics.shutil.which', side_effect=lambda name, **kw: '/sbin/' + name), \
             patch('travelrouter.diagnostics.subprocess.run', side_effect=run):
            archive = bundle()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            report = json.loads(zipped.read('diagnostics.json'))
            kernel = zipped.read('kernel.log').decode()
        self.assertTrue(any('192.168.4.1' in args and 'ping' in args[0] for args in calls))
        self.assertEqual(report['extended_checks']['gateway_ping']['exit_code'], 1)
        self.assertIn('0 packets received', report['extended_checks']['gateway_ping']['output'])
        self.assertIn('r92su warning', kernel)
        self.assertNotIn('do-not-share', kernel)

    def test_gateway_parser_rejects_untrusted_route_arguments(self):
        from travelrouter.diagnostics import gateway_from_route

        self.assertIsNone(gateway_from_route('default via 192.168.1.1 dev wlan1;evil'))
        self.assertIsNone(gateway_from_route('default via not-an-ip dev wlan1'))
