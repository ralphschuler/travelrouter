"""LAN-only captive landing page and authenticated operations API."""

import hmac
import json
import logging
import subprocess
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .metrics import logs, snapshot
from .security import Sessions, hash_password, validate_setup, verify_password

LOG = logging.getLogger(__name__)
ASSETS = Path(__file__).parent / 'static'


class RouterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def make_server(address, store, backend):
    sessions = Sessions()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'TravelRouter'
        sys_version = ''

        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, _format, *_args):
            # Avoid logging user-controlled paths, SSIDs or credentials.
            return

        def send(self, status, body=None, headers=None, content_type='application/json'):
            payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; "
                             "object-src 'none'; base-uri 'none'; form-action 'self'")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def host_allowed(self):
            hosts = {'10.42.0.1', '10.42.0.1:80', 'router.home.arpa', 'router.home.arpa:80',
                     f'{self.server.server_address[0]}:{self.server.server_port}'}
            return len(self.headers.get_all('Host', [])) == 1 and self.headers.get('Host') in hosts

        def origin_allowed(self):
            origin = self.headers.get('Origin')
            return origin is None or origin == 'http://' + self.headers.get('Host', '')

        def session(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                token = cookie['tr_session'].value if 'tr_session' in cookie else ''
                return sessions.get(token)
            except (ValueError, KeyError):
                return None

        def do_GET(self):
            path = urlsplit(self.path).path
            if not self.host_allowed():
                if not path.startswith('/api/') and backend.status()['state'] == 'offline':
                    self.send(302, {}, {'Location': 'http://10.42.0.1/'})
                else:
                    self.send(403, {'error': 'Use the local router address'})
                return
            if path == '/api/status':
                status = backend.status()
                if not self.session():
                    status = {key: value for key, value in status.items()
                              if key in {'state', 'setup_complete', 'ssid', 'address'}}
                self.send(200, status)
                return
            if path in {'/', '/app.js', '/style.css', '/forms.css', '/fonts/plex-sans-regular.woff2', '/fonts/plex-sans-semibold.woff2'}:
                name, kind = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/forms.css': ('forms.css', 'text/css; charset=utf-8'),
                              '/fonts/plex-sans-regular.woff2': ('fonts/plex-sans-regular.woff2', 'font/woff2'),
                              '/fonts/plex-sans-semibold.woff2': ('fonts/plex-sans-semibold.woff2', 'font/woff2'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
                self.send(200, (ASSETS / name).read_bytes(), content_type=kind)
                return
            with backend.lock:
                session = self.session()
                if not session:
                    self.send(401, {'error': 'Sign in to continue'})
                    return
                if path == '/api/session':
                    self.send(200, {'csrf': session['csrf'],
                                    'setup_required': not store.load()['setup_complete']})
                elif not store.load()['setup_complete']:
                    self.send(409, {'error': 'Replace factory passwords before continuing'})
                elif path == '/api/export':
                    self.send(200, backend.export())
                elif path == '/api/metrics':
                    config = store.load()
                    interfaces = [config.get('ap_interface'), config.get('wan_interface'), 'trvpn0', 'trproxy0']
                    self.send(200, snapshot(interfaces))
                elif path == '/api/logs':
                    self.send(200, logs())
                else:
                    self.send(404, {'error': 'Unknown endpoint'})

        def read_json(self):
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked requests are not accepted')
            if len(self.headers.get_all('Content-Length', [])) != 1:
                raise ValueError('A single Content-Length is required')
            try:
                length = int(self.headers['Content-Length'])
            except (ValueError, TypeError) as error:
                raise ValueError('Invalid Content-Length') from error
            maximum = 3 * 1024 * 1024 if urlsplit(self.path).path in {'/api/import', '/api/updates/install'} else 16384
            if length < 0 or length > maximum:
                self.send(413, {'error': 'Request body is too large'})
                return None
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Use application/json')
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError('Invalid JSON') from error
            if not isinstance(body, dict):
                raise ValueError('A JSON object is required')
            return body

        def do_POST(self):
            if not self.host_allowed() or not self.origin_allowed():
                self.send(403, {'error': 'Invalid request origin'})
                return
            try:
                data = self.read_json()
                if data is None:
                    return
                with backend.lock:
                    self.route_post(urlsplit(self.path).path, data)
            except (ValueError, TypeError, KeyError) as error:
                self.send(400, {'error': str(error)})
            except (TimeoutError, OSError, RuntimeError, subprocess.TimeoutExpired):
                LOG.exception('Router operation failed')
                self.send(503, {'error': 'Operation failed. Check the network and local console log.'})

        def route_post(self, path, data):
            config = store.load()
            if path == '/api/login':
                if not sessions.allow_login(self.client_address[0]):
                    self.send(429, {'error': 'Too many attempts. Wait one minute.'})
                    return
                password = data.get('password')
                if not isinstance(password, str) or len(password) > 128:
                    raise ValueError('Invalid password')
                if not verify_password(password, config['admin_hash']):
                    self.send(401, {'error': 'Incorrect password'})
                    return
                token, session = sessions.create()
                self.send(200, {'csrf': session['csrf'], 'setup_required': not config['setup_complete']},
                          {'Set-Cookie': f'tr_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=1800'})
                return
            session = self.session()
            if not session:
                self.send(401, {'error': 'Sign in to continue'})
                return
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                self.send(403, {'error': 'Invalid CSRF token'})
                return
            if path == '/api/logout':
                sessions.clear()
                self.send(200, {}, {'Set-Cookie': 'tr_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
                return
            if not config['setup_complete'] and path != '/api/setup':
                self.send(409, {'error': 'Replace factory passwords before continuing'})
                return
            if path in {'/api/setup', '/api/settings'}:
                if path == '/api/setup' and config['setup_complete']:
                    self.send(409, {'error': 'Initial setup is already complete'})
                    return
                admin, wifi = data.get('admin_password'), data.get('ap_password')
                ssid, country = data.get('ssid'), data.get('country')
                validate_setup(admin, wifi, ssid, country)
                config.update(admin_hash=hash_password(admin), ap_password=wifi, ssid=ssid,
                              country=country, setup_complete=True)
                backend.save_config(config)
                sessions.clear()
                self.send(200, {'reconnect': True, 'ssid': ssid})
            elif path == '/api/scan':
                self.send(200, {'networks': backend.scan()})
            elif path == '/api/dns':
                backend.save_dns(data.get('mode'))
                self.send(200, {'saved': True})
            elif path == '/api/developer':
                backend.save_developer(data)
                self.send(200, {'saved': True})
            elif path == '/api/filtering':
                backend.save_filtering(data)
                self.send(200, {'saved': True})
            elif path == '/api/filtering/refresh':
                backend.refresh_filtering()
                self.send(200, {'saved': True})
            elif path == '/api/privacy':
                backend.configure_privacy(data)
                self.send(200, {'saved': True})
            elif path == '/api/backup':
                self.send(200, backend.backup(data.get('password')))
            elif path == '/api/import':
                backend.restore(data.get('backup'), data.get('password'))
                sessions.clear()
                self.send(200, {'restored': True, 'reconnect': True})
            elif path == '/api/updates':
                backend.updates.start(data.get('operation'))
                self.send(202, {'started': True})
            elif path == '/api/updates/install':
                backend.updates.start('application', data.get('update'))
                self.send(202, {'started': True})
            elif path == '/api/updates/settings':
                if type(data.get('automatic')) is not bool:
                    raise ValueError('Automatic updates must be enabled or disabled')
                config['auto_updates'] = data['automatic']
                backend.save_config(config)
                self.send(200, {'saved': True})
            elif path == '/api/reboot':
                if data.get('confirm') is not True:
                    raise ValueError('Confirm the router reboot')
                from .network import command
                threading.Timer(3, lambda: command(['/sbin/reboot'])).start()
                self.send(202, {'rebooting': True})
            elif path == '/api/saved':
                self.send(200, {'networks': backend.saved()})
            elif path == '/api/connect':
                if type(data.get('allow_open', False)) is not bool:
                    raise ValueError('allow_open must be a boolean')
                backend.connect(ssid=data.get('ssid'), password=data.get('password', ''),
                                allow_open=data.get('allow_open', False))
                self.send(200, {'connected': True})
            elif path == '/api/network':
                backend.saved_action(action=data.get('action'), identifier=data.get('uuid'),
                                     priority=data.get('priority', 10))
                self.send(200, {})
            else:
                self.send(404, {'error': 'Unknown endpoint'})

    return RouterHTTPServer(address, Handler)
