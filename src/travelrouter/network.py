"""Small, shell-free NetworkManager adapter."""

import configparser
import re
import shutil
import subprocess
import uuid as uuid_module
from pathlib import Path

from .config import atomic_write
from .policy import interface
from .security import validate_text

WIFI_CONNECT_TIMEOUT = 90


class CommandFailure(RuntimeError):
    def __init__(self, program, returncode):
        self.returncode = returncode
        super().__init__(f'{Path(program).name} operation failed')


def command(arguments, timeout=20, input_text=None):
    executable = shutil.which(Path(arguments[0]).name, path='/usr/sbin:/usr/bin:/sbin:/bin')
    if not executable:
        raise RuntimeError('Required router executable is missing')
    arguments = [executable, *arguments[1:]]
    result = subprocess.run(arguments, input=input_text, capture_output=True, text=True,
                            timeout=timeout, check=False)  # nosec B603
    if result.returncode:
        # External messages may contain credentials; do not return them to HTTP.
        raise CommandFailure(arguments[0], result.returncode)
    return result.stdout


def parse_nmcli(line):
    fields, current, escaped = [], '', False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(current)
            current = ''
        else:
            current += char
    fields.append(current)
    return fields


def write_profile(directory, ssid, password, allow_open):
    validate_text(ssid, 'SSID', 1, 32)
    if password:
        validate_text(password, 'Upstream Wi-Fi password', 8, 63)
        if not password.isascii():
            raise ValueError('Upstream WPA passphrase must use ASCII characters')
    elif not allow_open:
        raise ValueError('Explicitly allow an open network before joining it')
    identifier = str(uuid_module.uuid4())
    # NetworkManager keyfiles accept a decimal byte array for an arbitrary SSID.
    encoded_ssid = ';'.join(str(value) for value in ssid.encode()) + ';'
    content = (f'[connection]\nid=TravelRouter upstream\nuuid={identifier}\n'
               'type=wifi\nautoconnect=false\nautoconnect-priority=10\n'
               f'\n[wifi]\nmode=infrastructure\nssid={encoded_ssid}\n'
               '\n[ipv4]\nmethod=auto\nroute-metric=100\n'
               '\n[ipv6]\nmethod=disabled\n')
    if password:
        escaped = password.replace('\\', '\\\\').replace(' ', r'\s')
        content += f'\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={escaped}\n'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / f'travelrouter-{identifier}.nmconnection'
    atomic_write(path, content)
    return path, identifier


class Network:
    def __init__(self, wan=None):
        self.wan = wan
        self.profiles = Path('/etc/NetworkManager/system-connections')

    def nm(self, *arguments, timeout=20):
        return command(['/usr/bin/nmcli', '--wait', str(min(timeout, 90)), *arguments],
                       timeout=timeout + 5)

    def scan(self):
        if not self.wan:
            return []
        output = self.nm('-t', '--escape', 'yes', '-f', 'SSID,SECURITY,SIGNAL,IN-USE',
                         'device', 'wifi', 'list', 'ifname', self.wan, '--rescan', 'yes')
        networks = {}
        for line in output.splitlines():
            row = parse_nmcli(line)
            if len(row) != 4 or not row[0]:
                continue
            ssid, security, signal, active = row
            try:
                strength = int(signal)
            except ValueError:
                continue
            record = {'ssid': ssid, 'security': security or 'Open', 'signal': strength,
                      'active': active == '*'}
            if ssid not in networks or strength > networks[ssid]['signal']:
                networks[ssid] = record
        return sorted(networks.values(), key=lambda record: -record['signal'])

    def connect(self, ssid, password, allow_open=False):
        if not self.wan:
            raise ValueError('Connect a supported second Wi-Fi adapter for upstream access')
        path, identifier = write_profile(self.profiles, ssid, password, allow_open)
        try:
            self.nm('connection', 'load', str(path))
            self.nm('connection', 'up', 'uuid', identifier, 'ifname', interface(self.wan), timeout=WIFI_CONNECT_TIMEOUT)
            self.nm('connection', 'modify', 'uuid', identifier, 'connection.autoconnect', 'yes')
        except (RuntimeError, subprocess.TimeoutExpired):
            path.unlink(missing_ok=True)
            self.nm('connection', 'reload')
            raise
        return identifier

    def saved(self):
        output = self.nm('-t', '--escape', 'yes', '-f', 'UUID,NAME,TYPE', 'connection', 'show')
        records = []
        for line in output.splitlines():
            row = parse_nmcli(line)
            if len(row) == 3 and row[2] == '802-11-wireless':
                identifier, _, _ = row
                if not (self.profiles / f'travelrouter-{identifier}.nmconnection').exists():
                    continue
                name = self.nm('-g', '802-11-wireless.ssid', 'connection', 'show',
                               'uuid', identifier).strip()
                priority = self.nm('-g', 'connection.autoconnect-priority', 'connection',
                                   'show', 'uuid', identifier).strip()
                records.append({'uuid': identifier, 'ssid': name, 'priority': int(priority)})
        return records

    def saved_action(self, action, identifier, priority=10):
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9-]{36}', identifier):
            raise ValueError('Invalid saved network identifier')
        if not (self.profiles / f'travelrouter-{identifier}.nmconnection').is_file():
            raise ValueError('Unknown saved network')
        if action == 'activate':
            if not self.wan:
                raise ValueError('No upstream Wi-Fi adapter')
            wan = interface(self.wan)
            active = self.nm('-t', '--escape', 'yes', '-f', 'UUID,DEVICE', 'connection', 'show', '--active')
            if any(parse_nmcli(line) == [identifier, wan] for line in active.splitlines()):
                return
            self.nm('connection', 'up', 'uuid', identifier, 'ifname', wan, timeout=WIFI_CONNECT_TIMEOUT)
        elif action == 'forget':
            self.nm('connection', 'delete', 'uuid', identifier)
        elif action == 'priority':
            if type(priority) is not int or not -100 <= priority <= 100:
                raise ValueError('Priority must be an integer between -100 and 100')
            self.nm('connection', 'modify', 'uuid', identifier,
                    'connection.autoconnect-priority', str(priority))
        else:
            raise ValueError('Unknown saved-network action')

    def resolvers(self, wan):
        output = self.nm('-g', 'IP4.DNS', 'device', 'show', interface(wan))
        return [line.strip() for line in output.splitlines() if line.strip()]

    def export_profiles(self):
        records = []
        for path in self.profiles.glob('travelrouter-*.nmconnection'):
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(path)
            raw = parser['wifi']['ssid']
            if re.fullmatch(r'(?:[0-9]{1,3};)+', raw):
                ssid = bytes(int(value) for value in raw.split(';') if value).decode()
            else:
                ssid = raw
            password = parser.get('wifi-security', 'psk', fallback='')
            password = re.sub(r'\\([sntr\\])', lambda match: {'s': ' ', 'n': '\n', 't': '\t',
                              'r': '\r', '\\': '\\'}[match[1]], password)
            records.append({'ssid': ssid, 'password': password, 'allow_open': not bool(password),
                            'priority': parser.getint('connection', 'autoconnect-priority', fallback=10)})
        return records
