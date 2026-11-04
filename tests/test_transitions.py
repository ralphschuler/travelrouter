import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from travelrouter.backup import seal
from travelrouter.config import ConfigStore
from travelrouter.security import hash_password
from travelrouter.system import System


class TransitionTests(unittest.TestCase):
    def test_dns_kill_switch_stays_installed_before_tunnel_teardown(self):
        for action in ('configure', 'restore'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                store = ConfigStore(Path(directory) / 'config.json')
                config = store.load()
                config.update(setup_complete=True, ap_password='a private wifi password', country='DE',
                              admin_hash=hash_password('a private admin password'), privacy_mode='wireguard')
                store.save(config)
                router = System.__new__(System)
                router.ap, router.wan, router.store = 'wlan0', 'wlan1', store
                policies = []

                class Tunnel:
                    mode = 'wireguard'

                    def stop(tunnel):
                        self.assertIn('meta skuid "unbound" oifname != "trvpn0"', policies[-1])
                        raise RuntimeError('stop after the transition-policy assertion')

                router.privacy = Tunnel()
                with patch('travelrouter.system.command', side_effect=lambda _args, **kwargs: policies.append(kwargs['input_text'])):
                    with self.assertRaises(RuntimeError):
                        if action == 'configure':
                            router.configure_privacy({'mode': 'direct'})
                        else:
                            envelope = seal({'version': 1, 'config': config, 'networks': [],
                                             'wireguard': None}, 'a unique backup password')
                            # A direct-mode backup can replace a protected router.
                            config['privacy_mode'] = 'direct'
                            envelope = seal({'version': 1, 'config': config}, 'a unique backup password')
                            router.restore(envelope, 'a unique backup password')
