"""OpenRC integration, AP discovery, connectivity checks and APK persistence."""

import copy
import hashlib
import json
import logging
import os
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from .backup import seal, unseal, validate_payload
from .config import atomic_write
from .developer import configure_files, host_fingerprint, validate_public_key
from .filtering import Filtering, validate_settings
from .network import Network, command, write_profile
from .policy import LAN_IP, classify_probe, interface, render_dns, render_firewall, render_unbound
from .privacy import PROXY_INTERFACE, VPN_INTERFACE, Privacy
from .security import validate_text
from .tether import discover_usb_networks, pair_iphone, perform_usb_action
from .updates import Updates

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
    temporary = None
    target = medium / 'travelrouter.apkovl.tar.gz'
    try:
        fd, name = tempfile.mkstemp(prefix='.travelrouter-', suffix='.tmp', dir=medium)
        os.close(fd)
        temporary = Path(name)
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
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        finally:
            command(['/bin/mount', '-o', 'remount,ro', str(medium)])


def _overlay_filter(info):
    # DHCP generated resolvers and machine identity are regenerated each boot.
    if info.name in {'etc/resolv.conf', 'etc/machine-id'}:
        return None
    return info


def initialize(store):
    # Local DNS binds before NetworkManager finishes its asynchronous startup.
    # Establish the loopback address explicitly rather than depend on that race.
    command(['/sbin/ip', 'address', 'replace', '127.0.0.1/8', 'dev', 'lo'])
    command(['/sbin/ip', 'link', 'set', 'lo', 'up'])
    RUN.mkdir(parents=True, exist_ok=True, mode=0o755)
    unbound_run = Path('/run/unbound')
    unbound_run.mkdir(parents=True, exist_ok=True)
    unbound_user = pwd.getpwnam('unbound')
    os.chown(unbound_run, unbound_user.pw_uid, unbound_user.pw_gid)
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
    atomic_write('/etc/unbound/unbound.conf', render_unbound(config.get('dns_mode', 'dot')), 0o644)
    filtering = Filtering(store)
    zones, _ = filtering.rules()
    atomic_write('/etc/unbound/travelrouter-blocks.conf', zones, 0o644)
    command(['/sbin/nft', '-f', '-'], input_text=render_firewall(
        ap, None, 'offline', config['setup_complete'], developer=config.get('developer_enabled') is True))
    return config


