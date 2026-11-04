"""Validate installed packages and real service parsers in the offline root."""

import secrets
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from travelrouter.policy import render_dns, render_firewall  # noqa: E402
from travelrouter.system import hostapd_config  # noqa: E402


def executable(root, name):
    for directory in ('usr/sbin', 'usr/bin', 'sbin', 'bin'):
        if (root / directory / Path(name).name).is_file():
            return '/' + directory + '/' + Path(name).name
    raise RuntimeError(f'Missing executable: {name}')


def run(root, binary, *args):
    subprocess.run([shutil.which('chroot'), str(root), executable(root, binary), *args], check=True)


def validate(root):
    root = Path(root)
    (root / 'run/travelrouter').mkdir(parents=True, exist_ok=True)
    for entry in (root / 'etc/runlevels').glob('*/*'):
        if not (root / 'etc/init.d' / entry.name).is_file():
            raise RuntimeError(f'Missing OpenRC service: {entry.name}')
    run(root, '/bin/sh', '-c', 'command -v nmcli hostapd dnsmasq nft unbound-checkconf rfkill ip curl python3')
    run(root, '/usr/sbin/unbound-checkconf', '/etc/unbound/unbound.conf')
    for state in ('offline', 'captive', 'online'):
        (root / 'etc/dnsmasq.conf').write_text(render_dns('wlan0', state, ['192.168.1.1']))
        run(root, '/usr/sbin/dnsmasq', '--test')
        rules = render_firewall('wlan0', 'wlan1', state, True)
        (root / 'run/travelrouter/rules.nft').write_text(rules)
        # The workflow gives this container NET_ADMIN for a real kernel check.
        run(root, 'nft', '--check', '--file', '/run/travelrouter/rules.nft')
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
