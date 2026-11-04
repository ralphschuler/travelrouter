import unittest

from travelrouter.policy import classify_probe, render_dns, render_firewall


class PolicyTests(unittest.TestCase):
    def test_connectivity_requires_https_and_exact_http_body(self):
        self.assertEqual(classify_probe(False, None, '', False), 'offline')
        self.assertEqual(classify_probe(True, 302, '', False), 'captive')
        self.assertEqual(classify_probe(True, 200, '<html>Login</html>', False), 'captive')
        self.assertEqual(classify_probe(True, 200, 'NetworkManager is online', True), 'online')
        self.assertEqual(classify_probe(True, 200, 'NetworkManager is online', False), 'offline')
        self.assertEqual(classify_probe(True, None, '', False), 'offline')
        self.assertEqual(classify_probe(True, 500, '', False), 'offline')

    def test_setup_blocks_forwarding_even_when_upstream_is_online(self):
        rules = render_firewall('wlan0', 'wlan1', 'online', False)
        self.assertIn('policy drop', rules)
        self.assertNotIn('masquerade', rules)
        self.assertNotIn('oifname "wlan1" accept', rules)

    def test_forwarding_only_uses_selected_upstream(self):
        rules = render_firewall('wlan0', 'wlan1', 'online', True)
        self.assertIn('iifname "wlan0" oifname "wlan1"', rules)
        self.assertIn('masquerade', rules)
        self.assertNotIn('iifname "wlan1" oifname "wlan0" accept', rules)
        self.assertNotIn('flush ruleset', rules)

    def test_invalid_or_same_interface_cannot_generate_firewall(self):
        for ap, wan in [('wlan0; include evil', 'wlan1'), ('wlan0', 'wlan0')]:
            with self.assertRaises(ValueError):
                render_firewall(ap, wan, 'online', True)

    def test_developer_ssh_only_opens_on_the_hotspot_after_setup(self):
        disabled = render_firewall('wlan0', 'wlan1', 'online', True)
        setup = render_firewall('wlan0', 'wlan1', 'online', False, developer=True)
        enabled = render_firewall('wlan0', 'wlan1', 'online', True, developer=True)
        rule = 'iifname "wlan0" ip saddr 10.42.0.0/24 tcp dport 22 accept'
        self.assertNotIn('tcp dport 22 accept', disabled)
        self.assertNotIn('tcp dport 22 accept', setup)
        self.assertIn(rule, enabled)
        self.assertNotIn('iifname "wlan1" tcp dport 22 accept', enabled)
        self.assertLess(disabled.index('tcp dport 22 drop'), disabled.index('ct state established,related accept'))
        self.assertLess(enabled.index(rule), enabled.index('tcp dport 22 drop'))

    def test_dns_modes_have_no_plaintext_online_fallback(self):
        offline = render_dns('wlan0', 'offline', [])
        self.assertIn('address=/#/10.42.0.1', offline)
        online = render_dns('wlan0', 'online', ['192.168.1.1'])
        self.assertIn('server=127.0.0.1#5335', online)
        self.assertNotIn('server=192.168.1.1', online)
        captive = render_dns('wlan0', 'captive', ['192.168.1.1'])
        self.assertIn('server=192.168.1.1', captive)
        self.assertNotIn('address=/#/', captive)

    def test_upstream_dns_values_cannot_inject_configuration(self):
        with self.assertRaises(ValueError):
            render_dns('wlan0', 'captive', ['8.8.8.8\nserver=evil'])
