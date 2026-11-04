import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from travelrouter.config import atomic_write
from travelrouter.system import System


class ServiceLifecycleTests(unittest.TestCase):
    def test_network_dns_and_ap_transitions_preserve_the_controller(self):
        config = {'setup_complete': True, 'dns_mode': 'dot', 'ssid': 'Lifecycle test',
                  'ap_password': 'private lifecycle password', 'country': 'DE'}
        router = System.__new__(System)
        router.store = SimpleNamespace(load=lambda: dict(config))
        router.ap, router.wan, router.state = 'wlan0', None, 'offline'
        router.privacy = SimpleNamespace(mode='direct', egress=None)
        router.network = SimpleNamespace(wan='wlan1')
        router.filtering = SimpleNamespace(status=lambda: {'missing_countries': []}, rules=lambda: ('', []))
        router.last_policy, router.last_dns_mode, router.filter_revision = None, 'dot', 0
        router.lock = threading.RLock()
        router.stop = Mock()
        router.stop.is_set.side_effect = [False, True]
        router.active_wan = lambda: None
        router._probe = lambda wan: 'offline'
        restarts = []

        def command(arguments, **kwargs):
            if arguments[0] == '/sbin/rc-service' and arguments[-1] == 'restart':
                # OpenRC stops reverse `need` dependencies unless --nodeps is
                # supplied. The controller needs all three managed services.
                self.assertIn('--nodeps', arguments, 'restart would stop its own controller')
                restarts.append(arguments[-2])
            return ''

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def local_path(value):
                return root / str(value).lstrip('/')

            def write(path, content, mode=0o600):
                path = Path(path)
                if not path.is_relative_to(root):
                    path = local_path(path)
                atomic_write(path, content, mode)

            write('/etc/unbound/travelrouter-blocks.conf', '', 0o644)
            with patch('travelrouter.system.Path', side_effect=local_path), \
                    patch('travelrouter.system.atomic_write', side_effect=write), \
                    patch('travelrouter.system.command', side_effect=command), \
                    patch('travelrouter.system.discover_radios', return_value=['wlan0', 'wlan1']):
                # First offline policy application updates dnsmasq. A no-op
                # repeat must not restart it again.
                router.apply('offline', None)
                router.apply('offline', None)
                self.assertEqual(restarts, ['dnsmasq'])
                # Changing DNS mode restarts Unbound and applies DNS routing.
                config['dns_mode'] = 'recursive'
                router.apply('offline', None)
                self.assertEqual(restarts, ['dnsmasq', 'unbound', 'dnsmasq'])
                # Deferred AP credential/SSID changes run through the real loop.
                router.pending_restart = 1
                router.loop()
                self.assertEqual(restarts, ['dnsmasq', 'unbound', 'dnsmasq', 'hostapd'])
                self.assertEqual(router.pending_restart, 0)
                self.assertIsNone(router.last_error)
