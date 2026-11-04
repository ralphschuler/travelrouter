import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from travelrouter.config import ConfigStore
from travelrouter.web import make_server


class LocalBackend:
    """No hardware in HTTP tests; real config writes remain under test."""
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.connected = False
        self.developer_settings = None

    def status(self):
        return {'state': 'offline', 'setup_complete': self.store.load()['setup_complete']}

    def save_config(self, data):
        self.store.save(data)

    def save_developer(self, data):
        self.developer_settings = data

    def connect(self, **kwargs):
        self.connected = True
        return 'test-network'

    def scan(self):
        return [{'ssid': '<img src=x onerror=alert(1)>', 'signal': 90, 'security': 'WPA2'}]


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.directory.name) / 'config.json')
        self.store.load()
        self.backend = LocalBackend(self.store)
        self.server = make_server(('127.0.0.1', 0), self.store, self.backend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''
        self.csrf = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        body = raw if raw is not None else json.dumps(data) if data is not None else None
        request_headers = {'Cookie': self.cookie, 'X-CSRF-Token': self.csrf}
        if data is not None or raw is not None:
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        connection.request('POST' if body is not None else 'GET', path, body, request_headers)
        response = connection.getresponse()
        payload = response.read()
        cookie = response.getheader('Set-Cookie')
        if cookie:
            self.cookie = cookie.split(';')[0]
        result = (response.status, payload, dict(response.getheaders()))
        connection.close()
        return result

    def login(self):
        status, body, _ = self.request('/api/login', {'password': 'ChangeMe-TravelRouter!'})
        self.assertEqual(status, 200)
        self.csrf = json.loads(body)['csrf']

    def test_mutation_without_login_is_rejected(self):
        status, _, _ = self.request('/api/connect', {'ssid': 'Hotel', 'password': 'test12345'})
        self.assertEqual(status, 401)
        self.assertFalse(self.backend.connected)

    def test_hostile_host_and_cross_origin_are_rejected(self):
        self.assertEqual(self.request('/api/status', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/login', {'password': 'ChangeMe-TravelRouter!'},
                                      {'Origin': 'https://evil.example'})[0], 403)

    def test_setup_gate_and_csrf_prevent_upstream_changes(self):
        self.login()
        self.assertEqual(self.request('/api/connect', {'ssid': 'Hotel', 'password': 'test12345'})[0], 409)
        self.assertEqual(self.request('/api/setup', {'admin_password': 'my new admin password',
                         'ap_password': 'my new wifi password', 'ssid': 'My Router', 'country': 'DE'},
                         {'X-CSRF-Token': 'wrong'})[0], 403)

    def test_developer_changes_require_login_setup_and_csrf(self):
        data = {'enabled': True, 'public_key': 'example'}
        self.assertEqual(self.request('/api/developer', data)[0], 401)
        self.login()
        self.assertEqual(self.request('/api/developer', data)[0], 409)
        config = self.store.load()
        config['setup_complete'] = True
        self.store.save(config)
        self.assertEqual(self.request('/api/developer', data, {'X-CSRF-Token': 'wrong'})[0], 403)
        self.assertIsNone(self.backend.developer_settings)
        self.assertEqual(self.request('/api/developer', data)[0], 200)
        self.assertEqual(self.backend.developer_settings, data)

    def test_setup_rotates_credentials_and_invalidates_session(self):
        self.login()
        data = {'admin_password': 'my new admin password', 'ap_password': 'my new wifi password',
                'ssid': 'My Router', 'country': 'DE'}
        self.assertEqual(self.request('/api/setup', data)[0], 200)
        self.assertTrue(self.store.load()['setup_complete'])
        self.assertEqual(self.request('/api/connect', {'ssid': 'Hotel', 'password': 'test12345'})[0], 401)
        self.assertEqual(self.request('/api/login', {'password': 'ChangeMe-TravelRouter!'})[0], 401)
        status, payload, _ = self.request('/api/login', {'password': 'my new admin password'})
        self.assertEqual(status, 200)
        self.csrf = json.loads(payload)['csrf']
        self.assertEqual(self.request('/api/connect', {'ssid': 'Hotel', 'password': 'test12345'})[0], 200)
        self.assertTrue(self.backend.connected)

    def test_malformed_and_oversized_json_are_rejected(self):
        self.assertEqual(self.request('/api/login', raw='{broken')[0], 400)
        self.assertEqual(self.request('/api/login', raw='[]')[0], 400)
        self.assertEqual(self.request('/api/login', raw='x' * 20000)[0], 413)

    def test_captive_probe_redirect_and_security_headers(self):
        status, _, headers = self.request('/generate_204', headers={'Host': 'connectivitycheck.gstatic.com'})
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], 'http://10.42.0.1/')
        status, _, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])

    def test_login_is_rate_limited(self):
        for _ in range(5):
            self.assertEqual(self.request('/api/login', {'password': 'wrong'})[0], 401)
        self.assertEqual(self.request('/api/login', {'password': 'wrong'})[0], 429)
