"""Real client-side protocol checks; run inside the VM's Wi-Fi client netns."""

import http.client
import ipaddress
import json
import socket
import struct
import sys
import time
from pathlib import Path

ADDRESS = '10.42.0.1'
# Public credentials used only inside the disposable guest fixture.
NEW_ADMIN = 'CI-only-admin-password-729'
NEW_WIFI = 'CI-only-wireless-password-841'
FACTORY_ADMIN = 'ChangeMe-TravelRouter!'
FACTORY_WIFI = 'TravelRouter-Setup!'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Client:
    def __init__(self):
        self.cookie = ''
        self.csrf = ''

    def request(self, path, data=None, headers=None, address=ADDRESS):
        connection = http.client.HTTPConnection(address, 80, timeout=20)
        request_headers = {'Cookie': self.cookie, 'X-CSRF-Token': self.csrf}
        body = None if data is None else json.dumps(data)
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        connection.request('GET' if body is None else 'POST', path, body, request_headers)
        response = connection.getresponse()
        payload, response_headers = response.read(), dict(response.getheaders())
        cookie = response.getheader('Set-Cookie')
        if cookie:
            self.cookie = cookie.split(';')[0]
        status = response.status
        connection.close()
        return status, payload, response_headers

    def expect(self, status, path, data=None, **kwargs):
        actual, payload, headers = self.request(path, data, **kwargs)
        require(actual == status, f'{path}: expected HTTP {status}, received {actual}: {payload[:200]!r}')
        return payload, headers

    def login(self, password, setup_required):
        payload, headers = self.expect(200, '/api/login', {'password': password})
        result = json.loads(payload)
        require(result['setup_required'] is setup_required, 'Incorrect forced-setup state')
        require('HttpOnly' in headers.get('Set-Cookie', ''), 'Session cookie must be HttpOnly')
        self.csrf = result['csrf']


def dns_answer(server, name):
    ident = 0x7452
    question = b''.join(bytes([len(label)]) + label.encode() for label in name.split('.')) + b'\x00'
    packet = struct.pack('!HHHHHH', ident, 0x100, 1, 0, 0, 0) + question + struct.pack('!HH', 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(5)
        sock.sendto(packet, (server, 53))
        answer, _ = sock.recvfrom(4096)
    response_id, flags, _, answer_count, _, _ = struct.unpack('!HHHHHH', answer[:12])
    require(response_id == ident and flags & 15 == 0 and answer_count > 0, 'DNS query failed')
    require(socket.inet_aton(ADDRESS) in answer[12:], 'Offline DNS must resolve to the router')


def require_blocked(address, port):
    try:
        with socket.create_connection((address, port), timeout=3):
            raise AssertionError(f'Unexpected reachable service: {address}:{port}')
    except (TimeoutError, ConnectionRefusedError, OSError):
        # Refused routes are fail-closed too; the destination server is separately
        # verified reachable inside its own namespace by the host-side harness.
        pass


def main():
    phase = sys.argv[1]
    if phase == 'untrusted':
        require_blocked(ADDRESS, 80)
        print('Untrusted ingress cannot reach the panel', flush=True)
        return
    lease = ipaddress.ip_address(Path('/root/ci-image-test/client-address').read_text().strip())
    require(lease in ipaddress.ip_network('10.42.0.0/24'), 'Client did not receive a LAN DHCP lease')
    dns_answer(ADDRESS, 'router.home.arpa')
    dns_answer('8.8.8.8', 'offline-test.example')
    client = Client()
    for path, content_type in [('/', 'text/html'), ('/app.js', 'text/javascript'),
                               ('/style.css', 'text/css'), ('/fonts/plex-sans-regular.woff2', 'font/woff2')]:
        payload, headers = client.expect(200, path)
        require(bool(payload), f'Empty panel asset: {path}')
        require(content_type in headers.get('Content-Type', ''), f'Wrong asset type for {path}')
    payload, _ = client.expect(200, '/api/status')
    status = json.loads(payload)
    require(status['state'] == 'offline', 'Isolated VM must be offline')
    require(status['setup_complete'] is (phase == 'restored'), 'Unexpected setup completion')
    _, headers = client.expect(302, '/generate_204', headers={'Host': 'connectivitycheck.gstatic.com'})
    require(headers.get('Location') == 'http://10.42.0.1/', 'Captive redirect target changed')
    client.expect(403, '/api/status', headers={'Host': 'evil.example'})
    client.expect(403, '/api/login', {'password': FACTORY_ADMIN}, headers={'Origin': 'https://evil.example'})
    client.expect(401, '/api/connect', {'ssid': 'CI network', 'password': NEW_WIFI})
    require_blocked('198.18.0.2', 8080)
    if phase == 'initial':
        client.login(FACTORY_ADMIN, True)
        client.expect(409, '/api/connect', {'ssid': 'CI network', 'password': NEW_WIFI})
        change = {'admin_password': NEW_ADMIN, 'ap_password': NEW_WIFI,
                  'ssid': 'TravelRouter-CI', 'country': 'DE'}
        client.expect(403, '/api/setup', change, headers={'X-CSRF-Token': 'invalid-fixture-token'})
        client.expect(200, '/api/setup', change)
        print('Forced setup, CSRF and real overlay persistence request passed', flush=True)
    elif phase == 'restored':
        require(status['ssid'] == 'TravelRouter-CI', 'SSID did not persist across cold reboot')
        client.expect(401, '/api/login', {'password': FACTORY_ADMIN})
        client.login(NEW_ADMIN, False)
        client.expect(200, '/api/metrics')
        client.expect(200, '/api/logs')
        client.expect(403, '/api/dns', {'mode': 'recursive'},
                      headers={'X-CSRF-Token': 'invalid-fixture-token'})
        print('Reboot preserved rotated credentials; dashboard metrics/logs respond', flush=True)
    else:
        raise ValueError('Unknown test phase')
    time.sleep(0.1)
    print(f'CLIENT E2E PASSED: {phase}', flush=True)


if __name__ == '__main__':
    main()
