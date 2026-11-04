"""OpenRC integration, AP discovery, connectivity checks and APK persistence."""

import copy
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from .config import atomic_write
from .network import Network, command
from .policy import LAN_IP, classify_probe, interface, render_dns, render_firewall
from .security import validate_text

LOG = logging.getLogger(__name__)
RUN = Path('/run/travelrouter')


def discover_radios():
    radios = []
    for path in Path('/sys/class/net').iterdir():
        if (path / 'phy80211').exists():
            # A USB radio is preferred for the upstream; an onboard radio for AP.
            usb = '/usb' in str(path.resolve())
            radios.append((usb, path.name))
    return [name for _, name in sorted(radios)]


def hostapd_config(ap, config):
    interface(ap)
    validate_text(config['ssid'], 'SSID', 1, 32)
    validate_text(config['ap_password'], 'Wi-Fi passphrase', 8, 63)
    lines = [f'interface={ap}', 'driver=nl80211', f'ssid2={config["ssid"].encode().hex()}',
             'hw_mode=g', 'channel=6', 'wmm_enabled=1', 'auth_algs=1', 'wpa=2',
             'wpa_key_mgmt=WPA-PSK', 'rsn_pairwise=CCMP', 'ieee80211w=1',
             'ap_isolate=1', 'ctrl_interface=/run/hostapd']
    # A raw PSK avoids configuration injection and ambiguous leading spaces.
    psk = hashlib.pbkdf2_hmac('sha1', config['ap_password'].encode(),
                            config['ssid'].encode(), 4096, 32).hex()
    lines.append(f'wpa_psk={psk}')
    country = config['country']
    if country != '00':
        if len(country) != 2 or not country.isalpha() or not country.isupper():
            raise ValueError('Invalid country code')
        lines += [f'country_code={country}', 'ieee80211d=1']
    return '\n'.join(lines) + '\n'


def boot_medium():
    # Never guess a disk: the expected root-level marker lives on our boot FAT.
    matches = [path.parent for path in Path('/media').glob('*/.travelrouter')]
    if len(matches) != 1:
        raise RuntimeError('Cannot uniquely identify TravelRouter boot medium')
    return matches[0]


