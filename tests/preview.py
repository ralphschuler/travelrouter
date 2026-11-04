"""Disposable local UI preview. No host networking/settings are changed."""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from test_web import LocalBackend

import travelrouter.web as web
from travelrouter.config import ConfigStore
from travelrouter.filtering import DEFAULTS


class PreviewBackend(LocalBackend):
    def status(self):
        config = self.store.load()
        return {'state': 'offline', 'setup_complete': config['setup_complete'], 'ssid': config['ssid'],
                'address': '10.42.0.1', 'country': config['country'], 'ap_interface': 'wlan0',
                'wan_interface': 'wlan1', 'privacy_mode': 'direct', 'dns_mode': 'dot',
                'dns': 'offline', 'firewall': True, 'filtering': {'settings': DEFAULTS,
                'metadata': {'updated': None, 'sources': {}}, 'last_error': None},
                'updates': {'automatic': False, 'message': 'Preview only', 'busy': False, 'reboot_required': False}}

    def saved(self):
        return []

    def save_filtering(self, data):
        return None

    def save_dns(self, mode):
        return None

    def export(self):
        return {'preview': True}


def metrics(_interfaces):
    return {'timestamp': 100, 'uptime_seconds': 4321,
            'memory': {'total_bytes': 8 * 1024**3, 'available_bytes': 6 * 1024**3},
            'interfaces': {'wlan0': {'rx_bytes': 123456, 'tx_bytes': 234567}},
            'load_average': [0.13, 0.09, 0.1], 'temperature_c': 42,
            'clients': [{'ip': '10.42.0.50', 'hostname': 'Preview phone'}],
            'dns': {'total.num.queries': 123, 'total.num.cachehits': 98}}


with tempfile.TemporaryDirectory() as directory:
    store = ConfigStore(Path(directory) / 'config.json')
    store.load()
    if '--configured' in sys.argv:
        config = store.load()
        config['setup_complete'] = True
        store.save(config)
    backend = PreviewBackend(store)
    backend.updates = SimpleNamespace(start=lambda *_args: None)
    web.snapshot = metrics
    web.logs = lambda: {'router': ['Preview only — no real router logs.']}
    server = web.make_server(('127.0.0.1', 8765), store, backend)
    print('Disposable UI preview at http://127.0.0.1:8765/', flush=True)
    server.serve_forever()