class System:
    def __init__(self, store):
        self.store = store
        config = store.load()
        self.ap = config['ap_interface']
        self.network = Network(config.get('wan_interface'))
        self.privacy = Privacy(store)
        self.filtering = Filtering(store)
        self.filter_revision = 0
        self.last_dns_mode = config.get('dns_mode', 'dot')
        self.lock = threading.RLock()
        self.state = 'offline'
        self.wan = None
        self.last_error = None
        self.pending_restart = 0
        self.last_policy = None
        self.stop = threading.Event()
        self.updates = Updates(self)

    def persist(self):
        self.ensure_no_pending_update()
        persist_overlay()

    def ensure_no_pending_update(self):
        if (boot_medium() / '.travelrouter-update').exists():
            raise ValueError('Restart to confirm or roll back the pending update before changing settings.')

    def persist_for_update(self):
        marker = boot_medium() / '.travelrouter-update'
        try:
            parts = marker.read_text().split()
        except OSError as error:
            raise ValueError('The prepared update transaction is unavailable') from error
        if len(parts) != 5 or parts[0] != 'v1' or parts[1] not in {'application', 'packages'} or parts[2] != 'prepared':
            raise ValueError('The prepared update transaction is unavailable')
        persist_overlay()

    def save_config(self, data):
        self.ensure_no_pending_update()
        previous = self.store.load()
        self.store.save(data)
        try:
            self.persist()
        except Exception:
            self.store.save(previous)
            raise
        if any(previous[key] != data[key] for key in ('ssid', 'ap_password', 'country')):
            self.pending_restart = time.monotonic() + 3

    def save_dns(self, mode):
        render_unbound(mode)
        config = self.store.load()
        config['dns_mode'] = mode
        self.save_config(config)

    def save_developer(self, data):
        self.ensure_no_pending_update()
        enabled = data.get('enabled')
        if type(enabled) is not bool:
            raise ValueError('Developer mode must be enabled or disabled')
        key = validate_public_key(data.get('public_key')) if enabled else ''
        old_config = self.store.load()
        directory = Path('/etc/travelrouter')
        paths = [Path('/etc/shadow'), *(directory / name for name in
                 ('developer-enabled', 'ssh_authorized_keys', 'sshd_config', 'ssh_host_ed25519_key'))]
        before = {path: path.read_text() if path.exists() else None for path in paths}
        command(['/sbin/rc-service', '--nodeps', 'travelrouter-ssh', 'stop'])
        try:
            configure_files(Path('/etc'), enabled, key)
            if enabled:
                command(['/usr/sbin/sshd', '-t', '-f', '/etc/travelrouter/sshd_config'])
            config = self.store.load()
            config['developer_enabled'] = enabled
            self.save_config(config)
            self.last_policy = None
            self.apply(self.state, self.wan)
            if enabled:
                command(['/sbin/rc-service', '--nodeps', 'travelrouter-ssh', 'start'])
        except Exception:
            # Restore both the live state and its persisted overlay; never log keys.
            try:
                for path, content in before.items():
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, content)
                self.store.save(old_config)
                self.persist()
                self.last_policy = None
                self.apply(self.state, self.wan)
                if old_config.get('developer_enabled') is True:
                    command(['/sbin/rc-service', '--nodeps', 'travelrouter-ssh', 'start'])
            except Exception:
                LOG.error('Could not restore developer access settings; inspect the local console')
            raise

    def save_filtering(self, data):
        self.ensure_no_pending_update()
        settings = validate_settings(data)
        missing = [country for country in settings['countries']
                   if not (self.filtering.directory / (country + '.zone')).is_file()]
        if missing:
            self.filtering.refresh(settings)
        self.filtering.rules(settings)
        config = self.store.load()
        config['filtering'] = settings
        self.save_config(config)
        self.filter_revision += 1

    def refresh_filtering(self):
        self.ensure_no_pending_update()
        self.filtering.refresh()
        self.persist()
        self.filter_revision += 1

    def backup(self, password):
        config = self.store.load()
        for key in ('ap_interface', 'wan_interface', 'developer_enabled'):
            config.pop(key, None)
        wireguard = Path('/etc/wireguard/trvpn0.conf')
        proxy = Path('/etc/travelrouter/proxy-source.json')
        payload = {'version': 1, 'config': config, 'networks': self.network.export_profiles(),
                   'wireguard': wireguard.read_text() if wireguard.exists() else None,
                   'proxy': json.loads(proxy.read_text()) if proxy.exists() else None}
        return seal(payload, password)

    def restore(self, envelope, password):
        self.ensure_no_pending_update()
        payload = validate_payload(unseal(envelope, password))
        command(['/sbin/nft', '-f', '-'], input_text=render_firewall(self.ap, self.wan, 'offline', False, self.privacy.mode))
        self.privacy.stop()
        old_config = self.store.load()
        paths = list(self.network.profiles.glob('travelrouter-*.nmconnection'))
        paths += [Path('/etc/wireguard/trvpn0.conf'), Path('/etc/travelrouter/proxy-source.json'),
                  Path('/etc/travelrouter/proxy.json')]
        previous = {path: path.read_text() if path.exists() else None for path in paths}
        created = []
        try:
            for record in payload.get('networks', []):
                path, _ = write_profile(self.network.profiles, record['ssid'],
                                         record.get('password', ''), record.get('allow_open', False))
                content = path.read_text().replace('autoconnect=false', 'autoconnect=true')
                content = content.replace('autoconnect-priority=10',
                                          'autoconnect-priority=' + str(record.get('priority', 10)))
                atomic_write(path, content)
                created.append(path)
            for path in paths:
                path.unlink(missing_ok=True)
            if payload.get('wireguard'):
                atomic_write('/etc/wireguard/trvpn0.conf', payload['wireguard'])
            if payload.get('proxy'):
                atomic_write('/etc/travelrouter/proxy-source.json', json.dumps(payload['proxy']))
            config = payload['config']
            config.update(ap_interface=self.ap, wan_interface=self.network.wan)
            # SSH keys and host identity remain specific to this router.
            config['developer_enabled'] = old_config.get('developer_enabled') is True
            self.save_config(config)
            self.network.nm('connection', 'reload')
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            for path, text in previous.items():
                if text is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, text)
            self.store.save(old_config)
            raise
        self.last_policy = None
        self.filter_revision += 1
        self.filtering.last_update = 0

    def configure_privacy(self, data):
        self.ensure_no_pending_update()
        # Drop forwarding before touching route tables or tunnel processes.
        command(['/sbin/nft', '-f', '-'],
                input_text=render_firewall(self.ap, self.wan, 'offline', False, self.privacy.mode))
        self.last_policy = None
        self.privacy.stop()
        mode = self.privacy.prepare(data, self.wan)
        config = self.store.load()
        config['privacy_mode'] = mode
        self.save_config(config)
        self.apply('offline', self.wan)
        self.privacy.start()

    def status(self):
        config = self.store.load()
        return {'state': self.state, 'setup_complete': config['setup_complete'],
                'ssid': config['ssid'], 'country': config['country'], 'ap_interface': self.ap,
                'wan_interface': self.network.wan, 'active_upstream': self.wan,
                'privacy_mode': self.privacy.mode,
                'tunnel_ready': bool(self.privacy.egress and Path('/sys/class/net/' + self.privacy.egress).exists()),
                'dns_mode': config.get('dns_mode', 'dot'),
                'last_error': self.last_error, 'address': LAN_IP,
                'dns': ('Unbound DNS-over-TLS' if config.get('dns_mode', 'dot') == 'dot'
                        else 'Unbound recursive DNS') if self.state == 'online' else self.state,
                'firewall': self.last_policy is not None,
                'filtering': self.filtering.status(),
                'updates': {**self.updates.status, 'automatic': config.get('auto_updates', False)},
                'developer_enabled': config.get('developer_enabled') is True,
                'developer_host_fingerprint': (host_fingerprint(Path('/etc/travelrouter/ssh_host_ed25519_key'))
                                               if config.get('developer_enabled') is True else None),
                'hardware_note': None if self.network.wan else
                'Connect a supported USB Wi-Fi adapter for upstream Wi-Fi.'}

    def active_wan(self):
        routes = json.loads(command(['/sbin/ip', '-j', '-4', 'route', 'show', 'default']))
        routes.sort(key=lambda route: route.get('metric', 0))
        for route in routes:
            device = route.get('dev')
            if device and device not in {self.ap, VPN_INTERFACE, PROXY_INTERFACE}:
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
        if self.filtering.status()['missing_countries']:
            effective = 'offline'
        resolvers = self.network.resolvers(wan) if effective == 'captive' and wan else []
        dns_mode = config.get('dns_mode', 'dot')
        developer = config.get('developer_enabled') is True
        key = (effective, wan, config['setup_complete'], tuple(resolvers), dns_mode, developer,
               self.privacy.mode, self.filter_revision)
        if key == self.last_policy:
            return
        zones, regions = self.filtering.rules()
        rules = render_firewall(self.ap, wan, effective, config['setup_complete'], self.privacy.mode, regions,
                                developer=developer)
        # Transactional nft replacement must succeed before advertising a new state.
        command(['/sbin/nft', '-f', '-'], input_text=rules)
        zones_path = Path('/etc/unbound/travelrouter-blocks.conf')
        zones_changed = not zones_path.exists() or zones_path.read_text() != zones
        if dns_mode != self.last_dns_mode or zones_changed:
            atomic_write(zones_path, zones, 0o644)
            atomic_write('/etc/unbound/unbound.conf', render_unbound(dns_mode), 0o644)
            command(['/sbin/rc-service', '--nodeps', 'unbound', 'restart'])
            self.last_dns_mode = dns_mode
        dns_path = Path('/etc/dnsmasq.conf')
        dns_content = render_dns(self.ap, effective, resolvers)
        if not dns_path.exists() or dns_path.read_text() != dns_content:
            atomic_write(dns_path, dns_content, 0o644)
            # A normal OpenRC restart would stop this controller through dependencies.
            command(['/sbin/rc-service', '--nodeps', 'dnsmasq', 'restart'])
        self.last_policy = key
        self.state, self.wan = effective, wan

    def loop(self):
        candidate, observations = 'offline', 0
        while not self.stop.is_set():
            try:
                # Probes run outside the mutation lock so the panel stays responsive.
                wan = self.active_wan()
                with self.lock:
                    if self.store.load()['setup_complete'] and wan:
                        self.privacy.start()
                probe_interface = self.privacy.egress or wan
                state = self._probe(probe_interface)
                if self.privacy.mode != 'direct' and state != 'online':
                    state = 'offline'
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
                        command(['/sbin/rc-service', '--nodeps', 'hostapd', 'restart'])
                        self.pending_restart = 0
                    self.last_error = None
                if state == 'online' and (self.filtering.last_update == 0 or time.monotonic() - self.filtering.last_update > 86400):
                    try:
                        # Downloading lists may take time; leave the panel responsive.
                        with self.lock:
                            self.ensure_no_pending_update()
                        self.filtering.refresh()
                        with self.lock:
                            self.persist()
                            self.filter_revision += 1
                    except (OSError, ValueError, RuntimeError):
                        self.filtering.error = 'List refresh failed; previous valid lists remain in use.'
                        self.filtering.last_update = time.monotonic() - 82800
                if (self.state == 'online' and self.store.load().get('auto_updates', False)
                        and not self.updates.status['busy'] and (self.updates.last_check == 0 or time.monotonic() - self.updates.last_check > 86400)):
                    self.updates.start('packages')
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                LOG.exception('Router state update failed')
                self.last_error = 'A network operation failed; check the local console log.'
            self.stop.wait(5)

    def scan(self):
        return self.network.scan()

    def usb_networks(self):
        return {'devices': discover_usb_networks(), 'active': self.wan}

    def usb_network_action(self, data):
        if data.get('action') == 'pair-iphone':
            pair_iphone()
        else:
            perform_usb_action(self.network, data.get('action'), data.get('interface'))

    def connect(self, **data):
        self.ensure_no_pending_update()
        identifier = self.network.connect(**data)
        self.persist()
        return identifier

    def saved(self):
        return self.network.saved()

    def saved_action(self, **data):
        self.ensure_no_pending_update()
        self.network.saved_action(**data)
        self.persist()

    def export(self):
        data = copy.deepcopy(self.store.load())
        for secret in ('admin_hash', 'ap_password'):
            data.pop(secret, None)
        return data