def persist_overlay():
    medium = boot_medium()
    command(['/bin/mount', '-o', 'remount,rw', str(medium)])
    fd, name = tempfile.mkstemp(prefix='.travelrouter-', suffix='.tmp', dir=medium)
    os.close(fd)
    temporary = Path(name)
    target = medium / 'travelrouter.apkovl.tar.gz'
    try:
        with tarfile.open(temporary, 'w:gz') as archive:
            archive.add('/etc', arcname='etc', filter=_overlay_filter)
            archive.add('/opt/travelrouter', arcname='opt/travelrouter')
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        if target.exists():
            shutil.copyfile(target, medium / 'travelrouter.previous.tar.gz.bak')
        os.replace(temporary, target)
        directory_fd = os.open(medium, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
        command(['/bin/mount', '-o', 'remount,ro', str(medium)])


def _overlay_filter(info):
    # DHCP generated resolvers and machine identity are regenerated each boot.
    if info.name in {'etc/resolv.conf', 'etc/machine-id'}:
        return None
    return info


def initialize(store):
    RUN.mkdir(parents=True, exist_ok=True, mode=0o755)
    config = store.load()
    radios = []
    for _ in range(20):
        radios = discover_radios()
        if radios:
            break
        time.sleep(1)
    if not radios:
        raise RuntimeError('No supported Wi-Fi adapter found; check firmware/driver on console')
    # Let USB enumeration complete before choosing persistent roles.
    time.sleep(3)
    radios = discover_radios()
    ap = config.get('ap_interface')
    if ap not in radios:
        ap = radios[0]
    wan = next((radio for radio in radios if radio != ap), None)
    if not config['setup_complete']:
        identity = Path(f'/sys/class/net/{ap}/address').read_text().strip().replace(':', '')
        config['ssid'] = 'TravelRouter-' + identity[-4:].upper()
    config['ap_interface'] = ap
    config['wan_interface'] = wan
    store.save(config)
    atomic_write(RUN / 'hardware.json', json.dumps({'ap': ap, 'wan': wan}), 0o644)
    atomic_write('/etc/NetworkManager/conf.d/travelrouter.conf',
                 f'[keyfile]\nunmanaged-devices=interface-name:{ap}\n'
                 '[device]\nwifi.scan-rand-mac-address=yes\n', 0o644)
    command(['/usr/sbin/rfkill', 'unblock', 'wifi'])
    command(['/sbin/ip', 'link', 'set', ap, 'up'])
    command(['/sbin/ip', 'address', 'replace', LAN_IP + '/24', 'dev', ap])
    atomic_write('/etc/hostapd/hostapd.conf', hostapd_config(ap, config))
    atomic_write('/etc/dnsmasq.conf', render_dns(ap, 'offline', []), 0o644)
    command(['/sbin/nft', '-f', '-'], input_text=render_firewall(ap, None, 'offline', False))
    return config


class System:
    def __init__(self, store):
        self.store = store
        config = store.load()
        self.ap = config['ap_interface']
        self.network = Network(config.get('wan_interface'))
        self.lock = threading.RLock()
        self.state = 'offline'
        self.wan = None
        self.last_error = None
        self.pending_restart = 0
        self.last_policy = None
        self.stop = threading.Event()

    def persist(self):
        persist_overlay()

    def save_config(self, data):
        previous = self.store.load()
        self.store.save(data)
        try:
            self.persist()
        except Exception:
            self.store.save(previous)
            raise
        self.pending_restart = time.monotonic() + 3

    def status(self):
        config = self.store.load()
        return {'state': self.state, 'setup_complete': config['setup_complete'],
                'ssid': config['ssid'], 'country': config['country'], 'ap_interface': self.ap,
                'wan_interface': self.network.wan, 'active_upstream': self.wan,
                'last_error': self.last_error, 'address': LAN_IP,
                'dns': 'Unbound DNS-over-TLS' if self.state == 'online' else self.state,
                'firewall': self.last_policy is not None,
                'hardware_note': None if self.network.wan else
                'Connect a supported USB Wi-Fi adapter for upstream Wi-Fi.'}

    def active_wan(self):
        routes = json.loads(command(['/sbin/ip', '-j', '-4', 'route', 'show', 'default']))
        routes.sort(key=lambda route: route.get('metric', 0))
        for route in routes:
            device = route.get('dev')
            if device and device != self.ap:
                return interface(device)
        return None

    def _probe(self, wan):
        if not wan:
            return 'offline'
        args = ['/usr/bin/curl', '--silent', '--show-error', '--noproxy', '*',
                '--interface', wan, '--max-time', '5', '--max-filesize', '4096',
                '--write-out', '\n%{http_code}']
        try:
            response = command([*args, '--proto', '=http',
                                'http://nmcheck.gnome.org/check_network_status.txt'], timeout=7)
            body, code = response.rsplit('\n', 1)
            status = int(code)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError):
            return 'offline'
        tls_ok = False
        if status == 200 and body.strip() == 'NetworkManager is online':
            try:
                response = command([*args, '--proto', '=https',
                                    'https://nmcheck.gnome.org/check_network_status.txt'], timeout=7)
                tls_body, tls_code = response.rsplit('\n', 1)
                tls_ok = tls_code == '200' and tls_body.strip() == 'NetworkManager is online'
            except (RuntimeError, subprocess.TimeoutExpired, ValueError):
                pass
        return classify_probe(True, status, body, tls_ok)

    def apply(self, state, wan):
        config = self.store.load()
        effective = state if config['setup_complete'] else 'offline'
        resolvers = self.network.resolvers(wan) if effective == 'captive' and wan else []
        key = (effective, wan, config['setup_complete'], tuple(resolvers))
        if key == self.last_policy:
            return
        rules = render_firewall(self.ap, wan, effective, config['setup_complete'])
        # Transactional nft replacement must succeed before advertising a new state.
        command(['/sbin/nft', '-f', '-'], input_text=rules)
        atomic_write('/etc/dnsmasq.conf', render_dns(self.ap, effective, resolvers), 0o644)
        command(['/sbin/rc-service', 'dnsmasq', 'restart'])
        self.last_policy = key
        self.state, self.wan = effective, wan

    def loop(self):
        candidate, observations = 'offline', 0
        while not self.stop.is_set():
            try:
                # Probes run outside the mutation lock so the panel stays responsive.
                wan = self.active_wan()
                state = self._probe(wan)
                with self.lock:
                    radios = discover_radios()
                    self.network.wan = next((radio for radio in radios if radio != self.ap), None)
                    if state == candidate:
                        observations += 1
                    else:
                        candidate, observations = state, 1
                    if observations >= 2 or not wan:
                        self.apply(state, wan)
                    if self.pending_restart and time.monotonic() >= self.pending_restart:
                        config = self.store.load()
                        atomic_write('/etc/hostapd/hostapd.conf', hostapd_config(self.ap, config))
                        command(['/sbin/rc-service', 'hostapd', 'restart'])
                        self.pending_restart = 0
                    self.last_error = None
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                LOG.exception('Router state update failed')
                self.last_error = 'A network operation failed; check the local console log.'
            self.stop.wait(5)

    def scan(self):
        return self.network.scan()

    def connect(self, **data):
        identifier = self.network.connect(**data)
        self.persist()
        return identifier

    def saved(self):
        return self.network.saved()

    def saved_action(self, **data):
        self.network.saved_action(**data)
        self.persist()

    def export(self):
        data = copy.deepcopy(self.store.load())
        for secret in ('admin_hash', 'ap_password'):
            data.pop(secret, None)
        return data
