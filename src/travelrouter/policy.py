"""Pure policy rendering: no shell, services, or privileged side effects."""

import ipaddress
import re

LAN_IP = '10.42.0.1'
LAN_NETWORK = '10.42.0.0/24'
HTTP_BODY = 'NetworkManager is online'


def interface(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', value):
        raise ValueError('Invalid network interface')
    return value


def classify_probe(link, http_status, body, https_ok):
    if not link:
        return 'offline'
    if http_status == 200 and body.strip() == HTTP_BODY:
        return 'online' if https_ok else 'offline'
    if http_status in (200, 301, 302, 303, 307, 308, 511):
        return 'captive'
    return 'offline'


def render_dns(ap, state, resolvers):
    interface(ap)
    if state not in {'offline', 'captive', 'online'}:
        raise ValueError('Invalid connectivity state')
    lines = [f'interface={ap}', 'bind-dynamic', f'listen-address={LAN_IP}',
             'no-resolv', 'no-hosts', 'domain-needed', 'bogus-priv',
             'dhcp-authoritative', 'dhcp-range=10.42.0.50,10.42.0.200,255.255.255.0,12h',
             f'dhcp-option=3,{LAN_IP}', f'dhcp-option=6,{LAN_IP}',
             'dhcp-leasefile=/run/travelrouter/dnsmasq.leases',
             'address=/router.home.arpa/10.42.0.1', 'local=/home.arpa/',
             'cache-size=500', 'dns-forward-max=150', 'stop-dns-rebind',
             'rebind-localhost-ok', 'dhcp-script=', 'log-facility=-']
    if state == 'offline':
        lines += [f'address=/#/{LAN_IP}', 'local=/#/']
    elif state == 'online':
        lines.append('server=127.0.0.1#5335')
    else:
        # Hotel login servers often resolve to private addresses. Permit this
        # only during a detected upstream captive login.
        lines.remove('stop-dns-rebind')
        for resolver in resolvers:
            parsed = ipaddress.ip_address(resolver)
            if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified:
                raise ValueError('Invalid upstream DNS address')
            lines.append(f'server={parsed}')
    return '\n'.join(lines) + '\n'


def render_firewall(ap, wan, state, setup_complete):
    interface(ap)
    if wan:
        interface(wan)
        if wan == ap:
            raise ValueError('AP and upstream must use separate interfaces')
    if state not in {'offline', 'captive', 'online'}:
        raise ValueError('Invalid connectivity state')
    forwarding = bool(wan and setup_complete and state in {'online', 'captive'})
    lines = ['destroy table inet travelrouter', 'table inet travelrouter {',
             ' chain input { type filter hook input priority filter; policy drop;',
             '  iifname "lo" accept', '  ct state invalid drop',
             '  meta nfproto ipv6 drop', '  ct state established,related accept',
             f'  iifname "{ap}" udp sport 68 udp dport 67 accept',
             f'  iifname "{ap}" ip saddr {LAN_NETWORK} udp dport 53 accept',
             f'  iifname "{ap}" ip saddr {LAN_NETWORK} tcp dport {{ 53, 80 }} accept',
             f'  iifname "{ap}" ip saddr {LAN_NETWORK} icmp type echo-request limit rate 5/second accept']
    if wan:
        lines.append(f'  iifname "{wan}" udp sport 67 udp dport 68 accept')
    lines += [' }', ' chain forward { type filter hook forward priority filter; policy drop;',
              '  ct state invalid drop', '  meta nfproto ipv6 drop']
    if forwarding:
        lines += [f'  iifname "{wan}" oifname "{ap}" ct state established,related accept',
                  f'  iifname "{ap}" ip saddr != {LAN_NETWORK} drop']
        if state == 'online':
            lines.append(f'  iifname "{ap}" ip daddr {{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 }} drop')
        lines.append(f'  iifname "{ap}" oifname "{wan}" ip saddr {LAN_NETWORK} accept')
    lines += [' }', ' chain prerouting { type nat hook prerouting priority dstnat; policy accept;',
              f'  iifname "{ap}" udp dport 53 redirect to :53',
              f'  iifname "{ap}" tcp dport 53 redirect to :53']
    if not setup_complete or state == 'offline':
        lines.append(f'  iifname "{ap}" ip daddr != {LAN_IP} tcp dport 80 redirect to :80')
    lines += [' }', ' chain postrouting { type nat hook postrouting priority srcnat; policy accept;']
    if forwarding:
        lines.append(f'  ip saddr {LAN_NETWORK} oifname "{wan}" masquerade')
    lines += [' }', '}']
    return '\n'.join(lines) + '\n'
