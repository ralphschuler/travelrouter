"""Validate installed packages and real service parsers in the offline root."""

import os
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from travelrouter.policy import render_dns, render_firewall, render_unbound  # noqa: E402
from travelrouter.privacy import proxy_config  # noqa: E402
from travelrouter.system import hostapd_config  # noqa: E402


def executable(root, name):
    for directory in ('usr/sbin', 'usr/bin', 'sbin', 'bin'):
        if (root / directory / Path(name).name).is_file():
            return '/' + directory + '/' + Path(name).name
    raise RuntimeError(f'Missing executable: {name}')


def run(root, binary, *args):
    # All command names/arguments originate in this build script, never HTTP.
    subprocess.run([shutil.which('chroot'), str(root), executable(root, binary), *args], check=True)  # nosec B603


def validate_wireless_regulatory_database(root):
    firmware = Path(root) / 'lib/firmware'
    database = firmware / 'regulatory.db'
    signature = firmware / 'regulatory.db.p7s'
    if not database.is_file():
        raise RuntimeError('Missing signed wireless regulatory database; install wireless-regdb')
    if not signature.is_file():
        raise RuntimeError('Missing wireless regulatory database signature')


def validate(root):
    root = Path(root)
    validate_wireless_regulatory_database(root)
    (root / 'run/travelrouter').mkdir(parents=True, exist_ok=True)
    (root / 'run/unbound').mkdir(parents=True, exist_ok=True)
    for name, minor in (('null', 3), ('random', 8), ('urandom', 9)):
        path = root / 'dev' / name
        if path.exists() and not path.is_char_device():
            path.unlink()
        if not path.exists():
            os.mknod(path, stat.S_IFCHR | 0o666, os.makedev(1, minor))
    (root / 'etc/unbound/travelrouter-blocks.conf').write_text('local-zone: "blocked.example" always_nxdomain\n')
    for entry in (root / 'etc/runlevels').glob('*/*'):
        if not (root / 'etc/init.d' / entry.name).is_file():
            raise RuntimeError(f'Missing OpenRC service: {entry.name}')
    for name in ('nmcli', 'hostapd', 'dnsmasq', 'nft', 'unbound-checkconf', 'rfkill', 'ip', 'curl', 'python3', 'openssl'):
        print('Checking installed executable:', executable(root, name), flush=True)
    run(root, 'python3', '--version')
    run(root, 'openssl', 'version')
    for mode in ('dot', 'recursive'):
        (root / 'etc/unbound/unbound.conf').write_text(render_unbound(mode))
        run(root, 'unbound-checkconf', '/etc/unbound/unbound.conf')
    for state in ('offline', 'captive', 'online'):
        (root / 'etc/dnsmasq.conf').write_text(render_dns('wlan0', state, ['192.168.1.1']))
        run(root, '/usr/sbin/dnsmasq', '--test')
        for privacy in ('direct', 'wireguard', 'proxy'):
            rules = render_firewall('wlan0', 'wlan1', state, True, privacy, ['8.8.8.0/24'])
            (root / 'run/travelrouter/rules.nft').write_text(rules)
            run(root, 'nft', '--check', '--file', '/run/travelrouter/rules.nft')
    for kind in ('https', 'socks5'):
        proxy = proxy_config({'type': kind, 'server': 'proxy.example.org', 'port': 443,
                              'acknowledge_plaintext': True}, '192.0.2.9', 'wlan1')
        import json
        (root / 'run/travelrouter/proxy.json').write_text(json.dumps(proxy))
        run(root, 'sing-box', 'check', '-c', '/run/travelrouter/proxy.json')
    config = {'ssid': 'Validation AP', 'ap_password': secrets.token_urlsafe(20), 'country': 'DE'}
    (root / 'etc/hostapd/hostapd.conf').write_text(hostapd_config('validation0', config))
    # hostapd has no syntax-only mode. It must parse before reaching nl80211.
    result = subprocess.run([shutil.which('chroot'), str(root), executable(root, 'hostapd'),
                             '/etc/hostapd/hostapd.conf'], text=True, capture_output=True,
                            timeout=10, check=False)  # nosec B603
    output = result.stdout + result.stderr
    if 'errors found' in output or 'unknown configuration item' in output:
        raise RuntimeError('hostapd rejected configuration: ' + output)
    if not any(term in output for term in ('nl80211', 'initialize driver', 'No such device')):
        raise RuntimeError('hostapd did not reach driver initialization: ' + output)
    print('Offline package install and service configuration validation passed')


if __name__ == '__main__':
    validate(sys.argv[1])
