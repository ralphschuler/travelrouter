"""Strict tunnel import and configuration; no imported scripts are executed."""

import base64
import configparser
import ipaddress
import json
import re
import socket
from pathlib import Path

from .config import atomic_write
from .network import command
from .policy import interface
from .security import validate_text

VPN_INTERFACE = 'trvpn0'
PROXY_INTERFACE = 'trproxy0'


def _key(value):
    try:
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError('WireGuard keys must encode 32 bytes')
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid WireGuard key') from error
    return value


def _hostname(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', value):
        raise ValueError('Invalid endpoint hostname or IPv4 address')
    return value


def wireguard_config(text):
    validate_text(text.replace('\n', '').replace('\r', ''), 'WireGuard configuration', 1, 12000)
    parser = configparser.ConfigParser(interpolation=None, delimiters=('=',), strict=True)
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise ValueError('Invalid WireGuard configuration') from error
    if parser.defaults() or set(parser.sections()) != {'Interface', 'Peer'}:
        raise ValueError('Exactly one Interface and one Peer are supported')
    local, peer = parser['Interface'], parser['Peer']
    if set(local) - {'privatekey', 'address', 'dns', 'mtu'} or set(peer) - {
            'publickey', 'presharedkey', 'endpoint', 'allowedips', 'persistentkeepalive'}:
        raise ValueError('Scripts, hooks and custom routing directives are not accepted')
    try:
        addresses = [ipaddress.ip_interface(address.strip()) for address in local['address'].split(',')]
        ipv4 = [str(address) for address in addresses if address.version == 4]
        if len(ipv4) != 1:
            raise ValueError('Exactly one IPv4 tunnel address is required')
        if ipaddress.ip_interface(ipv4[0]).ip in ipaddress.ip_network('10.42.0.0/24'):
            raise ValueError('Tunnel address collides with the local hotspot')
        allowed = {value.strip() for value in peer['allowedips'].split(',')}
        if '0.0.0.0/0' not in allowed or allowed - {'0.0.0.0/0', '::/0'}:
            raise ValueError('A full IPv4 tunnel (AllowedIPs=0.0.0.0/0) is required')
        host, port = peer['endpoint'].rsplit(':', 1)
        _hostname(host)
        if not 1 <= int(port) <= 65535:
            raise ValueError('Invalid endpoint port')
        mtu = int(local.get('mtu', '1380'))
        if not 1280 <= mtu <= 1500:
            raise ValueError('MTU must be between 1280 and 1500')
        private, public = _key(local['privatekey']), _key(peer['publickey'])
        shared = _key(peer['presharedkey']) if 'presharedkey' in peer else None
    except KeyError as error:
        raise ValueError('WireGuard configuration is missing required fields') from error
    # DNS remains under Unbound control. IPv6 is disabled by the router policy.
    output = (f'[Interface]\nPrivateKey = {private}\nAddress = {ipv4[0]}\nMTU = {mtu}\n'
              f'\n[Peer]\nPublicKey = {public}\nAllowedIPs = 0.0.0.0/0\n'
              f'Endpoint = {host}:{int(port)}\nPersistentKeepalive = 25\n')
    if shared:
        output += f'PresharedKey = {shared}\n'
    return output


def proxy_config(data, resolved_ip, wan):
    kind = data.get('type')
    if kind not in {'https', 'socks5'}:
        raise ValueError('Choose an HTTPS CONNECT or SOCKS5 proxy')
    host = _hostname(data.get('server'))
    port = data.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Proxy port must be between 1 and 65535')
    address = ipaddress.ip_address(resolved_ip)
    if address.version != 4 or address.is_loopback or address.is_unspecified:
        raise ValueError('Proxy must resolve to a usable IPv4 address')
    if kind == 'socks5' and data.get('acknowledge_plaintext') is not True:
        raise ValueError('SOCKS5 does not encrypt transport; explicitly acknowledge this before use')
    outbound = {'type': 'http' if kind == 'https' else 'socks', 'tag': 'proxy-out',
                'server': str(address), 'server_port': port, 'bind_interface': interface(wan)}
    if kind == 'https':
        outbound['tls'] = {'enabled': True, 'server_name': host}
    else:
        outbound['version'] = '5'
    for field in ('username', 'password'):
        value = data.get(field, '')
        if value:
            validate_text(value, 'Proxy ' + field, 1, 256)
            outbound[field] = value
    return {'log': {'level': 'warn', 'timestamp': True},
            'inbounds': [{'type': 'tun', 'tag': 'tun-in', 'interface_name': PROXY_INTERFACE,
                          'address': ['172.31.255.1/30'], 'mtu': 1380,
                          'auto_route': True, 'strict_route': True, 'stack': 'system'}],
            'outbounds': [outbound], 'route': {'auto_detect_interface': True, 'final': 'proxy-out'}}


class Privacy:
    def __init__(self, store):
        self.store = store
        self.directory = Path('/etc/travelrouter')
        self.attempted = False

    @property
    def mode(self):
        return self.store.load().get('privacy_mode', 'direct')

    @property
    def egress(self):
        return {'wireguard': VPN_INTERFACE, 'proxy': PROXY_INTERFACE}.get(self.mode)

    def stop(self):
        if Path('/sys/class/net/' + VPN_INTERFACE).exists():
            command(['/usr/bin/wg-quick', 'down', VPN_INTERFACE])
        # Our dedicated service is disabled by default and owns only our config.
        if (self.directory / 'proxy.json').exists():
            command(['/sbin/rc-service', 'travelrouter-proxy', 'stop'])
        self.attempted = False

    def prepare(self, data, wan):
        mode = data.get('mode')
        if mode not in {'direct', 'wireguard', 'proxy'}:
            raise ValueError('Invalid privacy mode')
        if mode == 'wireguard':
            path = Path('/etc/wireguard/trvpn0.conf')
            if data.get('config'):
                content = wireguard_config(data['config'])
                atomic_write(path, content)
            elif not path.is_file():
                raise ValueError('Supply a WireGuard configuration')
        elif mode == 'proxy':
            path = self.directory / 'proxy-source.json'
            if data.get('server'):
                if not wan:
                    raise ValueError('Connect the upstream before configuring a proxy')
                host = _hostname(data.get('server'))
                try:
                    resolved = socket.getaddrinfo(host, data.get('port'), socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
                except (OSError, TypeError) as error:
                    raise ValueError('Cannot resolve proxy endpoint through the upstream network') from error
                config = proxy_config(data, resolved, wan)
                atomic_write(path, json.dumps(data))
                atomic_write(self.directory / 'proxy.json', json.dumps(config, indent=2))
            elif not path.is_file():
                raise ValueError('Supply proxy settings')
        return mode

    def start(self):
        if self.mode == 'direct' or (self.egress and Path('/sys/class/net/' + self.egress).exists()):
            return
        if self.mode == 'wireguard':
            command(['/usr/bin/wg-quick', 'up', VPN_INTERFACE], timeout=30)
        elif self.mode == 'proxy':
            source = json.loads((self.directory / 'proxy-source.json').read_text())
            routes = json.loads(command(['/sbin/ip', '-j', '-4', 'route', 'show', 'default']))
            wan = next((route['dev'] for route in routes if route.get('dev') not in
                        {VPN_INTERFACE, PROXY_INTERFACE} and route.get('dev')), None)
            if not wan:
                raise RuntimeError('No upstream route for the proxy')
            address = socket.getaddrinfo(source['server'], source['port'], socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
            atomic_write(self.directory / 'proxy.json', json.dumps(proxy_config(source, address, wan)))
            command(['/sbin/rc-service', 'travelrouter-proxy', 'start'])
        self.attempted = True
